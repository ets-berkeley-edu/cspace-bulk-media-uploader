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
    assert api.post(f"/api/jobs/{job}/rows/{row['n']}/uploaded").json()["row"]["upload"]["s"] == "failed"


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


# ---- checks while editing (design: Validation while editing) -------------------------------------
def _checks(row, level=None):
    return [c["text"] for c in row["checks"] if level is None or c["level"] == level]


def test_rows_are_checked_as_soon_as_their_upload_is_confirmed(api, login, services):
    login()
    job = new_job(api)
    row = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "20-0501.jpg", "size": 3, "type": "image/jpeg"}]}).json()["rows"][0]
    services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=row["s3Key"], Body=b"abc")
    checked = api.post(f"/api/jobs/{job}/rows/{row['n']}/uploaded").json()["row"]
    assert any("No object 20-0501" in t for t in _checks(checked, "block"))


def test_editing_a_row_rechecks_it(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"obj": "77-7777"}).json()["row"]
    assert any("No object 77-7777" in t for t in _checks(row, "block"))
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"obj": "15-1234"}).json()["row"]
    assert not _checks(row, "block")


def test_a_duplicate_id_updates_the_other_row_too(api, login, add_uploaded):
    login()
    job = new_job(api)
    a, b = add_uploaded(job, ["1-2345_1.jpg", "12-5678_1.jpg"])
    r = api.patch(f"/api/jobs/{job}/rows/{b['n']}", json={"idnum": a["idnum"]}).json()
    assert any("Another document in this job" in t for t in _checks(r["row"], "warn"))
    other = {x["n"]: x for x in r["others"]}[a["n"]]
    assert any("Another document in this job" in t for t in _checks(other, "warn"))
    # deleting one row clears the warning on the other
    others = api.delete(f"/api/jobs/{job}/rows/{b['n']}").json()["others"]
    assert [x["n"] for x in others] == [a["n"]] and not any("Another document" in t for t in _checks(others[0]))


def test_lookups_are_reused_until_the_searched_value_changes(api, login, add_uploaded, fake):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    fake.searches.clear()
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"description": "no new lookups"})
    assert fake.searches == []
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"obj": "1-2345"})
    assert ("collectionobjects", "1-2345") in fake.searches
    # a batch check of a few rows asks CollectionSpace once per distinct value
    add_uploaded(job, ["12-5678_1.jpg", "12-5678_2.jpg"])
    fake.searches.clear()
    api.post(f"/api/jobs/{job}/check", json={"rows": [2, 3]})
    assert fake.searches.count(("collectionobjects", "12-5678")) <= 1


def test_existing_media_warning_names_the_csid(api, login, add_uploaded, fake):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"idnum": "15-1234"}).json()["row"]
    csid = next(c for c, m in fake.media.items() if m["identificationNumber"] == "15-1234")
    assert any(csid in t for t in _checks(row, "warn"))


def test_unsupported_file_type_blocks(api, login, add_uploaded):
    login()
    job = new_job(api)
    row = add_uploaded(job, ["15-1234_a.docx"])[0]
    chk = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any("doesn't accept .docx" in t for t in _checks(chk, "block"))


def test_scheduling_fetches_permissions_again(api, login, add_uploaded, fake, services):
    """Design: roles can change during a session, so scheduling re-fetches permissions and re-checks the job."""
    login()
    job = new_job(api)
    n = add_uploaded(job, ["30-0001.jpg"])[0]["n"]
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "create"})
    fake.perm_overrides["admin"] = {"collectionobjects": "RL"}  # admin loses create on objects
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 409
    row = api.get(f"/api/jobs/{job}").json()["rows"][0]
    assert any("can't create Object records" in t for t in _checks(row, "block"))
    assert api.get("/api/me").json()["perms"]["objects"] is False
    assert services.storage.get_credential(job) is None


def test_a_date_collectionspace_cannot_interpret_blocks(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "sometime last spring"}).json()["row"]
    assert any("can't interpret the date" in t for t in _checks(row, "block"))
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 409
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "2024-05-14"}).json()["row"]
    assert not _checks(row, "block")


