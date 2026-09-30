"""Deleting documents from a job in the editor: one at a time or the selected ones (design: Deleting a row).

Excluded documents can be deleted; documents that created something in CollectionSpace can't (use Exclude).
"""


def new_job(api, name="Delete test"):
    return api.post("/api/jobs", json={"name": name}).json()["id"]


def mark_created(services, job, n):
    """As if an earlier run had created this document's Media record."""
    row = services.storage.get_row(job, n)
    row["result"] = {"state": "Partial", "steps": {"media": {"s": "done", "csid": f"m{n}", "run": 1}}, "run": 1}
    services.storage.put_row(job, row, guard=False)


def test_an_excluded_document_can_be_deleted_one_at_a_time(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"include": False}).json()["row"]["include"] is False
    staged = services.storage.get_row(job, 1)["s3Key"]
    r = api.delete(f"/api/jobs/{job}/rows/1")
    assert r.status_code == 200 and r.json()["ok"] is True and "jobStatus" not in r.json()
    assert services.storage.get_row(job, 1) is None and services.storage.head_object(staged) is None
    assert [x["n"] for x in api.get(f"/api/jobs/{job}").json()["rows"]] == [2]


def test_delete_selected_deletes_what_it_may_and_skips_the_rest(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg", "1-2345.jpg", "3-1001_1.jpg"])
    api.patch(f"/api/jobs/{job}/rows/2", json={"include": False})
    mark_created(services, job, 3)
    staged = {n: services.storage.get_row(job, n)["s3Key"] for n in (1, 2, 3)}
    audits_before = len([a for a in services.storage.list_audit("pahma") if a["type"] == "Row deleted"])
    r = api.post(f"/api/jobs/{job}/rows/delete", json={"rows": [1, 2, 3, 99, 1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == [1, 2] and "jobStatus" not in body and isinstance(body["others"], list)
    assert [(x["n"], x["file"], x["code"]) for x in body["skipped"]] == [(3, "1-2345.jpg", "created"), (99, "", "missing")]
    assert "already created records" in body["skipped"][0]["reason"]
    assert [x["n"] for x in api.get(f"/api/jobs/{job}").json()["rows"]] == [3, 4]
    assert services.storage.head_object(staged[1]) is None and services.storage.head_object(staged[2]) is None
    assert services.storage.head_object(staged[3])  # the skipped one keeps its file
    entries = [a for a in services.storage.list_audit("pahma") if a["type"] == "Row deleted"]
    assert len(entries) - audits_before == 2
    assert {e["detail"].split(" (")[0] for e in entries} >= {"Deleted document 1", "Deleted document 2"}
    assert services.storage.get_job(job)["rowCount"] == 2
    assert not services.storage.get_job(job).get("deletedRows")  # never run: nothing for a next run to list


def test_deleting_every_document_deletes_the_job(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    api.patch(f"/api/jobs/{job}/rows/2", json={"include": False})
    r = api.post(f"/api/jobs/{job}/rows/delete", json={"rows": [1, 2]}).json()
    assert r == {"deleted": [1, 2], "skipped": [], "others": [], "jobStatus": "Deleted"}
    assert api.get(f"/api/jobs/{job}").status_code == 404
    assert len([a for a in services.storage.list_audit("pahma") if a["type"] == "Row deleted"]) == 2


def test_nothing_deletable_changes_nothing(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    mark_created(services, job, 1)
    r = api.post(f"/api/jobs/{job}/rows/delete", json={"rows": [1]}).json()
    assert r["deleted"] == [] and [x["code"] for x in r["skipped"]] == ["created"] and "jobStatus" not in r
    assert services.storage.get_row(job, 1) is not None
    assert not [a for a in services.storage.list_audit("pahma") if a["type"] == "Row deleted"]


def test_a_document_changed_meanwhile_is_skipped_not_the_whole_request(api, login, add_uploaded, services, monkeypatch):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg", "1-2345.jpg"])
    real = services.storage.delete_row_if_unchanged

    def changed_for_2(job_id, row, session):
        return False if row["n"] == 2 else real(job_id, row, session)
    monkeypatch.setattr(services.storage, "delete_row_if_unchanged", changed_for_2)
    r = api.post(f"/api/jobs/{job}/rows/delete", json={"rows": [1, 2]})
    assert r.status_code == 200
    assert r.json()["deleted"] == [1] and [(x["n"], x["code"]) for x in r.json()["skipped"]] == [(2, "changed")]
    assert services.storage.get_row(job, 2) is not None


def test_only_the_drafts_editor_can_delete_selected(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    services.storage.update_job(job, {"editingSession": "someone-else", "editingBy": "other"})
    r = api.post(f"/api/jobs/{job}/rows/delete", json={"rows": [1]})
    assert r.status_code == 409 and services.storage.get_row(job, 1) is not None
    assert api.post(f"/api/jobs/{job}/rows/delete", json={"rows": []}).status_code == 422


def test_a_job_that_has_run_lists_the_deleted_documents_once_and_completes(api, login, add_uploaded, worker, services, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg", "1-2345.jpg"])
    fail_on("media", status=400, match="12-5678")
    fail_on("media", status=500, match="1-2345")
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    api.post(f"/api/jobs/{job}/fix")
    r = api.post(f"/api/jobs/{job}/rows/delete", json={"rows": [1, 2, 3]})
    assert r.status_code == 200, r.text
    body = r.json()
    # document 1 was created in CollectionSpace: it stays, and with the others gone the job is Completed
    assert body["deleted"] == [2, 3] and [x["n"] for x in body["skipped"]] == [1] and body["jobStatus"] == "Completed"
    done = services.storage.get_job(job)
    assert done["status"] == "Completed"
    assert [d["file"] for d in done["deletedRows"]] == ["12-5678_1.jpg", "1-2345.jpg"]
    assert all(d["by"] == "admin" for d in done["deletedRows"])
    assert len([a for a in services.storage.list_audit("pahma") if a["type"] == "Row deleted"]) == 2
