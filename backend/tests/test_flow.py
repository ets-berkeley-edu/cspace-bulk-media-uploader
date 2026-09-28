"""End-to-end run path against the simulated CollectionSpace and mocked AWS."""


def new_job(api, name="Test job"):
    r = api.post("/api/jobs", json={"name": name})
    assert r.status_code == 200
    return r.json()["id"]


def test_requires_sign_in_and_csrf_header(api):
    assert api.get("/api/me").status_code == 401
    r = api.post("/api/login", json={"username": "admin", "password": "admin"}, headers={"X-BMU": ""})
    assert r.status_code == 403


def test_bad_password_is_rejected(api):
    r = api.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_session_does_not_store_plain_password(api, login, services):
    login()
    items = services.storage.sessions.scan()["Items"]
    assert len(items) == 1 and "admin" != items[0]["password"] and "admin" not in items[0]["password"]


def test_full_run_path(api, login, add_uploaded, worker, services, fake):
    me = login()
    assert me["perms"]["media"] and me["tenant"]["publish"]["header"] == "Restricted"
    job = new_job(api)
    add_uploaded(job, ["15-1234_a.jpg", "20-0501.jpg", "9-9999.jpg", "15-1240_1.jpg"])

    chk = api.post(f"/api/jobs/{job}/check").json()
    by = {r["file"]: r for r in chk["rows"]}
    assert any("No object 20-0501" in c["text"] for c in by["20-0501.jpg"]["checks"])
    assert any("matches 2 objects" in c["text"] for c in by["9-9999.jpg"]["checks"])
    assert any(c["level"] == "warn" and "already exists" in c["text"] for c in by["15-1234_a.jpg"]["checks"])
    assert chk["counts"]["block"] == 2

    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409 and len(r.json()["detail"]["rows"]) == 2

    # fix: create the missing object; leave the ambiguous one out
    api.patch(f"/api/jobs/{job}/rows/{by['20-0501.jpg']['n']}", json={"handling": "create"})
    api.patch(f"/api/jobs/{job}/rows/{by['9-9999.jpg']['n']}", json={"include": False})
    ref = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'"
    api.patch(f"/api/jobs/{job}/rows/{by['15-1240_1.jpg']['n']}", json={"restricted": True, "creator": ref})

    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "Queued"
    assert services.storage.get_credential(job) is not None
    # queued jobs can't be edited
    assert api.patch(f"/api/jobs/{job}/rows/1", json={"description": "x"}).status_code == 409

    assert worker.tick() is True
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed", j
    assert services.storage.get_credential(job) is None  # password deleted after the run
    rows = {r["file"]: r for r in j["rows"]}
    for f in ("15-1234_a.jpg", "20-0501.jpg", "15-1240_1.jpg"):
        assert rows[f]["result"]["state"] == "Done", rows[f]
    assert rows["9-9999.jpg"]["result"] is None
    assert len(fake.blobs) == 3 and len(fake.relations) == 6
    created_obj = [c for c, o in fake.objects.items() if o["objectNumber"] == "20-0501"]
    assert len(created_obj) == 1
    media = fake.media[rows["15-1240_1.jpg"]["result"]["steps"]["media"]["csid"]]
    assert "<approvedForWeb>false</approvedForWeb>" in media["xml"] and ref in media["xml"]
    # Media first, then PUT media/{csid}/blob: the Blob belongs to the Media record and blobCsid was set by CollectionSpace
    assert "blobCsid" not in media["xml"]
    steps = rows["15-1240_1.jpg"]["result"]["steps"]
    assert media["blobCsid"] == steps["upload"]["csid"] and fake.blobs[steps["upload"]["csid"]]["media"] == steps["media"]["csid"]
    assert list(steps) == ["media", "findObject", "upload", "relMediaObject", "relObjectMedia"]
    # staged files are deleted once in CollectionSpace
    assert services.storage.head_object(rows["15-1234_a.jpg"]["s3Key"]) is None
    audit = services.storage.list_audit("pahma")
    assert any(a["type"] == "Run" and "Completed" in a["detail"] and a["csids"] for a in audit)