# ---- bulk-change panel (design: User interface, Bulk-change panel) -------------------------------
def test_bulk_change_applies_to_every_target_and_rechecks(api, login, add_uploaded):
    login()
    job = new_job(api)
    rows = add_uploaded(job, ["30-0001.jpg", "30-0002.jpg", "15-1234_a.jpg"])
    ref = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'"
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [rows[0]["n"], rows[1]["n"]],
                                                     "changes": {"handling": "create", "restricted": True, "creator": ref}})
    assert r.status_code == 200, r.text
    changed = {x["n"]: x for x in r.json()["rows"]}
    for n in (rows[0]["n"], rows[1]["n"]):
        assert changed[n]["handling"] == "create" and changed[n]["restricted"] and changed[n]["creator"] == ref
        assert not _checks(changed[n], "block")  # rechecked: objects are created, so nothing to fix
    assert rows[2]["n"] not in changed or changed[rows[2]["n"]]["handling"] == "link"


def test_bulk_change_is_never_applied_partially(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    a, b = add_uploaded(job, ["15-1234_a.jpg", "1-2345_1.jpg"])
    row = services.storage.get_row(job, b["n"])
    row["result"] = {"state": "Partial", "steps": {"media": {"s": "done", "csid": "m1"}}}
    services.storage.put_row(job, row)
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"], b["n"]], "changes": {"restricted": True}})
    assert r.status_code == 409 and r.json()["detail"]["rows"] == [b["n"]]
    assert services.storage.get_row(job, a["n"])["restricted"] is False  # nothing was changed
    # a value the locked row already has is no change for it, so it doesn't block
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"], b["n"]], "changes": {"restricted": False, "type": "image"}})
    assert r.status_code == 409  # type would change the locked row
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"], b["n"]], "changes": {"restricted": False}})
    assert r.status_code == 200


def test_disable_and_enable_selected_work_on_partial_rows(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    a, b = add_uploaded(job, ["15-1234_a.jpg", "1-2345_1.jpg"])
    row = services.storage.get_row(job, b["n"])
    row["result"] = {"state": "Partial", "steps": {"media": {"s": "done", "csid": "m1"}}}
    services.storage.put_row(job, row)
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"], b["n"]], "changes": {"include": False}})
    assert r.status_code == 200 and all(not x["include"] for x in r.json()["rows"] if x["n"] in (a["n"], b["n"]))
    # a disabled row takes no other changes
    assert api.patch(f"/api/jobs/{job}/rows/{a['n']}", json={"restricted": True}).status_code == 422


def test_failed_row_whose_object_step_ran_keeps_its_handling(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    a = add_uploaded(job, ["15-1234_a.jpg"])[0]
    row = services.storage.get_row(job, a["n"])
    row["result"] = {"state": "Failed", "steps": {"media": {"s": "failed"}, "findObject": {"s": "done", "csid": "o1"}}}
    services.storage.put_row(job, row)
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"]], "changes": {"handling": "create"}})
    assert r.status_code == 409
    assert api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"]], "changes": {"restricted": True}}).status_code == 200


def test_a_stale_check_never_overwrites_a_newer_upload_confirmation(api, login, services):
    """Seen in a browser run: a batch check read the rows, the upload of one was confirmed, then the check
    saved its stale copy and the row was stuck on "pending". Rows are versioned now."""
    from bmu.rows import check_rows
    from conftest import factory
    login()
    job = new_job(api)
    row = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_a.jpg", "size": 3, "type": "image/jpeg"}]}).json()["rows"][0]
    stale = services.storage.get_rows(job)  # the batch check reads the rows...
    services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=row["s3Key"], Body=b"abc")
    assert api.post(f"/api/jobs/{job}/rows/{row['n']}/uploaded").json()["row"]["upload"]["s"] == "done"
    check_rows(services.tenant, stale, factory("admin", "admin"), {"media": True, "relations": True, "objects": True})
    assert services.storage.save_checks(job, stale[0]) is False  # ...and its stale result is not saved
    assert services.storage.get_row(job, row["n"])["upload"]["s"] == "done"


def test_a_stale_row_edit_is_refused(api, login, add_uploaded, services):
    from bmu.storage import RowChanged
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    a, b = services.storage.get_row(job, n), services.storage.get_row(job, n)
    a["description"] = "first"
    services.storage.put_row(job, a)
    b["description"] = "second"
    try:
        services.storage.put_row(job, b)
        raise AssertionError("a stale copy was saved")
    except RowChanged:
        pass
    assert services.storage.get_row(job, n)["description"] == "first"


def test_bulk_save_puts_rows_back_if_one_changed_meanwhile(api, login, add_uploaded, services):
    from bmu.storage import RowChanged
    login()
    job = new_job(api)
    a, b = (services.storage.get_row(job, r["n"]) for r in add_uploaded(job, ["15-1234_a.jpg", "1-2345_1.jpg"]))
    import copy
    originals = copy.deepcopy([a, b])
    other = services.storage.get_row(job, b["n"]); other["description"] = "someone else"; services.storage.put_row(job, other)
    a["restricted"] = b["restricted"] = True
    try:
        services.storage.put_rows_all_or_none(job, [a, b], originals)
        raise AssertionError("expected RowChanged")
    except RowChanged:
        pass
    assert services.storage.get_row(job, a["n"])["restricted"] is False  # put back
    assert services.storage.get_row(job, b["n"])["description"] == "someone else"


def test_rechecking_one_row_never_saves_partial_checks_for_another(api, login, services):
    """Seen in a browser run: two uploads confirmed together; one row's re-check evaluated the other row
    without its lookups and saved that, wiping its checks."""
    login()
    job = new_job(api)
    a, b = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": n, "size": 3, "type": "image/jpeg"} for n in ["20-0501.jpg", "20-0502.jpg"]]}).json()["rows"]
    for r in (a, b):
        services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=r["s3Key"], Body=b"abc")
    api.post(f"/api/jobs/{job}/rows/{b['n']}/uploaded")          # b checked: its object isn't found
    # the moment of the race: b's checks are saved, but a's re-check reads b without its lookups
    row = services.storage.get_row(job, b["n"])
    assert any("No object 20-0502" in c["text"] for c in row["checks"])
    row.pop("lookups")
    services.storage.put_row(job, row)
    api.post(f"/api/jobs/{job}/rows/{a['n']}/uploaded")          # a's re-check also re-evaluates b
    row = services.storage.get_row(job, b["n"])
    assert any("No object 20-0502" in c["text"] for c in row["checks"])  # not wiped by a partial check


# ---- repeating media type and language (design: Media record fields) ------------------------------
ENG = "urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(languages):item:name(eng)'English'"
SPA = "urn:cspace:pahma.cspace.berkeley.edu:vocabularies:name(languages):item:name(spa)'Spanish'"


def test_media_type_and_language_repeat_and_reach_collectionspace(api, login, add_uploaded, worker, fake):
    me = login()
    assert {"value": "image", "label": "image"} in me["tenant"]["mediaTypes"]
    job = new_job(api)
    row = add_uploaded(job, ["15-1234_a.jpg"])[0]
    assert row["type"] == [] and row["language"] == [ENG]  # the tenant's default language
    r = api.patch(f"/api/jobs/{job}/rows/{row['n']}", json={"type": ["image", "", "slide", "image"], "language": [ENG, SPA]})
    assert r.status_code == 200, r.text
    assert r.json()["row"]["type"] == ["image", "slide"]  # blanks and repeats dropped, order kept
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    xml = next(m["xml"] for m in fake.media.values() if "xml" in m)
    assert xml.count("<type>") == 2 and "<type>slide</type>" in xml
    assert xml.count("<language>") == 2 and "name(spa)" in xml


def test_repeating_fields_accept_only_listed_values(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    assert api.patch(f"/api/jobs/{job}/rows/{n}", json={"type": ["photograph"]}).status_code == 422
    assert api.patch(f"/api/jobs/{job}/rows/{n}", json={"type": "image"}).status_code == 422
    assert api.patch(f"/api/jobs/{job}/rows/{n}", json={"language": ["English"]}).status_code == 422
    assert api.patch(f"/api/jobs/{job}/rows/{n}", json={"language": []}).status_code == 200  # the default is sent then


def test_bulk_media_type_replaces_the_list(api, login, add_uploaded):
    login()
    job = new_job(api)
    a, b = add_uploaded(job, ["15-1234_a.jpg", "1-2345_1.jpg"])
    api.patch(f"/api/jobs/{job}/rows/{a['n']}", json={"type": ["image", "slide"]})
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"], b["n"]], "changes": {"type": ["document"]}})
    assert all(x["type"] == ["document"] for x in r.json()["rows"] if x["n"] in (a["n"], b["n"]))


def test_languages_vocabulary(api, login):
    login()
    terms = api.get("/api/vocabularies/languages").json()["terms"]
    assert {"refName": ENG, "displayName": "English"} in terms
    assert [t["displayName"] for t in terms] == sorted(t["displayName"] for t in terms)
    assert api.get("/api/vocabularies/materials").status_code == 404


def test_rows_saved_with_a_single_media_type_are_upgraded(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    row = services.storage.get_row(job, n)
    row["type"] = "image"  # as saved before media type was repeating
    services.storage.put_row(job, row)
    assert services.storage.get_row(job, n)["type"] == ["image"]


# ---- structured dates (design: Structured dates) ---------------------------------------------------
def test_dates_are_parsed_by_collectionspace_and_saved_structured(api, login, add_uploaded, worker, fake):
    login()
    assert api.get("/api/dates/parse", params={"text": "circa 1850"}).json()["group"]["dateEarliestSingleCertainty"] == "approximate"
    assert api.get("/api/dates/parse", params={"text": "sometime"}).json() == {"ok": False, "group": {}}
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "1920s"}).json()["row"]
    assert not _checks(row, "block") and row["lookups"]["date"]["group"]["dateLatestYear"] == "1929"
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "the twenties"}).json()["row"]
    assert any("can't interpret the date" in t for t in _checks(row, "block"))
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "circa 1850"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    worker.tick()
    xml = next(m["xml"] for m in fake.media.values() if "xml" in m)
    assert "<dateDisplayDate>circa 1850</dateDisplayDate>" in xml
    assert "<dateEarliestSingleYear>1850</dateEarliestSingleYear>" in xml and "approximate" in xml


