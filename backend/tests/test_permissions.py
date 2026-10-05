"""Permission checks, autocomplete sources and the idle sign-out (design: Authentication; Authority term fields)."""
import bmu.app as appmod
from bmu.storage import now


def new_job(api):
    return api.post("/api/jobs", json={"name": "Perms"}).json()["id"]


def _texts(row):
    return [c["text"] for c in row["checks"]]


def _set_session_perms(services, user="admin", **changes):
    """As if the user's roles changed after they signed in (the session keeps what it read at sign-in)."""
    item = next(i for i in services.storage.sessions.scan()["Items"] if i["user"] == user)
    services.storage.update_session_perms(item["PK"], {**item["perms"], **changes})


def test_attaching_the_file_needs_update_on_media(api, login, add_uploaded, fake, services):
    """The row check stays as a backstop: a session whose account lost update on media sees it when viewing."""
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    _set_session_perms(services, mediaUpdate=False)
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any("can't update Media records" in t for t in _texts(r))


def test_scheduling_is_refused_when_the_account_lost_update_on_media_meanwhile(api, login, add_uploaded, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fake.perm_overrides["admin"] = {"media": "CRL"}  # permissions changed after signing in: submitting reads them again
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account"
    assert "can't update Media records" in r.json()["detail"]["message"]
    assert "Contact your CollectionSpace administrator" in r.json()["detail"]["message"]
    assert api.get(f"/api/jobs/{job}").json()["job"]["status"] == "Draft"


# ---- rows whose Media record exists: the rerun's own permission checks -----------------------------
def test_a_partial_rows_pending_upload_needs_update_on_media(api, login, add_uploaded, worker, services, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fail_on("upload", status=500)
    api.post(f"/api/jobs/{job}/schedule")
    worker.tick()
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert not any("can't update Media records" in t for t in _texts(r))
    _set_session_perms(services, mediaUpdate=False)
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any(c["level"] == "block" and "can't update Media records" in c["text"] for c in r["checks"])


def test_a_partial_rows_pending_object_lookup_needs_read_on_objects(api, login, add_uploaded, worker, services, fake, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    fail_on("objectSearch", effect="none")
    api.post(f"/api/jobs/{job}/schedule")
    worker.tick()
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    fake.perm_overrides["admin"] = {"collectionobjects": "C"}  # the lookup would now get a 403
    _set_session_perms(services, readObjects=False)
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any(c["level"] == "block" and "can't read Object records" in c["text"] for c in r["checks"]), _texts(r)
    assert not any(c["level"] == "warn" and "Couldn't check object" in c["text"] for c in r["checks"])


# ---- "No object found" offers only the handlings the user may pick ----------------------------------------
def test_no_object_found_offers_only_handlings_the_user_may_pick(api, login, add_uploaded):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0777_1.jpg"])  # handling "Link to existing object"; there is no such object
    text = next(c["text"] for c in api.post(f"/api/jobs/{job}/check").json()["rows"][0]["checks"] if c["level"] == "block")
    assert text.endswith("choose “Link to object (create if missing)” or “Create new object + link” or “Media only (no object)”.")
    login("limited")  # can't create objects
    job = new_job(api)
    add_uploaded(job, ["20-0777_1.jpg"])
    text = next(c["text"] for c in api.post(f"/api/jobs/{job}/check").json()["rows"][0]["checks"] if c["level"] == "block")
    assert text == "No object 20-0777 in CollectionSpace. Correct the object number, or choose “Media only (no object)”."


def test_no_object_found_without_a_media_only_handling_offers_only_creating():
    import dataclasses
    from bmu.rows import object_checks
    from bmu.tenant import load_tenant
    t = load_tenant("pahma")
    t = dataclasses.replace(t, handling=tuple(h for h in t.handling if h.object != "none"))
    all_perms = {"objects": True, "relations": True}
    assert object_checks(t, "existing", "1-1", [], all_perms)[0]["text"].endswith(
        "choose “Link to object (create if missing)” or “Create new object + link”.")
    assert object_checks(t, "existing", "1-1", [], {"relations": True})[0]["text"] == \
        "No object 1-1 in CollectionSpace. Correct the object number."


# ---- the job's Group: create on groups only while it doesn't exist -----------------------------------------
def test_joining_a_group_that_already_exists_needs_no_create_on_groups(api, login, add_uploaded, worker, services, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg", "12-5678_1.jpg"])
    api.patch(f"/api/jobs/{job}", json={"groupOn": True, "groupTitle": "Survey batch 4"})
    fail_on("objectSearch", effect="none", match="12-5678")  # document 2 doesn't reach the group this time
    api.post(f"/api/jobs/{job}/schedule")
    worker.tick()
    assert services.storage.get_job(job)["groupStep"]["s"] == "done"
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    _set_session_perms(services, groups=False)
    add_uploaded(job, ["3-1001_1.jpg"])  # a new document, still to create its Media record
    rows = {r["file"]: _texts(r) for r in api.post(f"/api/jobs/{job}/check").json()["rows"]}
    assert not any("can't create groups" in t for ts in rows.values() for t in ts), rows


def test_a_partial_row_joining_the_group_needs_create_on_groups_only_before_it_exists():
    from bmu.rows import check_rows
    from bmu.tenant import load_tenant
    t = load_tenant("pahma")
    done = {"s": "done", "csid": "x"}
    row = {"n": 1, "file": "15-1234_1.jpg", "handling": "link", "obj": "15-1234", "include": True, "group": True,
           "result": {"state": "Partial", "steps": {"media": done, "findObject": done, "upload": done, "relMediaObject": done,
                                                     "relObjectMedia": done, "addToGroup": {"s": "skipped", "after": "group"}}}}
    perms = {"media": True, "mediaUpdate": True, "relations": True, "objects": True, "readObjects": True, "groups": False}

    def texts(**kw):
        check_rows(t, [row], None, kw.pop("perms", perms), group_on=True, **kw)
        return [c["text"] for c in row["checks"] if c["level"] == "block"]
    assert any("can't create groups" in x for x in texts())
    assert texts(group_exists=True) == []
    assert any("can't be added to the job's group" in x for x in texts(group_exists=True, perms={**perms, "relations": False}))


def test_the_languages_vocabulary_is_read_whole_with_pgsz_0(fake):
    from conftest import factory
    c = factory("admin", "admin")
    seen = []
    real = c._http.request

    def spy(method, url, **kw):
        seen.append(kw.get("params"))
        return real(method, url, **kw)
    c._http.request = spy
    assert len(c.vocabulary_items("languages")) == 8
    assert seen[-1]["pgSz"] == "0"
    # the fake pages like CollectionSpace: pgSz=0 is every item
    terms, total = c.search_terms_page("personauthorities", "person", "a", 0)
    assert len(terms) == total > 1


def test_finding_objects_needs_read_on_objects(api, login, add_uploaded, fake, services):
    login()
    fake.perm_overrides["admin"] = {"collectionobjects": "C"}  # lost after signing in (staff can't sign in without it)
    _set_session_perms(services, readObjects=False)
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any("can't read Object records" in t for t in _texts(r))


def test_without_read_on_media_the_id_check_blocks(api, login, add_uploaded, fake, services):
    login()
    fake.perm_overrides["admin"] = {"media": "CU"}  # lost after signing in (staff can't sign in without it)
    _set_session_perms(services, readMedia=False)
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any(c["level"] == "block" and "can't read Media records" in c["text"] for c in r["checks"])


def test_a_filled_authority_field_needs_read_on_its_authority(api, login, add_uploaded, fake, services):
    login()
    fake.perm_overrides["admin"] = {"personauthorities": ""}  # lost after signing in (staff can't sign in without it)
    _set_session_perms(services, readPersons=False, authorities=False)
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert not any("authority" in t for t in _texts(r))  # empty fields need no check
    ref = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'"
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"creator": ref}).json()["row"]
    assert any(c["level"] == "block" and "can't read the Person authority" in c["text"] and "Creator" in c["text"]
               for c in r["checks"])


def test_dates_need_the_date_parser(api, login, add_uploaded, fake, services):
    login()
    fake.perm_overrides["admin"] = {"structureddates": ""}  # lost after signing in (staff can't sign in without it)
    _set_session_perms(services, readDates=False)
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "1920s"}).json()["row"]
    assert any("date parser" in t for t in _texts(r))


