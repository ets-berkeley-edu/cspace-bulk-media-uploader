import base64
import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from bmu.app import Services, create_app
from bmu.config import Settings
from bmu.crypto import LocalCrypto
from bmu.cspace import CSpaceClient
from bmu.storage import Storage
from bmu.worker import Worker
from fakecspace.app import app as fake_app
from fakecspace.app import store as fake_store

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")


@pytest.fixture
def settings():
    return Settings(cspace_url="http://fake", aws_region="us-west-2", s3_bucket="bmu-test", table_prefix="t",
                    session_key_b64=base64.b64encode(b"s" * 32).decode(), job_key_b64=base64.b64encode(b"j" * 32).decode(),
                    cookie_secure=False, always_run_time=True, _env_file=None)
    # always_run_time: a queued job runs at the next worker.tick(), as most tests expect. The scheduling tests
    # (test_scheduling.py) turn it off and move an injected clock (design: Job scheduling).


@pytest.fixture
def fake():
    fake_store.reset()
    return fake_store


def factory(user, password):
    return CSpaceClient("http://fake", user, password, http=TestClient(fake_app, base_url="http://fake"))


def worker_factory(user, password):
    return CSpaceClient("http://fake", user, password, http=TestClient(fake_app, base_url="http://fake"), agent="bmu-worker")


@pytest.fixture
def fail_on(fake):
    """Add a /_fake/fail rule: e.g. fail_on("upload", status=413, match="1-2345")."""
    c = TestClient(fake_app, base_url="http://fake")

    def _add(step, **params):
        r = c.post("/_fake/fail", params={"step": step, **params})
        assert r.status_code == 200, r.text
        return r.json()["rules"]
    return _add


@pytest.fixture
def aws():
    with mock_aws():
        yield


@pytest.fixture
def services(settings, aws, fake):
    storage = Storage(settings, dynamodb=boto3.resource("dynamodb", region_name="us-west-2"),
                      s3=boto3.client("s3", region_name="us-west-2"), s3_public=boto3.client("s3", region_name="us-west-2"))
    storage.create_tables()
    crypto = LocalCrypto({"session": b"s" * 32, "job": b"j" * 32})
    return Services(settings, storage, crypto, factory)


@pytest.fixture
def api(services):
    c = TestClient(create_app(services), base_url="http://testserver")
    c.headers["X-BMU"] = "1"
    return c


@pytest.fixture
def worker(services):
    return Worker(services.settings, services.storage, services.crypto, worker_factory)


@pytest.fixture
def login(api):
    def _login(user="admin", pw=None):
        r = api.post("/api/login", json={"username": user, "password": pw or user})
        assert r.status_code == 200, r.text
        return r.json()
    return _login


@pytest.fixture
def add_uploaded(api, services):
    """Add files to a job and simulate the browser's direct upload to S3."""
    def _add(job_id, names, content=b"\xff\xd8\xff\xe0 fake JPEG bytes", api=api):
        r = api.post(f"/api/jobs/{job_id}/files",
                     json={"files": [{"name": n, "size": len(content), "type": "image/jpeg"} for n in names]})
        assert r.status_code == 200, r.text
        rows = r.json()["rows"]
        for row in rows:
            assert "uploadForm" in row and row["uploadForm"]["fields"]["key"] == row["s3Key"]
            services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=row["s3Key"], Body=content)
            u = api.post(f"/api/jobs/{job_id}/rows/{row['n']}/uploaded")
            assert u.json()["row"]["upload"]["s"] == "done"
        return rows
    return _add
