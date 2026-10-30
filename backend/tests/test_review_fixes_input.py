"""Input handling found in the 29 October 2026 review: field types and sizes, failed sign-ins, large thumbnails, NaN."""
from bmu.app import MAX_BROWSER_BYTES
from test_flow import new_job


def test_a_row_field_of_the_wrong_type_or_size_is_refused_and_the_draft_still_checks(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    for change in ({"obj": ["a", "b"]}, {"include": "yes"}, {"description": "x" * 10001}, {"type": "photo"},
                   {"creator": {"refName": "x"}}, {"idnum": 5}):
        r = api.patch(f"/api/jobs/{job}/rows/{n}", json=change)
        assert r.status_code == 422, (change, r.text)
        r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [n], "changes": change})
        assert r.status_code == 422, (change, r.text)
    assert api.patch(f"/api/jobs/{job}/rows/{n}", json={"description": "x" * 10000}).status_code == 200
    assert api.post(f"/api/jobs/{job}/check").status_code == 200


def test_failed_sign_ins_are_limited_per_username(api, services, fake):
    allowed = services.settings.login_failures_allowed
    for _ in range(allowed):
        assert api.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    calls = len(fake.requests)
    r = api.post("/api/login", json={"username": "Admin", "password": "admin"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "login_limit"
    assert len(fake.requests) == calls  # CollectionSpace wasn't asked
    assert api.post("/api/login", json={"username": "limited", "password": "limited"}).status_code == 200  # others can


def test_a_huge_thumbnail_is_refused_before_it_is_read_whole(api, login, add_uploaded):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]

    def chunks():
        for _ in range(MAX_BROWSER_BYTES // 65536 + 2):
            yield b"\0" * 65536
    r = api.post(f"/api/jobs/{job}/rows/{n}/thumbnail", content=chunks())
    assert r.status_code == 413


def test_a_run_time_that_is_not_a_number_is_refused(api, login, add_uploaded):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    for bad in ("NaN", "Infinity"):
        r = api.post(f"/api/jobs/{job}/run-at", content=f'{{"at": {bad}}}', headers={"Content-Type": "application/json"})
        assert r.status_code == 422, r.text
