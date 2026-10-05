"""Three kinds of result (design: Roles): a problem with the job ("needs fixing"), a document that needs someone
who can create Objects, and a problem with the user's account. Only the first is shown as a mistake in the job."""
from test_flow import _second_user, new_job

MISSING, EXISTS = "20-0990", "15-1234"


def _levels(row):
    return sorted({c["level"] for c in row["checks"]} - {"info"})


def _draft(api, add_uploaded, files, handling="linkorcreate"):
    job = new_job(api)
    for row in add_uploaded(job, files):
        api.patch(f"/api/jobs/{job}/rows/{row['n']}", json={"handling": handling})
    return job


def test_a_document_that_needs_a_new_object_is_not_a_mistake_in_the_job(api, login, add_uploaded):
    login("limited")  # staff who can't create Objects
    job = _draft(api, add_uploaded, [f"{MISSING}_1.jpg", f"{EXISTS}_1.jpg"])
    r = api.post(f"/api/jobs/{job}/check").json()
    by = {x["file"]: x for x in r["rows"]}
    assert _levels(by[f"{MISSING}_1.jpg"]) == ["creator"]
    text = next(c["text"] for c in by[f"{MISSING}_1.jpg"]["checks"] if c["level"] == "creator")
    assert text.startswith(f"No object {MISSING} in CollectionSpace, so this document needs a new Object, and your account can't")
    assert "creator" not in _levels(by[f"{EXISTS}_1.jpg"])
    assert r["counts"] == {"block": 0, "warn": 1, "creator": 1, "newObjects": 1}
    # "Create new object + link" can still be chosen, to prepare the document for a colleague
    row = api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "create"}).json()["row"]
    assert _levels(row) == ["creator"]


def test_someone_who_can_create_objects_sees_which_drafts_wait_for_them(api, login, add_uploaded, services):
    login("limited")
    job = _draft(api, add_uploaded, [f"{MISSING}_1.jpg"])
    api.post(f"/api/jobs/{job}/close")
    admin = _second_user(services, "admin")
    counts = admin.post(f"/api/jobs/{job}/check").json()["counts"]
    assert counts["creator"] == 0 and counts["newObjects"] == 1  # nothing in their way; one Object will be created


def test_a_job_is_submitted_whole_by_someone_who_can_create_its_objects(api, login, add_uploaded, worker, services):
    """A user who can't create Objects can't submit a job with documents that need a new one, and there is no
    way to submit only the rest: the draft waits for a colleague who can."""
    login("limited")
    job = _draft(api, add_uploaded, [f"{MISSING}_1.jpg", f"{EXISTS}_1.jpg", "1-2345_1.jpg"])
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "creator" and r.json()["detail"]["rows"] == [1]
    assert "this document needs a new Object. Leave the draft for a colleague who can create Objects" in r.json()["detail"]["message"]
    assert api.post(f"/api/jobs/{job}/schedule", json={"withoutCreator": True}).status_code == 409  # no such option
    data = api.get(f"/api/jobs/{job}").json()
    assert data["job"]["status"] == "Draft" and all(x["include"] for x in data["rows"])  # nothing was changed
    assert services.storage.get_credential(job) is None
    api.post(f"/api/jobs/{job}/close")

    # a colleague who can create Objects submits all of it
    admin = _second_user(services, "admin")
    assert admin.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    assert admin.get(f"/api/jobs/{job}").json()["job"]["status"] == "Completed"
    assert any(o["objectNumber"] == MISSING for o in services_objects())


def services_objects():
    from fakecspace.app import store
    return list(store.objects.values())


def test_taking_the_documents_out_or_changing_their_handling_lets_the_rest_go(api, login, add_uploaded):
    login("limited")
    job = _draft(api, add_uploaded, [f"{MISSING}_1.jpg", f"{EXISTS}_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 409
    assert api.delete(f"/api/jobs/{job}/rows/1").status_code == 200
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200


def test_a_document_that_needs_fixing_still_comes_first(api, login, add_uploaded):
    login("limited")
    job = _draft(api, add_uploaded, [f"{MISSING}_1.jpg", f"{EXISTS}_1.jpg"])
    api.patch(f"/api/jobs/{job}/rows/2", json={"date": "sometime last spring"})
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409 and "need fixing first" in r.json()["detail"]["message"]


def test_an_intern_is_not_told_about_their_own_permissions(services, add_uploaded):
    services.settings.reader_user, services.settings.reader_password = "bmureader", "bmureader"
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Intern's"}).json()["id"]
    add_uploaded(job, [f"{EXISTS}_1.jpg", f"{MISSING}_1.jpg", f"{MISSING}_2.jpg"], api=intern)
    intern.patch(f"/api/jobs/{job}/rows/3", json={"handling": "linkorcreate"})
    intern.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Interns' batch"})
    r = intern.post(f"/api/jobs/{job}/check").json()
    rows = {x["n"]: x for x in r["rows"]}
    assert _levels(rows[1]) in ([], ["warn"])  # found: nothing about Media, relations or groups
    assert not any("Your account" in c["text"] or "your account" in c["text"] for x in rows.values() for c in x["checks"])
    assert "block" in _levels(rows[2]) and any(f"No object {MISSING}" in c["text"] for c in rows[2]["checks"])  # a real problem
    text = next(c["text"] for c in rows[3]["checks"] if c["level"] == "creator")
    assert text.endswith("The staff member who submits the job must be able to create Objects.")
    assert r["counts"]["creator"] == 1 and r["counts"]["block"] == 1


def test_the_worker_still_checks_the_groups_permission_itself():
    from bmu.rows import permission_checks
    from bmu.tenant import load_tenant
    t = load_tenant("pahma")
    row = {"handling": "link", "group": True}
    perms = {"mediaUpdate": True, "readObjects": True, "relations": True, "objects": True, "groups": False}
    assert permission_checks(t, row, perms, group_on=True) == []
    assert "can't create groups" in permission_checks(t, row, perms, group_on=True, run=True)[0]["text"]