def test_partial_failure_and_rerun_skips_finished_steps(api, login, add_uploaded, worker, services, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_b.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["relations"] = 503
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    row = j["rows"][0]
    assert j["job"]["status"] == "NeedsAttention"
    assert row["result"]["state"] == "Partial" and row["result"]["error"]["code"] == "server"
    media_csid = row["result"]["steps"]["media"]["csid"]
    assert services.storage.get_credential(job) is None
    # a Partial row is locked: it can't be edited or deleted
    assert api.delete(f"/api/jobs/{job}/rows/{row['n']}").status_code == 409
    # Reschedule: the rerun reuses the Media record and only adds the relations
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Completed" and j["job"]["run"] == 2
    assert j["rows"][0]["result"]["steps"]["media"]["csid"] == media_csid
    assert len(fake.media) == 2 and len(fake.blobs) == 1 and len(fake.relations) == 2  # 1 seeded media + 1


def test_rerun_finds_relation_whose_response_was_lost(api, login, add_uploaded, worker, fake):
    """CollectionSpace saved the relation but the BMU never got the response: the rerun must find it, not duplicate it."""
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_d.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["relations_lost"] = 504
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "NeedsAttention"
    assert j["rows"][0]["result"]["steps"]["relMediaObject"]["s"] == "failed"
    assert j["rows"][0]["result"]["steps"]["relObjectMedia"]["s"] == "done"
    assert len(fake.relations) == 2  # both saved on the server, one despite the error
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    steps = j["rows"][0]["result"]["steps"]
    assert j["job"]["status"] == "Completed"
    assert steps["relMediaObject"]["csid"] in fake.relations
    assert len(fake.relations) == 2  # one each way, no duplicate


def test_limited_user_cannot_create_objects(api, login, add_uploaded):
    login("limited")
    job = new_job(api)
    rows = add_uploaded(job, ["30-0001.jpg"])
    api.patch(f"/api/jobs/{job}/rows/{rows[0]['n']}", json={"handling": "create"})
    chk = api.post(f"/api/jobs/{job}/check").json()
    assert any("can't create Object records" in c["text"] for c in chk["rows"][0]["checks"])


def test_wrong_credentials_stop_job_and_delete_password(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_c.jpg", "12-5678_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    # simulate the password changing in CollectionSpace after scheduling
    cred = services.storage.get_credential(job)
    services.storage.put_credential(job, "admin", services.crypto.encrypt("job", "changed", {"user": "admin", "job": job}),
                                    cred["expires"])
    worker.tick()
    j = api.get(f"/api/jobs/{job}").json()
    assert j["job"]["status"] == "Failed" and j["job"]["code"] == "auth"
    assert services.storage.get_credential(job) is None


def test_expired_sign_in_returns_job_to_drafts(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_d.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    services.storage.delete_credential(job)  # as if the 72-hour limit had passed
    worker.tick()
    assert api.get(f"/api/jobs/{job}").json()["job"]["status"] == "Draft"


def test_one_job_per_tenant(api, login, add_uploaded, worker, services):
    login()
    assert services.storage.acquire_lock("pahma", "someone-else", 60)
    job = new_job(api)
    add_uploaded(job, ["15-1234_e.jpg"])
    api.post(f"/api/jobs/{job}/schedule")
    assert worker.tick() is False  # another worker holds the tenant's run lock
    services.storage.release_lock("pahma", "someone-else")
    assert worker.tick() is True


def test_authority_autocomplete_returns_refnames(api, login):
    login()
    assert api.get("/api/authorities", params={"field": "creator", "q": "fr"}).json()["terms"] == []
    terms = api.get("/api/authorities", params={"field": "creator", "q": "freu"}).json()["terms"]
    assert terms and terms[0]["displayName"] == "Leslie Freund" and terms[0]["refName"].startswith("urn:cspace:")
    orgs = api.get("/api/authorities", params={"field": "rightsHolder", "q": "hearst"}).json()["terms"]
    assert orgs[0]["source"] == "organization"


def test_upload_size_mismatch_marks_failed(api, login, services):
    login()
    job = new_job(api)
    r = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_z.jpg", "size": 100, "type": "image/jpeg"}]})
    row = r.json()["rows"][0]
    services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=row["s3Key"], Body=b"short")
    assert api.post(f"/api/jobs/{job}/rows/{row['n']}/uploaded").json()["upload"]["s"] == "failed"


def test_failed_upload_still_relates_and_rerun_reuses_media(api, login, add_uploaded, worker, services, fake):
    """Design: "Upload fails: Relations are still created"; an upload retry targets the existing Media CSID."""
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_f.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["media_blob"] = 500
    worker.tick()
    row = api.get(f"/api/jobs/{job}").json()["rows"][0]
    st = row["result"]["steps"]
    assert row["result"]["state"] == "Partial"
    assert st["upload"]["s"] == "failed" and st["relMediaObject"]["s"] == "done" and st["relObjectMedia"]["s"] == "done"
    media = st["media"]["csid"]
    assert fake.media[media]["blobCsid"] == "" and len(fake.relations) == 2
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    row = api.get(f"/api/jobs/{job}").json()["rows"][0]
    assert row["result"]["state"] == "Done" and row["result"]["steps"]["media"]["csid"] == media
    assert fake.media[media]["blobCsid"] == row["result"]["steps"]["upload"]["csid"]
    assert len(fake.relations) == 2  # not recreated


def test_object_not_found_still_uploads_and_skips_relations(api, login, add_uploaded, worker, services, fake):
    """Design: "Object not found: the file is still uploaded; Relations are skipped" (e.g. deleted after checks)."""
    login()
    job = new_job(api)
    rows = add_uploaded(job, ["15-1234_g.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    for o in fake.objects.values():  # the object disappears after scheduling
        if o["objectNumber"] == "15-1234":
            o["deleted"] = True
    worker.tick()
    st = api.get(f"/api/jobs/{job}").json()["rows"][0]["result"]
    assert st["state"] == "Partial" and st["error"]["code"] == "objnotfound"
    assert st["steps"]["upload"]["s"] == "done"
    assert st["steps"]["relMediaObject"] == {"s": "skipped", "after": "findObject"}
    assert len(fake.relations) == 0


def test_media_failure_skips_upload_and_relations(api, login, add_uploaded, worker, fake):
    """Design: "Media create fails: the upload and Relations are skipped" -> row Failed."""
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0777.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "create"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.fail_next["media"] = 500
    worker.tick()
    st = api.get(f"/api/jobs/{job}").json()["rows"][0]["result"]
    assert st["state"] == "Failed"
    assert st["steps"]["upload"] == {"s": "skipped", "after": "media"}
    assert st["steps"]["createObject"]["s"] == "done"  # the Object step doesn't depend on Media
    assert len(fake.blobs) == 0