def test_autocomplete_drops_sources_the_user_cannot_read_and_counts_matches(api, login, fake, monkeypatch, services):
    login()
    fake.perm_overrides["admin"] = {"orgauthorities": ""}  # lost after signing in
    _set_session_perms(services, readOrgs=False, authorities=False)
    r = api.get("/api/authorities", params={"field": "creator", "q": "hearst"}).json()
    assert r["terms"] == []  # organizations dropped silently
    monkeypatch.setattr(appmod, "AUTOCOMPLETE_PAGE", 1)
    r = api.get("/api/authorities", params={"field": "creator", "q": "cha"}).json()  # Michael T. Black, Zachary Williams
    assert len(r["terms"]) == 1 and r["total"] == 2 and r["more"] is True
    fake.perm_overrides["admin"] = {"orgauthorities": "", "personauthorities": ""}
    _set_session_perms(services, readPersons=False)
    r = api.get("/api/authorities", params={"field": "creator", "q": "son"}).json()
    assert "can't read the Person or Organization authorities" in r["message"]


def test_idle_sessions_are_signed_out_but_polling_is_not_activity(api, login, services):
    login()
    key = next(iter(services.storage.sessions.scan()["Items"]))["PK"]
    services.storage.touch_session(key, now() - 20 * 60)
    assert api.get("/api/jobs", headers={"X-BMU-Poll": "1"}).status_code == 200  # a background refresh
    item = services.storage.get_session(key)
    assert item["lastSeen"] < now() - 19 * 60  # didn't count as activity
    assert api.get("/api/jobs").status_code == 200  # a real request renews it
    assert services.storage.get_session(key)["lastSeen"] > now() - 5
    draft = api.post("/api/jobs", json={"name": "left open"}).json()["id"]
    assert services.storage.get_job(draft)["editingSession"] == key
    services.storage.touch_session(key, now() - 31 * 60)
    r = api.get("/api/jobs")
    assert r.status_code == 401 and "30 minutes without activity" in r.json()["detail"]
    assert services.storage.get_session(key) is None
    # the draft it was editing is released, so others can edit it without taking over (design: Drafts, Closing)
    assert "editingSession" not in services.storage.get_job(draft) and "editingBy" not in services.storage.get_job(draft)


