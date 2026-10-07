"""One deployment for several museums (design: One deployment for several museums). The tests' second museum,
"bampfa", is PAHMA's configuration under another name, on the same simulated CollectionSpace: what matters here is
that every request takes the museum from the session or the job, never from the deployment or the browser, and
that one museum's session can see and change nothing of another's."""
import dataclasses

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient

from bmu.app import Services, create_app, session_context
from bmu.crypto import job_context
from bmu.reader import Reader
from bmu.worker import Worker
from conftest import factory, worker_factory


def new_job(api, name="Museum test"):
    r = api.post("/api/jobs", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def museums(services):
    """The deployment serves two museums."""
    services.settings.tenants = {"pahma": "http://fake", "bampfa": "http://fake"}
    services.tenants["bampfa"] = dataclasses.replace(services.tenants["pahma"], key="bampfa", name="BAMPFA")
    services.readers["bampfa"] = Reader(services.settings, lambda u, p: factory("bampfa", u, p))
    return services


def client(services):
    c = TestClient(create_app(services), base_url="http://testserver")
    c.headers["X-BMU"] = "1"
    return c


def sign_in(c, museum=None, user="admin"):
    body = {"username": user, "password": user, **({"tenant": museum} if museum else {})}
    return c.post("/api/login", json=body)


# ---- choosing the museum at sign-in ---------------------------------------------------------------------------------

def test_the_sign_in_page_lists_the_museums(api, museums):
    assert api.get("/api/env").json()["tenants"] == [{"key": "pahma", "name": "PAHMA"}, {"key": "bampfa", "name": "BAMPFA"}]


def test_with_several_museums_one_must_be_chosen_and_be_one_of_them(api, museums):
    assert sign_in(api).json()["detail"] == {"code": "tenant", "message": "Choose your museum."}
    r = sign_in(api, "ucjeps")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "tenant"
    assert api.get("/api/me").status_code == 401  # no session was started
    r = sign_in(api, "bampfa")
    assert r.status_code == 200 and r.json()["tenant"]["key"] == "bampfa"
    assert api.get("/api/me").json()["tenant"]["key"] == "bampfa"


def test_with_one_museum_none_needs_choosing(api):
    assert sign_in(api).json()["tenant"]["key"] == "pahma"


def test_a_session_whose_museum_the_deployment_no_longer_serves_ends(api, museums):
    sign_in(api, "bampfa")
    del museums.tenants["bampfa"]
    assert api.get("/api/me").status_code == 401


# ---- one museum's session sees and changes nothing of another's -----------------------------------------------------

def test_another_museums_jobs_are_invisible_and_untouchable(museums, add_uploaded):
    pahma, bampfa = client(museums), client(museums)
    sign_in(pahma, "pahma")
    sign_in(bampfa, "bampfa")
    job = new_job(pahma)
    n = add_uploaded(job, ["15-1234_1.jpg"], api=pahma)[0]["n"]
    assert job in {j["id"] for j in pahma.get("/api/jobs").json()["jobs"]}
    assert job not in {j["id"] for j in bampfa.get("/api/jobs").json()["jobs"]}
    attempts = [
        ("get", f"/api/jobs/{job}", None), ("post", f"/api/jobs/{job}/open", {}), ("patch", f"/api/jobs/{job}", {"name": "x"}),
        ("post", f"/api/jobs/{job}/files", {"files": [{"name": "1-1.jpg", "size": 3, "type": "image/jpeg"}]}),
        ("patch", f"/api/jobs/{job}/rows/{n}", {"handling": "create"}), ("post", f"/api/jobs/{job}/rows/{n}/upload-form", {"size": 3, "type": "image/jpeg"}),
        ("get", f"/api/jobs/{job}/rows/{n}/thumbnail", None), ("post", f"/api/jobs/{job}/check", {}),
        ("post", f"/api/jobs/{job}/schedule", {}), ("delete", f"/api/jobs/{job}/rows/{n}", None), ("delete", f"/api/jobs/{job}", None),
    ]
    for method, url, body in attempts:
        r = getattr(bampfa, method)(url, **({"json": body} if body is not None else {}))
        assert r.status_code in (403, 404), (method, url, r.status_code, r.text)
        assert "15-1234" not in r.text, (method, url)
    assert pahma.get(f"/api/jobs/{job}").status_code == 200  # still there, unchanged
    assert pahma.get(f"/api/jobs/{job}").json()["rows"][0]["handling"] != "create"


def test_no_job_endpoint_lets_another_museum_in(museums, add_uploaded):
    """Every route with a job in its address, with every method, refuses a session of another museum, and its
    answer shows nothing of the job. (A body the route can't accept is refused before the route runs, which is a
    refusal too.)"""
    pahma, bampfa = client(museums), client(museums)
    sign_in(pahma, "pahma")
    sign_in(bampfa, "bampfa")
    job = new_job(pahma, name="Secret museum job")
    n = add_uploaded(job, ["15-1234_1.jpg"], api=pahma)[0]["n"]
    before = pahma.get(f"/api/jobs/{job}").json()
    routes = [(r.path, m) for r in pahma.app.routes if "{job_id}" in getattr(r, "path", "") for m in r.methods]
    assert len(routes) >= 30, routes
    for path, method in routes:
        url = path.replace("{job_id}", job).replace("{n}", str(n))
        r = bampfa.request(method, url, json={})
        assert not 200 <= r.status_code < 300, (method, path, r.status_code)
        assert "Secret museum job" not in r.text and "15-1234" not in r.text, (method, path)
    after = pahma.get(f"/api/jobs/{job}").json()
    assert after["job"]["name"] == before["job"]["name"] and len(after["rows"]) == len(before["rows"])


def test_a_jobs_files_go_under_its_museum_with_its_museums_key(museums, add_uploaded):
    museums.settings.s3_kms_key_ids = {"pahma": "key-pahma", "bampfa": "key-bampfa"}
    bampfa = client(museums)
    sign_in(bampfa, "bampfa")
    job = new_job(bampfa)
    r = bampfa.post(f"/api/jobs/{job}/files", json={"files": [{"name": "15-1234_1.jpg", "size": 3, "type": "image/jpeg"}]})
    row = r.json()["rows"][0]
    assert row["s3Key"].startswith(f"staging/bampfa/{job}/")
    assert row["uploadForm"]["fields"]["x-amz-server-side-encryption-aws-kms-key-id"] == "key-bampfa"
    assert museums.storage._kms_key(f"audit/pahma/{job}/run-001.json") == "key-pahma"
    with pytest.raises(ValueError):
        museums.storage._kms_key("elsewhere/x")  # nothing is written outside a museum's prefixes


def test_a_saved_password_is_only_decrypted_for_its_own_museum(museums):
    token = museums.crypto.encrypt("session", "secret", session_context("admin", "k1", "pahma"))
    assert museums.crypto.decrypt("session", token, session_context("admin", "k1", "pahma")) == "secret"
    with pytest.raises(InvalidTag):
        museums.crypto.decrypt("session", token, session_context("admin", "k1", "bampfa"))
    token = museums.crypto.encrypt("job", "secret", job_context("admin", "j1", "pahma"))
    with pytest.raises(InvalidTag):
        museums.crypto.decrypt("job", token, job_context("admin", "j1", "bampfa"))


# ---- the worker: one per museum ---------------------------------------------------------------------------------------

def test_each_museums_worker_runs_only_its_own_museums_jobs(museums, add_uploaded):
    pahma, bampfa = client(museums), client(museums)
    sign_in(pahma, "pahma")
    sign_in(bampfa, "bampfa")
    jobs = {}
    for name, c in (("pahma", pahma), ("bampfa", bampfa)):
        jobs[name] = new_job(c)
        add_uploaded(jobs[name], ["15-1234_1.jpg"], api=c)
        assert c.post(f"/api/jobs/{jobs[name]}/schedule").status_code == 200, name
    w = Worker(museums.settings, museums.storage, museums.crypto, worker_factory, tenant=museums.tenants["bampfa"])
    assert w.tick()
    assert bampfa.get(f"/api/jobs/{jobs['bampfa']}").json()["job"]["status"] == "Completed"
    assert pahma.get(f"/api/jobs/{jobs['pahma']}").json()["job"]["status"] == "Queued"  # pahma's own worker runs it
    w = Worker(museums.settings, museums.storage, museums.crypto, worker_factory, tenant=museums.tenants["pahma"])
    assert w.tick()
    assert pahma.get(f"/api/jobs/{jobs['pahma']}").json()["job"]["status"] == "Completed"


def test_a_worker_by_default_serves_the_deployments_first_museum(services):
    assert Worker(services.settings, services.storage, services.crypto, worker_factory).tenant.key == "pahma"


# ---- one read-only account per museum ---------------------------------------------------------------------------------

def test_each_museum_has_its_own_read_only_account(services, monkeypatch):
    import bmu.app
    pahma = services.tenants["pahma"]
    monkeypatch.setattr(bmu.app, "load_tenant", lambda key: dataclasses.replace(pahma, key=key))
    settings = services.settings.model_copy(update={
        "tenants": {"pahma": "https://pahma.example", "ucjeps": "https://ucjeps.example"},
        "reader_secret_ids": {"pahma": "bmu-dev/cspace-reader/pahma", "ucjeps": "bmu-dev/cspace-reader/ucjeps"}})
    s = Services(settings, services.storage, services.crypto, factory)
    assert list(s.tenants) == ["pahma", "ucjeps"]
    assert {k: r.secret_id for k, r in s.readers.items()} == settings.reader_secret_ids
