"""Permission checks, autocomplete sources and the idle sign-out (design: Authentication; Authority term fields)."""
import bmu.app as appmod
from bmu.storage import now


def new_job(api):
    return api.post("/api/jobs", json={"name": "Perms"}).json()["id"]


def _texts(row):
    return [c["text"] for c in row["checks"]]


def test_attaching_the_file_needs_update_on_media(api, login, add_uploaded, fake):
    fake.perm_overrides["admin"] = {"media": "CRL"}
    me = login()
    assert me["perms"]["mediaUpdate"] is False
    job = new_job(api)
    row = add_uploaded(job, ["15-1234_1.jpg"])[0]
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any("can't update Media records" in t for t in _texts(r))


def test_finding_objects_needs_read_on_objects(api, login, add_uploaded, fake):
    fake.perm_overrides["admin"] = {"collectionobjects": "C"}
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any("can't read Object records" in t for t in _texts(r))


def test_without_read_on_media_the_id_check_blocks(api, login, add_uploaded, fake):
    fake.perm_overrides["admin"] = {"media": "CU"}
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any(c["level"] == "block" and "can't read Media records" in c["text"] for c in r["checks"])


def test_a_filled_authority_field_needs_read_on_its_authority(api, login, add_uploaded, fake):
    fake.perm_overrides["admin"] = {"personauthorities": ""}
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert not any("authority" in t for t in _texts(r))  # empty fields need no check
    ref = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'"
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"creator": ref}).json()["row"]
    assert any(c["level"] == "block" and "can't read the Person authority" in c["text"] and "Creator" in c["text"]
               for c in r["checks"])


def test_dates_need_the_date_parser(api, login, add_uploaded, fake):
    fake.perm_overrides["admin"] = {"structureddates": ""}
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"date": "1920s"}).json()["row"]
    assert any("date parser" in t for t in _texts(r))


def test_autocomplete_drops_sources_the_user_cannot_read_and_counts_matches(api, login, fake, monkeypatch):
    fake.perm_overrides["admin"] = {"orgauthorities": ""}
    login()
    r = api.get("/api/authorities", params={"field": "creator", "q": "hearst"}).json()
    assert r["terms"] == []  # organizations dropped silently
    monkeypatch.setattr(appmod, "AUTOCOMPLETE_PAGE", 1)
    r = api.get("/api/authorities", params={"field": "creator", "q": "cha"}).json()  # Michael T. Black, Zachary Williams
    assert len(r["terms"]) == 1 and r["total"] == 2 and r["more"] is True
    fake.perm_overrides["admin"] = {"orgauthorities": "", "personauthorities": ""}
    login()
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
    services.storage.touch_session(key, now() - 31 * 60)
    r = api.get("/api/jobs")
    assert r.status_code == 401 and "30 minutes without activity" in r.json()["detail"]
    assert services.storage.get_session(key) is None


def test_the_sweep_deletes_idle_and_expired_sessions_with_their_passwords(api, login, services, worker):
    """Design: expiry deletes the session record. An abandoned tab never makes the request that would notice."""
    login()
    login("limited")
    login("reader")
    keys = {i["user"]: i["PK"] for i in services.storage.sessions.scan()["Items"]}
    services.storage.touch_session(keys["admin"], now() - 31 * 60)  # idle
    services.storage.sessions.update_item(Key={"PK": keys["limited"]}, UpdateExpression="SET expires = :e",
                                          ExpressionAttributeValues={":e": int(now()) - 10})  # past the 8 hours
    assert services.storage.get_session(keys["limited"]) is None  # an expired session read is deleted at once
    assert services.storage.sweep_sessions(30 * 60) == 1
    left = {i["user"] for i in services.storage.sessions.scan()["Items"]}
    assert left == {"reader"}
    worker.sweep()  # the worker's periodic checks include it
    assert {i["user"] for i in services.storage.sessions.scan()["Items"]} == {"reader"}



def test_autocomplete_timing_comes_from_the_tenant_profile(api, login):
    me = login()
    assert me["tenant"]["autocomplete"] == {"findDelayMs": 1000, "minLength": 3}  # PAHMA's UI profile
    assert api.get("/api/authorities", params={"field": "creator", "q": "ha"}).json()["terms"] == []


def test_authority_vocabularies_are_listed_for_the_check_script(fake):
    from conftest import factory
    c = factory("admin", "admin")
    assert [v["shortIdentifier"] for v in c.authority_vocabularies("personauthorities")] == ["person"]  # no "shared"
    assert [v["shortIdentifier"] for v in c.authority_vocabularies("orgauthorities")] == ["organization"]