def test_the_sweep_deletes_idle_and_expired_sessions_with_their_passwords(api, login, services, worker):
    """Design: expiry deletes the session record. An abandoned tab never makes the request that would notice."""
    login()
    login("limited")
    login("intern")
    keys = {i["user"]: i["PK"] for i in services.storage.sessions.scan()["Items"]}
    login()  # admin again: a second session, with a draft open
    second = next(i["PK"] for i in services.storage.sessions.scan()["Items"] if i["PK"] not in keys.values())
    draft = api.post("/api/jobs", json={"name": "abandoned tab"}).json()["id"]
    assert services.storage.get_job(draft)["editingSession"] == second
    services.storage.touch_session(second, now() - 31 * 60)
    assert services.storage.sweep_sessions(30 * 60) == 1
    assert "editingSession" not in services.storage.get_job(draft)  # the sweep released the draft it was editing
    services.storage.touch_session(keys["admin"], now() - 31 * 60)  # idle
    services.storage.sessions.update_item(Key={"PK": keys["limited"]}, UpdateExpression="SET expires = :e",
                                          ExpressionAttributeValues={":e": int(now()) - 10})  # past the 8 hours
    assert services.storage.get_session(keys["limited"]) is None  # an expired session read is deleted at once
    assert services.storage.sweep_sessions(30 * 60) == 1
    left = {i["user"] for i in services.storage.sessions.scan()["Items"]}
    assert left == {"intern"}
    worker.sweep()  # the worker's periodic checks include it
    assert {i["user"] for i in services.storage.sessions.scan()["Items"]} == {"intern"}



def test_autocomplete_timing_comes_from_the_tenant_profile(api, login):
    me = login()
    assert me["tenant"]["autocomplete"] == {"findDelayMs": 1000, "minLength": 3}  # PAHMA's UI profile
    assert api.get("/api/authorities", params={"field": "creator", "q": "ha"}).json()["terms"] == []


def test_authority_vocabularies_are_listed_for_the_check_script(fake):
    from conftest import factory
    c = factory("admin", "admin")
    assert [v["shortIdentifier"] for v in c.authority_vocabularies("personauthorities")] == ["person"]  # no "shared"
    assert [v["shortIdentifier"] for v in c.authority_vocabularies("orgauthorities")] == ["organization"]
