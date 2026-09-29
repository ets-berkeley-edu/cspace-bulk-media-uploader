"""Finished jobs: failure codes, run history, Fix and reschedule, reverting an abandoned fix, deleting jobs.

Design: Finished jobs and error messages; Fixing a job after a run; State rules; Deleting a job.
"""
from bmu.cspace import CSpaceError
from bmu.failures import catalog, classify, needs_fix
from bmu.storage import now


def new_job(api, name="Finished test"):
    return api.post("/api/jobs", json={"name": name}).json()["id"]


def run_once(api, job, worker):
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    assert worker.tick() is True
    return api.get(f"/api/jobs/{job}").json()


def by_file(j):
    return {r["file"]: r for r in j["rows"]}


# ---- the failure catalog ------------------------------------------------------------------------
def test_catalog_has_every_code_the_worker_records():
    codes = {"upload_too_large", "file_type_rejected", "file_missing", "media_rejected", "object_gone", "object_ambiguous",
             "object_rejected", "no_permission", "server_error", "duplicate_at_run", "group_failed", "auth",
             "account_inactive", "unavailable", "worker_stopped", "cancelled", "unknown"}
    assert codes <= set(catalog())
    assert needs_fix("upload_too_large") and needs_fix("object_gone") and not needs_fix("auth") and not needs_fix("cancelled")


def test_classify_maps_http_failures_to_catalog_codes():
    def e(status, code="unknown"):
        return CSpaceError(code, f"X returned {status}", status)
    assert classify("upload", e(413))[0] == "upload_too_large"
    assert classify("upload", e(415))[0] == "file_type_rejected"
    assert classify("media", e(400))[0] == "media_rejected"
    assert classify("createObject", e(400))[0] == "object_rejected"
    assert classify("relMediaObject", e(403, "forbidden"))[0] == "no_permission"
    assert classify("media", e(401, "auth"))[0] == "auth"
    assert classify("media", e(409))[0] == "account_inactive"
    assert classify("upload", e(503, "server"))[0] == "server_error"
    assert classify("upload", CSpaceError("unavailable", "timeout"))[0] == "server_error"
    code, detail = classify("relMediaObject", e(418))
    assert code == "unknown" and "418" in detail and "relMediaObject" in detail


def test_the_api_serves_the_catalog(api, login):
    login()
    f = api.get("/api/failures").json()["failures"]
    assert f["object_gone"]["title"] == "Object not found when the job ran" and f["object_gone"]["needs_fix"] is True


# ---- failures on demand in the simulated CollectionSpace ---------------------------------------
def test_failure_rules_affect_only_job_runs_by_default(api, login, add_uploaded, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fail_on("objectSearch", effect="none", match="15-1234", count=0)
    # the editor's check still finds the object: the rule is for the worker only
    row = api.post(f"/api/jobs/{job}/check", json={"rows": [1]}).json()["rows"][0]
    assert not [c for c in row["checks"] if c["level"] == "block"]


# ---- a file rejected as too large: fix by replacing it -----------------------------------------
def test_upload_too_large_then_replace_file_and_rerun(api, login, add_uploaded, worker, services, fake, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "1-2345.jpg"])
    fail_on("upload", status=413, match="1-2345")
    j = run_once(api, job, worker)
    assert j["job"]["status"] == "NeedsAttention" and j["job"]["code"] == ""
    assert j["job"]["counts"] == {"done": 1, "partial": 1, "failed": 0, "notStarted": 0, "disabled": 0}
    row = by_file(j)["1-2345.jpg"]
    assert row["result"]["state"] == "Partial"
    assert row["result"]["error"]["code"] == "upload_too_large" and "413" in row["result"]["error"]["detail"]
    assert [r["outcome"] for r in j["runs"]] == ["NeedsAttention"] and j["runs"][0]["counts"]["partial"] == 1
    assert j["created"]["media"] == 2 and j["created"]["files"] == 1 and j["created"]["unfinished"] == 1
    old_key = row["s3Key"]

    # Only drafts can be scheduled: the job goes to Drafts first
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 409
    fixed = api.post(f"/api/jobs/{job}/fix").json()
    assert fixed["status"] == "Draft" and fixed["editingByYou"] and fixed["fixFrom"] == {"status": "NeedsAttention", "code": "", "run": 1}
    # the Media record exists: its fields can't change, and it can't be deleted
    n = row["n"]
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"description": "new"})
    assert r.status_code == 422 and "already exists in CollectionSpace" in r.json()["detail"]
    assert api.delete(f"/api/jobs/{job}/rows/{n}").status_code == 409
    chk = api.post(f"/api/jobs/{job}/check").json()["rows"]
    checks = next(x for x in chk if x["n"] == n)["checks"]
    assert any("The rerun will only upload the file" in c["text"] for c in checks)
    assert any(c["level"] == "warn" and "rejected this file" in c["text"] for c in checks)

    # a replacement file: the browser uploads it like any other
    r = api.post(f"/api/jobs/{job}/rows/{n}/replace-file", json={"name": "1-2345_small.jpg", "size": 5, "type": "image/jpeg"})
    assert r.status_code == 200, r.text
    new = r.json()["row"]
    assert new["upload"]["s"] == "pending" and new["s3Key"] != old_key and new["supersededKey"] == old_key
    services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=new["s3Key"], Body=b"small")
    after = api.post(f"/api/jobs/{job}/rows/{n}/uploaded").json()["row"]
    assert after["upload"]["s"] == "done" and not [c for c in after["checks"] if c["level"] != "info"]

    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    row = by_file(j)["1-2345_small.jpg"]
    assert j["job"]["status"] == "Completed" and j["job"]["run"] == 2 and j["job"]["expiresAt"] > now() + 29 * 86400
    assert row["result"]["state"] == "Done" and row["result"]["steps"]["media"]["run"] == 1 and row["result"]["steps"]["upload"]["run"] == 2
    blob = fake.blobs[row["result"]["steps"]["upload"]["csid"]]
    assert blob["name"] == "1-2345_small.jpg" and blob["size"] == 5
    assert services.storage.head_object(old_key) is None  # the rejected file was removed when the rerun started
    assert [r["outcome"] for r in j["runs"]] == ["NeedsAttention", "Completed"]
    assert services.storage.fix_originals(job) == []


