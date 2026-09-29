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


def test_without_read_on_media_the_id_check_is_a_warning(api, login, add_uploaded, fake):
    fake.perm_overrides["admin"] = {"media": "CU"}
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    r = api.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert any(c["level"] == "warn" and "can't read Media records" in c["text"] for c in r["checks"])


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
