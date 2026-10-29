"""A create whose answer was lost, and a worker that was stopped (design: Job execution).

CollectionSpace may save a record and still answer with a 5xx, or not answer in time. The rerun must find that
record instead of creating a second one. A worker whose run the heartbeat check stopped must write nothing more, and
SIGTERM ends a run at once, deleting its sign-in.
"""
from bmu.storage import now


def new_job(api, name="Lost answers"):
    return api.post("/api/jobs", json={"name": name}).json()["id"]


def reschedule(api, job):
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 200, r.text


def test_a_media_record_saved_without_its_answer_is_used_by_the_rerun(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_a.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "mediaonly"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["media_lost"] = 504
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    row = j["rows"][0]
    assert row["result"]["steps"]["media"]["s"] == "failed" and row["result"]["steps"]["media"]["maybeSent"]
    saved = [c for c, m in fake.media.items() if m.get("title") == "20-0501_a.jpg"]
    assert len(saved) == 1
    # the record may exist in CollectionSpace, so the document can't be deleted
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    assert api.delete(f"/api/jobs/{job}/rows/1").status_code == 409
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    steps = j["rows"][0]["result"]["steps"]
    assert j["job"]["status"] == "Completed", j["job"]
    assert steps["media"]["csid"] == saved[0] and steps["media"]["recovered"]
    assert len([m for m in fake.media.values() if m.get("title") == "20-0501_a.jpg"]) == 1
    assert not j["rows"][0]["result"].get("notices")  # the record it adopted isn't reported as a duplicate


def test_two_candidates_fail_the_document_without_creating_a_third(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_a.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "mediaonly"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["media_lost"] = 504
    worker.tick()
    idnum = api.get(f"/api/jobs/{job}").json()["rows"][0]["idnum"]
    fake.media["someone-else"] = {"identificationNumber": idnum, "title": "20-0501_a.jpg", "deleted": False}
    reschedule(api, job)
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    media = j["rows"][0]["result"]["steps"]["media"]
    assert media["s"] == "failed" and media["code"] == "create_uncertain" and media["maybeSent"]
    assert len([m for m in fake.media.values() if m.get("title") == "20-0501_a.jpg"]) == 2


def test_an_upload_saved_without_its_answer_is_not_sent_again(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_b.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "mediaonly"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["media_blob_lost"] = 504
    worker.tick()
    assert len(fake.blobs) == 1
    reschedule(api, job)
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    upload = j["rows"][0]["result"]["steps"]["upload"]
    assert j["job"]["status"] == "Completed"
    assert len(fake.blobs) == 1 and upload["csid"] in fake.blobs and upload["recovered"]


def test_an_object_saved_without_its_answer_is_used_not_reported_as_existing(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_c.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "create"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["collectionobjects_lost"] = 504
    worker.tick()
    made = [c for c, o in fake.objects.items() if o["objectNumber"] == "20-0501"]
    assert len(made) == 1
    reschedule(api, job)
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    st = j["rows"][0]["result"]["steps"]["createObject"]
    assert j["job"]["status"] == "Completed", j["rows"][0]["result"]
    assert st["csid"] == made[0] and st["recovered"] and not st.get("found")
    assert len([o for o in fake.objects.values() if o["objectNumber"] == "20-0501"]) == 1
    assert any(e["csid"] == made[0] for e in j["created"].get("csids", [])) or j["created"]["objects"] == 1


def test_a_group_saved_without_its_answer_is_used_and_needs_only_a_reschedule(api, login, add_uploaded, worker, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Lost group"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["groups_lost"] = 502
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "NeedsAttention" and j["job"]["code"] == "group_server_error"
    assert j["rows"][0]["result"]["error"]["code"] == "group_server_error"
    assert len(fake.groups) == 1
    reschedule(api, job)
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed", j["job"]
    assert len(fake.groups) == 1 and j["job"]["groupStep"]["csid"] in fake.groups and j["job"]["groupStep"]["recovered"]


def test_a_stopped_worker_writes_nothing_after_the_heartbeat_check_ended_its_run(api, login, add_uploaded, worker, services,
                                                                                 fake, monkeypatch):
    """Fencing: the sweep ends the run as worker_stopped and the job is submitted again while the first worker is
    still on its first document. That worker stops before its next step, leaves the new sign-in alone, and doesn't
    finish the job a second time."""
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_d.jpg", "20-0501_e.jpg"])
    for n in (1, 2):
        api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    real = worker.run_row
    calls = []

    def run_row(client, job_id, row, run_no, created):
        err = real(client, job_id, row, run_no, created)
        if not calls:  # after the first document: the heartbeat check stops the run, and staff reschedule it
            calls.append(row["n"])
            services.storage.update_job(job_id, {"heartbeatAt": now() - 3600})
            worker.sweep_stopped_jobs()
            assert services.storage.get_job(job_id)["status"] == "Failed"
            reschedule(api, job_id)
        return err
    monkeypatch.setattr(worker, "run_row", run_row)
    worker.tick()
    j = services.storage.get_job(job)
    assert j["status"] == "Queued" and services.storage.get_credential(job) is not None
    assert len([m for m in fake.media.values() if (m.get("title") or "").startswith("20-0501")]) == 1
    monkeypatch.setattr(worker, "run_row", real)
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed" and j["job"]["run"] == 2
    assert len([m for m in fake.media.values() if (m.get("title") or "").startswith("20-0501")]) == 2


def test_sigterm_ends_the_run_at_once_and_deletes_the_sign_in(api, login, add_uploaded, worker, services, monkeypatch):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_f.jpg", "20-0501_g.jpg"])
    for n in (1, 2):
        api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    real = worker.run_row

    def run_row(*a):
        err = real(*a)
        worker.stop()  # SIGTERM arrives during the first document
        return err
    monkeypatch.setattr(worker, "run_row", run_row)
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()["job"]
    assert j["status"] == "Failed" and j["code"] == "worker_stopped" and "SIGTERM" in j["codeDetail"]
    assert services.storage.get_credential(job) is None
    assert worker.stopping.is_set()