# ---- object not found at run time: correct the number or stop linking --------------------------
def test_object_gone_then_stop_linking(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fail_on("objectSearch", effect="none", match="15-1234")
    j = run_once(api, job, worker)
    row = j["rows"][0]
    assert row["result"]["state"] == "Partial" and row["result"]["error"]["code"] == "object_gone"
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    # a wrong correction blocks; the object number may change because the object step failed on it
    r = api.patch(f"/api/jobs/{job}/rows/1", json={"obj": "20-0501"}).json()["row"]
    assert any(c["level"] == "block" and "No object 20-0501" in c["text"] for c in r["checks"])
    assert r["idnum"] == "15-1234"  # the Media record's identification number never follows
    r = api.patch(f"/api/jobs/{job}/rows/1", json={"skipLink": True}).json()["row"]
    assert not [c for c in r["checks"] if c["level"] == "block"]
    assert "stopped linking" in r["checks"][0]["text"]
    # once stopped, the object number is no longer what the rerun needs
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"obj": "12-5678"}).status_code == 422
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    row = api.get(f"/api/jobs/{job}").json()["rows"][0]
    st = row["result"]["steps"]
    assert row["result"]["state"] == "Done"
    assert st["findObject"]["s"] == "not needed" and st["relMediaObject"]["s"] == "not needed"
    assert len(fake.relations) == 0


def test_object_ambiguous_at_run_and_correcting_the_number(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fail_on("objectSearch", effect="many", match="15-1234")
    row = run_once(api, job, worker)["rows"][0]
    assert row["result"]["error"]["code"] == "object_ambiguous"
    api.post(f"/api/jobs/{job}/fix")
    r = api.patch(f"/api/jobs/{job}/rows/1", json={"obj": "12-5678"}).json()["row"]
    assert not [c for c in r["checks"] if c["level"] == "block"]
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    row = api.get(f"/api/jobs/{job}").json()["rows"][0]
    obj = row["result"]["steps"]["findObject"]["csid"]
    assert row["result"]["state"] == "Done" and fake.objects[obj]["objectNumber"] == "12-5678"


def test_no_permission_for_relations_offers_stop_linking(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fail_on("relation", status=403, count=0)
    row = run_once(api, job, worker)["rows"][0]
    assert row["result"]["error"]["code"] == "no_permission" and row["result"]["state"] == "Partial"
    api.post(f"/api/jobs/{job}/fix")
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"obj": "12-5678"}).status_code == 422  # the object was found
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"skipLink": True}).status_code == 200


def test_media_rejected_row_is_editable_except_its_object(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0777.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "create"})
    fail_on("media", status=400)
    row = run_once(api, job, worker)["rows"][0]
    assert row["result"]["state"] == "Failed" and row["result"]["error"]["code"] == "media_rejected"
    assert row["result"]["steps"]["createObject"]["s"] == "done"
    api.post(f"/api/jobs/{job}/fix")
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"description": "fixed"}).status_code == 200
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"obj": "20-0778"}).status_code == 422
    # it created an Object, so it can't be deleted; the object isn't looked up again (it would now "already exist")
    assert api.delete(f"/api/jobs/{job}/rows/1").status_code == 409
    checks = api.post(f"/api/jobs/{job}/check").json()["rows"][0]["checks"]
    assert not [c for c in checks if c["level"] == "block"], checks
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed" and j["created"]["objects"] == 1


