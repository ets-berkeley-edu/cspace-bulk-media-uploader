"""Demo tools (demo builds only, BMU_DEMO=true): slowing the browser's uploads, controlling the simulated
CollectionSpace, and deleting every job to start a demo afresh. Off by default: every endpoint is 404."""
import pytest
from fastapi.testclient import TestClient

from fakecspace.app import app as fake_app


@pytest.fixture
def demo(services):
    services.settings.demo = True
    services.demo.sim = TestClient(fake_app, base_url="http://fake")
    return services.demo


def new_job(api, name="Demo"):
    return api.post("/api/jobs", json={"name": name}).json()["id"]


def test_off_by_default_every_demo_endpoint_is_404_and_uploads_go_to_s3(api, login, services):
    login()
    assert services.settings.demo is False
    for method, path, body in [("GET", "/api/_demo/status", None), ("POST", "/api/_demo/browser-upload", {"mbps": 1}),
                               ("POST", "/api/_demo/sim/slow", {"params": {"seconds": 2}}), ("GET", "/api/_demo/sim/objects", None),
                               ("POST", "/api/_demo/delete-all-jobs", {}), ("POST", "/api/_demo/s3upload", None),
                               ("POST", "/api/_demo/sign-in-as", {"user": "intern"})]:
        assert api.request(method, path, json=body).status_code == 404, path
    services.demo.browser_upload_mbps = 1.0  # even if set somehow, uploads aren't rerouted while demo mode is off
    job = new_job(api)
    form = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_1.jpg", "size": 5, "type": "image/jpeg"}]}).json()["rows"][0]["uploadForm"]
    assert not form["url"].startswith("/api/")


def test_demo_endpoints_need_a_signed_in_user(api, demo):
    assert api.get("/api/_demo/status").status_code == 401
    assert api.post("/api/_demo/delete-all-jobs").status_code == 401


def test_status_shows_the_simulator_settings_and_samples(api, login, demo, fake):
    login()
    st = api.get("/api/_demo/status").json()
    assert st["browserUploadMbps"] == 0 and st["simError"] == ""
    assert st["sim"]["delay"] == 0 and "Leslie Freund" in st["sim"]["people"] and st["sim"]["languages"]["spa"] == "Spanish"
    assert "termRead" in st["sim"]["steps"] and "Leslie Freund" in st["sim"]["term_names"].values()


def test_simulator_controls_are_passed_on_and_only_known_ones(api, login, demo, fake):
    login()
    r = api.post("/api/_demo/sim/slow", json={"params": {"seconds": 2, "upload_mbps": 5}})
    assert r.status_code == 200 and fake.delay == 2 and fake.upload_mbps == 5 and r.json()["upload_mbps"] == 5
    assert api.post("/api/_demo/sim/fail", json={"params": {"step": "upload", "status": 500, "count": 1}}).json()["rules"][0]["step"] == "upload"
    assert api.post("/api/_demo/sim/rename-term", json={"params": {"name": "Leslie Freund", "to": "Leslie Freund (1950-)"}}).status_code == 200
    assert list(fake.term_renames.values()) == ["Leslie Freund (1950-)"]
    bad = api.post("/api/_demo/sim/fail", json={"params": {"step": "nonsense"}})
    assert bad.status_code == 400 and "step must be one of" in bad.json()["detail"]
    assert api.post("/api/_demo/sim/objects-delete-all", json={"params": {}}).status_code == 404  # not a known control
    assert api.post("/api/_demo/sim/clear-failures", json={"params": {}}).json()["rules"] == []
    api.post("/api/_demo/sim/reset", json={"params": {}})
    assert fake.delay == 0 and fake.term_renames == {}
    assert any(o["objectNumber"] for o in api.get("/api/_demo/sim/objects").json()["objects"])


def test_a_real_server_is_reported_not_passed_on(api, login, demo):
    login()
    demo.sim = TestClient(__import__("fastapi").FastAPI(), base_url="http://real")  # answers 404 to /_fake/...
    st = api.get("/api/_demo/status").json()
    assert st["sim"] is None and "only work with the simulated CollectionSpace" in st["simError"]
    assert api.post("/api/_demo/sim/slow", json={"params": {"seconds": 1}}).status_code == 502