def test_clearing_the_date_clears_its_parse(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "nonsense"})
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": ""}).json()["row"]
    assert "date" not in row["lookups"] and not _checks(row, "block")


def test_a_new_lookup_on_a_row_that_already_has_lookups_is_saved(api, login, add_uploaded, services):
    """Seen in a browser run: the date's parse was added to the row's existing lookups in place, compared
    equal to the "before" copy, and was never saved, so the run sent no structured date."""
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    assert services.storage.get_row(job, n)["lookups"].get("object")  # already has lookups
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "circa 1850"})
    assert services.storage.get_row(job, n)["lookups"]["date"]["ok"] is True


# ---- filenames: cleaned on add, renamed with the filename rules (design: Filenames; Editable names) -------
def test_filenames_are_cleaned_when_added_and_staged_under_random_keys(api, login):
    login()
    job = new_job(api)
    rows = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "C:\\Users\\me\\15-1234_a.jpg", "size": 3, "type": "image/jpeg"},
                                                               {"name": "x" * 150 + ".tif", "size": 3, "type": "image/tiff"}]}).json()["rows"]
    assert rows[0]["file"] == "15-1234_a.jpg" and rows[0]["objParsed"] == "15-1234"
    assert len(rows[1]["file"]) == 100 and rows[1]["file"].endswith(".tif")
    assert "15-1234" not in rows[0]["s3Key"] and rows[0]["s3Key"].count("/") == 2
    r = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "../../etc/passwd..jpg", "size": 3, "type": "image/jpeg"}]})
    assert r.status_code == 422