def test_object_created_since_scheduling_is_found_not_duplicated(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0901.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "create"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.objects["late"] = {"objectNumber": "20-0901", "deleted": False}
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    st = j["rows"][0]["result"]["steps"]["createObject"]
    assert st["csid"] == "late" and st["found"] is True and j["created"]["objects"] == 0


# ---- job-level failures -------------------------------------------------------------------------
def test_sign_in_failure_fails_the_job_and_reschedule_continues(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    fail_on("media", status=401)
    j = run_once(api, job, worker)
    assert j["job"]["status"] == "Failed" and j["job"]["code"] == "auth"
    assert j["runs"][0]["code"] == "auth" and j["job"]["counts"]["notStarted"] == 1
    fixed = api.post(f"/api/jobs/{job}/fix").json()
    assert fixed["fixFrom"]["code"] == "auth"
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    assert api.get(f"/api/jobs/{job}").json()["job"]["status"] == "Completed"


def test_five_server_errors_in_a_row_stop_the_job(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, [f"15-1234_{i}.jpg" for i in range(1, 7)])
    fail_on("media", status=503, count=0)
    j = run_once(api, job, worker)
    assert j["job"]["status"] == "Failed" and j["job"]["code"] == "unavailable"
    assert j["job"]["counts"]["failed"] == 5 and j["job"]["counts"]["notStarted"] == 1


def test_a_running_job_whose_worker_stopped_fails_as_worker_stopped(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    # as if a worker had claimed it, started the row and then died
    row = services.storage.get_row(job, 1)
    row["result"] = {"state": "In progress", "steps": {"media": {"s": "done", "csid": "m1", "run": 1}}, "run": 1}
    services.storage.put_row(job, row, guard=False)
    services.storage.put_run(job, {"run": 1, "startedAt": now() - 900, "outcome": "Running"})
    services.storage.update_job(job, {"status": "Running", "run": 1, "startedAt": now() - 900, "heartbeatAt": now() - 600})
    assert worker.tick() is False  # a Running job is never resumed; the periodic check stops it instead
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Failed" and j["job"]["code"] == "worker_stopped"
    assert j["rows"][0]["result"]["state"] == "Partial"
    assert j["runs"][0]["outcome"] == "Failed" and j["runs"][0]["code"] == "worker_stopped"
    assert services.storage.get_credential(job) is None
    # the row the worker was on can't be deleted: a create may have reached CollectionSpace
    api.post(f"/api/jobs/{job}/fix")
    assert api.delete(f"/api/jobs/{job}/rows/1").status_code == 409


def test_cancelled_run_is_recorded_in_the_run_history(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    original = worker.run_row

    def cancel_after_first(client, job_id, row, run_no, created):
        services.storage.update_job(job_id, {"cancelRequested": {"by": "admin", "at": now()}})
        return original(client, job_id, row, run_no, created)
    worker.run_row = cancel_after_first
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["code"] == "cancelled" and j["runs"][0]["cancelledBy"] == "admin"
    assert j["job"]["counts"] == {"done": 1, "partial": 0, "failed": 0, "notStarted": 1, "disabled": 0}


def test_duplicate_id_created_after_scheduling_is_a_notice(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["12-5678_1.jpg"])
    fail_on("mediaSearch", effect="many")
    row = run_once(api, job, worker)["rows"][0]
    assert row["result"]["state"] == "Done"
    assert row["result"]["notices"][0]["code"] == "duplicate_at_run"


# ---- the run history lists what was disabled or deleted before each run ------------------------
def test_run_history_lists_documents_disabled_or_deleted_before_the_run(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg", "1-2345.jpg"])
    fail_on("media", status=400, match="12-5678")
    fail_on("media", status=500, match="1-2345")
    run_once(api, job, worker)
    api.post(f"/api/jobs/{job}/fix")
    r = api.patch(f"/api/jobs/{job}/rows/2", json={"include": False}).json()["row"]
    assert r["disabledBy"] == "admin" and r["disabledAt"]
    assert api.post(f"/api/jobs/{job}/save").json()["status"] == "Draft"  # document 3 still has work left
    # deleting the last unfinished document (a Failed one that created nothing) leaves every document done or
    # disabled: the job is Completed
    r = api.delete(f"/api/jobs/{job}/rows/3")
    assert r.status_code == 200 and r.json()["jobStatus"] == "Completed"
    done = api.get(f"/api/jobs/{job}").json()["job"]
    assert done["status"] == "Completed" and not done.get("editingBy") and done["expiresAt"] > now() + 29 * 86400
    assert done["deletedRows"][0]["file"] == "1-2345.jpg"


def test_rerun_records_disabled_documents(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg", "1-2345.jpg"])
    fail_on("media", status=400, match="12-5678")
    fail_on("media", status=500, match="1-2345")
    run_once(api, job, worker)
    api.post(f"/api/jobs/{job}/fix")
    api.patch(f"/api/jobs/{job}/rows/2", json={"include": False})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed" and j["job"]["counts"]["disabled"] == 1
    run2 = j["runs"][1]
    assert run2["scheduledBy"] == "admin" and [d["file"] for d in run2["disabledBefore"]] == ["12-5678_1.jpg"]


# ---- an abandoned fix is reverted -------------------------------------------------------------
def test_an_abandoned_fix_is_reverted(api, login, add_uploaded, worker, services, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    fail_on("media", status=400, match="12-5678")
    fail_on("upload", status=413, match="15-1234")
    run_once(api, job, worker)
    api.post(f"/api/jobs/{job}/fix")
    api.patch(f"/api/jobs/{job}/rows/2", json={"description": "changed while fixing"})
    r = api.post(f"/api/jobs/{job}/rows/1/replace-file", json={"name": "15-1234_1s.jpg", "size": 3, "type": "image/jpeg"}).json()
    new_key, old_key = r["row"]["s3Key"], r["row"]["supersededKey"]
    services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=new_key, Body=b"abc")
    add_uploaded(job, ["1-2345.jpg"])
    assert len(api.get(f"/api/jobs/{job}").json()["rows"]) == 3
    services.storage.update_job(job, {"expiresAt": now() - 1})
    assert worker.sweep_expired_drafts() == [job]
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "NeedsAttention" and j["job"]["fixFrom"] is None and not j["job"].get("editingBy")
    rows = by_file(j)
    assert set(rows) == {"15-1234_1.jpg", "12-5678_1.jpg"}
    assert rows["12-5678_1.jpg"]["description"] == "" and rows["15-1234_1.jpg"]["s3Key"] == old_key
    assert services.storage.head_object(new_key) is None and services.storage.head_object(old_key) is not None
    assert len(j["runs"]) == 1
    assert any(a["type"] == "Fix reverted" for a in services.storage.list_audit("pahma"))


def test_drafts_that_never_ran_are_still_deleted_on_expiry(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    services.storage.update_job(job, {"expiresAt": now() - 1})
    assert worker.sweep_expired_drafts() == [job]
    assert services.storage.get_job(job) is None


def test_completed_jobs_are_removed_after_30_days(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert run_once(api, job, worker)["job"]["status"] == "Completed"
    assert worker.sweep_completed() == []
    services.storage.update_job(job, {"expiresAt": now() - 1})
    assert worker.sweep_completed() == [job]
    assert services.storage.get_job(job) is None
    assert any(a["type"] == "Job expired" for a in services.storage.list_audit("pahma"))


# ---- deleting a job that created records ------------------------------------------------------
def test_a_job_that_created_records_can_be_deleted_and_the_audit_keeps_its_csids(api, login, add_uploaded, worker, services, fake, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    fail_on("upload", status=413, match="12-5678")
    j = run_once(api, job, worker)
    assert j["job"]["status"] == "NeedsAttention"
    assert api.delete(f"/api/jobs/{job}").status_code == 200
    assert services.storage.get_job(job) is None and services.storage.get_runs(job) == []
    entry = next(a for a in services.storage.list_audit("pahma") if a["type"] == "Job deleted")
    assert "2 Media records (1 with files)" in entry["detail"] and "1 unfinished" in entry["detail"]
    assert {c["step"] for c in entry["csids"]} == {"media", "upload", "relMediaObject", "relObjectMedia"}
    assert len(fake.media) == 3  # nothing in CollectionSpace was touched


def test_running_and_completed_jobs_cannot_be_deleted(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    run_once(api, job, worker)
    assert api.delete(f"/api/jobs/{job}").status_code == 409  # Completed: removed on its own
    services.storage.update_job(job, {"status": "Running"})
    assert api.delete(f"/api/jobs/{job}").status_code == 409


def test_only_one_person_fixes_a_job(api, login, add_uploaded, worker, services, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["12-5678_1.jpg"])
    fail_on("media", status=400)
    run_once(api, job, worker)
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    r = api.post(f"/api/jobs/{job}/fix")
    assert r.status_code == 409 and "already fixing" in r.json()["detail"]