def test_browser_uploads_go_through_the_web_app_at_the_set_speed(api, login, demo, services):
    login()
    assert api.post("/api/_demo/browser-upload", json={"mbps": 1}).json() == {"browserUploadMbps": 1}
    job = new_job(api)
    row = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_1.jpg", "size": 300_000, "type": "image/jpeg"}]}).json()["rows"][0]
    form = row["uploadForm"]
    assert form["url"] == "/api/_demo/s3upload" and form["fields"]["key"] == row["s3Key"]  # the same signed fields
    fresh = api.post(f"/api/jobs/{job}/rows/{row['n']}/upload-form", json={"size": 300_000}).json()["uploadForm"]
    assert fresh["url"] == "/api/_demo/s3upload" and fresh["fields"]["key"] == row["s3Key"]  # a fresh form goes the same way

    seen, waits = {}, []

    async def forward(url, headers, body):
        seen.update(url=url, headers=headers, body=b"".join([c async for c in body]))
        return 204, "", b""

    async def sleep(t):
        waits.append(t)
    services.demo.forward, services.demo.sleep = forward, sleep
    files = {"file": ("15-1234_1.jpg", b"x" * 300_000, "image/jpeg")}
    r = api.post("/api/_demo/s3upload", data=form["fields"], files=files)
    assert r.status_code == 204
    assert seen["url"] == services.demo.s3_post_url() and services.settings.s3_bucket in seen["url"]  # the web app's own S3 endpoint
    assert seen["headers"]["content-type"].startswith("multipart/form-data") and b"x" * 1000 in seen["body"]
    assert 0.25 < max(waits) < 0.32  # the last piece waits until about 0.29 s: 300,000 bytes at 1 MB/s (the fake sleep doesn't pass time)

    api.post("/api/_demo/browser-upload", json={"mbps": 0})  # full speed: straight to S3 again
    row2 = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_2.jpg", "size": 5, "type": "image/jpeg"}]}).json()["rows"][0]
    assert row2["uploadForm"]["url"] != "/api/_demo/s3upload"


def test_delete_all_jobs_deletes_every_job_but_running_ones_and_writes_the_audit(api, login, demo, add_uploaded, services):
    login()
    a, b = new_job(api, "A"), new_job(api, "B")
    services.storage.update_job(b, {"editingSession": "someone-elses-session", "editingBy": "jlee"})  # open in another editor
    add_uploaded(a, ["15-1234_1.jpg"])
    running = new_job(api, "Running one")
    services.storage.update_job(running, {"status": "Running"})
    r = api.post("/api/_demo/delete-all-jobs").json()
    assert r["deleted"] == 2 and r["skipped"] == ["Running one"]
    assert [j["id"] for j in services.storage.list_jobs("pahma")] == [running]
    assert services.storage.get_job(a) is None and services.storage.get_job(b) is None


def test_reset_everything_clears_jobs_files_audit_and_schedule_and_keeps_the_sign_in(api, login, demo, add_uploaded, services, worker, fake):
    login()
    done = new_job(api, "Ran")
    add_uploaded(done, ["1-2345_a.jpg"])
    assert api.post(f"/api/jobs/{done}/schedule").status_code == 200 and worker.tick()
    draft = new_job(api, "A draft")
    add_uploaded(draft, ["12-5678_1.jpg"])
    queued = new_job(api, "Queued")
    add_uploaded(queued, ["15-1240_1.jpg"])
    assert api.post(f"/api/jobs/{queued}/schedule").status_code == 200
    assert api.put("/api/schedule", json={"days": [1, 3, 5], "start": "07:30", "end": ""}).status_code == 200
    api.post("/api/_demo/sim/slow", json={"params": {"seconds": 2}})
    api.post("/api/_demo/browser-upload", json={"mbps": 2})
    assert services.storage.list_audit("pahma") and services.storage.get_credential(queued) is not None
    media_before = len(fake.media)

    r = api.post("/api/_demo/reset-everything")
    assert r.status_code == 200 and r.json()["items"] > 0 and r.json()["objects"] > 0, r.text
    assert api.get("/api/jobs").json()["jobs"] == []
    assert services.storage.list_audit("pahma") == []
    assert services.storage.get_credential(queued) is None
    assert services.storage.get_rows(draft) == []
    assert api.get("/api/schedule").json()["start"] == "19:00"  # back to the default
    left = services.storage.s3.list_object_versions(Bucket=services.settings.s3_bucket)
    assert not left.get("Versions") and not left.get("DeleteMarkers")
    status = api.get("/api/_demo/status").json()
    assert status["browserUploadMbps"] == 0 and status["sim"]["delay"] == 0
    assert len(fake.media) < media_before  # the simulated CollectionSpace is back to its samples
    assert api.get("/api/me").status_code == 200  # still signed in
    assert new_job(api, "After")  # and the prototype works again