def test_renaming_reparses_the_numbers_and_rechecks(api, login, add_uploaded):
    login()
    job = new_job(api)
    a, b = add_uploaded(job, ["IMG 4411.jpg", "1-2345_1.jpg"])
    row = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any("No object number" in t for t in _checks(row, "block"))
    for bad, why in [("1-2345 3.jpg", "Remove spaces"), ("1-2345_3.png", "Keep the extension .jpg"), ("1-2345_1.JPG", "already has this name"),
                     ("x/1-2345_3.jpg", "Remove slashes"), ("bad name!.jpg", "Use only letters"), ("_x.jpg", "filename pattern")]:
        r = api.patch(f"/api/jobs/{job}/rows/{a['n']}", json={"file": bad})
        assert r.status_code == 422 and why in r.json()["detail"], (bad, r.text)
    row = api.patch(f"/api/jobs/{job}/rows/{a['n']}", json={"file": "1-2345_3.jpg"}).json()["row"]
    assert (row["file"], row["fileOriginal"], row["objParsed"], row["obj"], row["idnum"]) == ("1-2345_3.jpg", "IMG 4411.jpg", "1-2345", "1-2345", "1-2345")
    assert not _checks(row, "block")
    assert api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [a["n"]], "changes": {"file": "x.jpg"}}).status_code == 422


def test_edited_numbers_keep_their_edits_and_derived_ones_follow(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_a.jpg"])[0]["n"]
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"obj": "1-2345"}).json()["row"]
    assert row["idnum"] == "1-2345"  # the ID follows the edited object number
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"file": "12-5678_a.jpg"}).json()["row"]
    assert row["objParsed"] == "12-5678" and row["obj"] == "1-2345"  # the edited object number is kept
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"obj": "12-5678"}).json()["row"]  # "Use parsed value"
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"idnum": "MY-ID"}).json()["row"]
    row = api.patch(f"/api/jobs/{job}/rows/{n}", json={"file": "15-1240_1.jpg"}).json()["row"]
    assert row["obj"] == "15-1240" and row["idnum"] == "MY-ID"  # the object number follows; the edited ID doesn't
