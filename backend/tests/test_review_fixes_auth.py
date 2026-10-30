"""Authorization gaps found in the 29 October 2026 review (design: Roles; Drafts, one editor at a time)."""
import bmu.app as app_module
from bmu.storage import now
from test_flow import _second_user, new_job

INTERN_DELETE_RAN = "This job has already run, so only staff can delete it. You can still edit it."


def _ran_once_open_to_interns(api, login, add_uploaded, worker, services, fail_on):
    """A job an intern created, run once by staff with a Partial document, back in Drafts and open to interns."""
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Ran once"}).json()["id"]
    intern.post(f"/api/jobs/{job}/close")
    login()
    assert api.post(f"/api/jobs/{job}/open").status_code == 200
    add_uploaded(job, ["20-0501_a.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "mediaonly"})
    fail_on("media", status=403)  # refused: the document created nothing, so it could be deleted
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    api.post(f"/api/jobs/{job}/close")
    assert intern.post(f"/api/jobs/{job}/open").status_code == 200
    return intern, job


def test_an_intern_cannot_delete_a_job_that_ran_by_deleting_its_last_document(api, login, add_uploaded, worker, services, fail_on):
    intern, job = _ran_once_open_to_interns(api, login, add_uploaded, worker, services, fail_on)
    for r in (intern.delete(f"/api/jobs/{job}/rows/1"), intern.post(f"/api/jobs/{job}/rows/delete", json={"rows": [1]})):
        assert r.status_code == 403 and r.json()["detail"] == INTERN_DELETE_RAN, r.text
    assert services.storage.get_job(job)["status"] == "Draft" and services.storage.get_row(job, 1)


def test_upload_endpoints_need_the_editor_and_respect_staff_only(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    api.post(f"/api/jobs/{job}/close")
    intern = _second_user(services, "intern")
    for r in (intern.post(f"/api/jobs/{job}/rows/{n}/uploaded"), intern.post(f"/api/jobs/{job}/rows/{n}/upload-failed"),
              intern.post(f"/api/jobs/{job}/rows/{n}/thumbnail", content=b"x")):
        assert r.status_code == 403, r.text
    assert services.storage.get_row(job, n)["upload"]["s"] == "done"
    # staff who aren't editing the draft can't mark its uploads either
    other = _second_user(services, "limited")
    assert other.post(f"/api/jobs/{job}/rows/{n}/upload-failed").status_code == 409
    assert services.storage.get_row(job, n)["upload"]["s"] == "done"


def test_an_edit_after_a_take_over_is_not_saved(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    other = _second_user(services, "limited")
    since = other.post(f"/api/jobs/{job}/open").json()["detail"]["editingSince"]
    assert other.post(f"/api/jobs/{job}/open", json={"takeOverSince": since}).status_code == 200
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"description": "late"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_editing"
    assert services.storage.get_row(job, n).get("description") != "late"


def test_a_row_write_checks_the_draft_and_its_editor_in_the_same_request(api, login, add_uploaded, services):
    """The editor read the job (still its draft), then the job was submitted before the row was written."""
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    session = services.storage.get_job(job)["editingSession"]
    row = services.storage.get_row(job, n)
    services.storage.update_job(job, {"status": "Queued"})
    row["description"] = "after submit"
    try:
        services.storage.put_row(job, row, editing=session)
        raise AssertionError("saved")
    except app_module.NotEditing:
        pass
    assert services.storage.get_row(job, n).get("description") != "after submit"


def test_files_added_at_once_cannot_take_a_job_past_its_limit(api, login, services):
    login()
    job = new_job(api)
    services.storage.update_job(job, {"rowCount": services.settings.max_rows - 1})  # as if another batch just landed
    files = [{"name": f"15-1234_{i}.jpg", "size": 3, "type": "image/jpeg"} for i in range(2)]
    r = api.post(f"/api/jobs/{job}/files", json={"files": files})
    assert r.status_code == 413
    # the check before the write passed (the job looked emptier); the write itself refuses
    real = services.storage.get_job
    services.storage.get_job = lambda jid: {**real(jid), "rowCount": 0} if jid == job else real(jid)
    try:
        r = api.post(f"/api/jobs/{job}/files", json={"files": files})
    finally:
        services.storage.get_job = real
    assert r.status_code == 413 and int(services.storage.get_job(job)["rowCount"]) == services.settings.max_rows - 1


def test_an_update_after_a_job_was_deleted_does_not_bring_it_back(api, login, services):
    login()
    job = new_job(api)
    assert api.delete(f"/api/jobs/{job}").status_code == 200
    assert services.storage.update_job(job, {"deletedRows": []}) is False
    assert services.storage.get_job(job) is None


def test_a_staff_member_whose_role_was_removed_loses_draft_rights_within_minutes(api, login, add_uploaded, fake, services, monkeypatch):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    fake.role_overrides["admin"] = []  # removed in CollectionSpace after signing in
    assert api.patch(f"/api/jobs/{job}/rows/{n}", json={"description": "a"}).status_code == 200  # read minutes ago
    later = now() + app_module.ROLE_RECHECK_SECONDS + 1
    monkeypatch.setattr(app_module, "now", lambda: later)
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"description": "b"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_role"


def test_a_queued_job_whose_submitter_lost_the_staff_role_does_not_run(api, login, add_uploaded, worker, services, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.role_overrides["admin"] = ["ROLE_14_BMU_INTERN"]
    media_before = len(fake.media)
    worker.tick()
    j = services.storage.get_job(job)
    assert j["status"] == "Failed" and j["code"] == "not_staff" and "admin" in j["codeDetail"]
    assert len(fake.media) == media_before and services.storage.get_credential(job) is None
