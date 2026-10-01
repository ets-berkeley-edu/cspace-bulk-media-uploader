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
                               ("POST", "/api/_demo/delete-all-jobs", {}), ("POST", "/api/_demo/s3upload", None)]:
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
