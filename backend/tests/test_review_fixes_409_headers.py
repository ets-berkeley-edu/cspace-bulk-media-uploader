"""Review 4.8 (a 409 stops the job only for an inactive account) and 4.5 (security headers, image-only thumbnails)."""
from test_finished import new_job, run_once


def test_a_409_about_one_record_fails_that_document_and_the_job_carries_on(api, login, add_uploaded, worker, fail_on):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_a.jpg", "20-0501_b.jpg"])
    for n in (1, 2):
        api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly"})
    fail_on("media", status=409, match="20-0501_a")
    j = run_once(api, job, worker)
    rows = {r["file"]: r for r in j["rows"]}
    assert j["job"]["status"] == "NeedsAttention" and j["job"]["code"] == ""
    assert rows["20-0501_a.jpg"]["result"]["steps"]["media"]["code"] == "conflict"
    assert "account is active" in rows["20-0501_a.jpg"]["result"]["steps"]["media"]["detail"]
    assert rows["20-0501_b.jpg"]["result"]["state"] == "Done"


def test_an_inactive_account_stops_the_job_at_once(api, login, add_uploaded, worker, fake, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_c.jpg", "20-0501_d.jpg"])
    for n in (1, 2):
        api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    real = worker._check_staff
    worker._check_staff = lambda client, user: (real(client, user), fake.inactive.add("admin"))  # deactivated after the start
    worker.tick()
    j = services.storage.get_job(job)
    assert j["status"] == "Failed" and j["code"] == "account_inactive"
    assert services.storage.get_credential(job) is None


def test_every_answer_carries_the_security_headers(api, login):
    for r in (api.get("/api/env"), (login(), api.get("/api/me"))[1]):
        csp = r.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
        assert "connect-src 'self' http" in csp  # and the staging bucket, where the browser uploads
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
        assert "strict-transport-security" not in r.headers  # tests run without a Secure cookie (no HTTPS)


def test_hsts_where_the_site_is_https(api, services):
    services.settings.cookie_secure = True
    assert api.get("/api/env").headers["strict-transport-security"].startswith("max-age=")


def test_a_collectionspace_derivative_that_isnt_an_image_is_not_passed_on(api, login, add_uploaded, worker, monkeypatch):
    from bmu.cspace import CSpaceClient
    login()
    job = new_job(api)
    add_uploaded(job, ["20-0501_e.jpg"])
    api.patch(f"/api/jobs/{job}/rows/1", json={"handling": "mediaonly"})
    assert run_once(api, job, worker)["job"]["status"] == "Completed"
    for ctype in ("text/html", "image/svg+xml", "application/javascript"):
        monkeypatch.setattr(CSpaceClient, "derivative", lambda self, csid, name="Thumbnail", t=ctype: (b"<script>x</script>", t))
        assert api.get(f"/api/jobs/{job}/rows/1/thumbnail").status_code == 404
    monkeypatch.setattr(CSpaceClient, "derivative", lambda self, csid, name="Thumbnail": (b"\xff\xd8", "image/jpeg; charset=binary"))
    r = api.get(f"/api/jobs/{job}/rows/1/thumbnail")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