def test_reset_everything_is_refused_while_a_job_runs_and_against_a_real_server(api, login, demo, services):
    login()
    running = new_job(api, "Running one")
    services.storage.update_job(running, {"status": "Running"})
    r = api.post("/api/_demo/reset-everything")
    assert r.status_code == 409 and "“Running one” is running" in r.json()["detail"]
    assert services.storage.get_job(running) is not None
    services.storage.update_job(running, {"status": "Draft"})
    # a real CollectionSpace has no simulator controls: nothing is deleted, least of all the audit log
    demo.sim = TestClient(__import__("fastapi").FastAPI(), base_url="http://real")  # answers 404 to /_fake/...
    r = api.post("/api/_demo/reset-everything")
    assert r.status_code == 502 and "not a real server" in r.json()["detail"]
    assert services.storage.get_job(running) is not None


# ---- Sign in as: one of the simulator's users, with a click ---------------------------------------------------------
def test_status_lists_the_simulators_users_without_their_passwords_and_says_who_you_are(api, login, demo):
    login()
    st = api.get("/api/_demo/status").json()
    assert (st["user"], st["role"]) == ("admin", "staff")
    assert [u["user"] for u in st["users"]] == ["admin", "limited", "reader", "intern", "newstaff"]
    assert st["users"][3] == {"user": "intern", "about": "Intern: no CollectionSpace permissions"}
    assert "password" not in str(st)


def test_sign_in_as_switches_the_user_and_releases_the_old_sessions_draft(api, login, demo, services):
    login()
    draft = new_job(api)  # open in admin's editor
    old = services.storage.sessions.scan()["Items"][0]["PK"]
    r = api.post("/api/_demo/sign-in-as", json={"user": "intern"})
    assert r.status_code == 200 and (r.json()["user"], r.json()["role"]) == ("intern", "intern")
    assert api.get("/api/me").json()["user"] == "intern"  # the cookie is the new session's
    assert services.storage.get_session(old) is None and len(services.storage.sessions.scan()["Items"]) == 1
    assert "editingSession" not in services.storage.get_job(draft)
    assert api.post("/api/schedule/pause", json={"reason": "x"}).status_code == 403  # an intern, as if typed in
    assert api.post("/api/_demo/sign-in-as", json={"user": "limited"}).json()["role"] == "staff"


def test_sign_in_as_a_refused_account_says_why_and_leaves_you_signed_in(api, login, demo, services):
    login()
    for user, code in [("reader", "no_role"), ("newstaff", "account")]:
        r = api.post("/api/_demo/sign-in-as", json={"user": user})
        assert r.status_code == 403 and r.json()["detail"]["code"] == code
        assert "Contact your CollectionSpace administrator" in r.json()["detail"]["message"]
    assert api.post("/api/_demo/sign-in-as", json={"user": "nobody"}).status_code == 404
    assert api.get("/api/me").json()["user"] == "admin" and len(services.storage.sessions.scan()["Items"]) == 1


def test_sign_in_as_is_refused_against_a_real_server(api, login, demo):
    import httpx
    login()
    demo.sim = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404)), base_url="http://real")
    r = api.post("/api/_demo/sign-in-as", json={"user": "admin"})
    assert r.status_code == 502 and "Demo tools only work with the" in r.json()["detail"]
    assert api.get("/api/_demo/status").json()["users"] == []
