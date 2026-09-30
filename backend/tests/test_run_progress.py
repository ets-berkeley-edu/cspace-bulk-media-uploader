"""The running job's progress for the Job queue (design: The job queue): the document and step in progress, and
while a document's file is sent to CollectionSpace, the bytes sent so far."""
import io

from bmu import worker as worker_mod
from bmu.worker import _UploadProgress


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_upload_progress_counts_bytes_and_reports_at_most_every_two_seconds_and_at_the_end():
    clock, reports = Clock(), []
    up = _UploadProgress(io.BytesIO(b"x" * 1000), 1000, lambda s, t: reports.append((s, t)), clock=clock)
    assert up.read(100) == b"x" * 100 and reports == []  # too soon
    clock.t = 2.5
    up.read(100)
    assert reports == [(200, 1000)]
    clock.t = 3.0
    up.read(100)
    assert reports == [(200, 1000)]  # within two seconds of the last report
    up.read()  # the rest: the end is always reported
    assert reports[-1] == (1000, 1000) and up.sent == 1000
    up.read(10)
    assert len(reports) == 2  # the end is reported once


def test_a_failing_progress_report_never_stops_the_upload():
    def boom(sent, total):
        raise RuntimeError("DynamoDB unavailable")
    up = _UploadProgress(io.BytesIO(b"abc"), 3, boom)
    assert up.read() == b"abc"


def test_upload_progress_adds_no_seek_or_fileno():
    """httpx sends the stream the same way as before: it can't find the length by seeking."""
    up = _UploadProgress(io.BytesIO(b"abc"), 3, lambda s, t: None)
    assert not hasattr(up, "seek") and not hasattr(up, "fileno")


def test_a_run_records_the_step_and_upload_in_progress_and_clears_them_at_the_end(
        api, login, add_uploaded, worker, services, monkeypatch):
    login()
    job = api.post("/api/jobs", json={"name": "Progress"}).json()["id"]
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly"})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    monkeypatch.setattr(worker_mod, "UPLOAD_PROGRESS_SECONDS", 0.0)
    seen = []
    orig = services.storage.update_job

    def spy(job_id, fields, *a, **kw):
        if job_id == job and ("currentStep" in fields or "currentUpload" in fields):
            seen.append({k: fields[k] for k in ("currentStep", "currentUpload") if k in fields})
        return orig(job_id, fields, *a, **kw)
    monkeypatch.setattr(services.storage, "update_job", spy)
    assert worker.tick() is True
    steps = [s["currentStep"] for s in seen if s.get("currentStep")]
    assert steps[:3] == ["values", "media", "upload"]
    uploads = [s["currentUpload"] for s in seen if s.get("currentUpload")]
    assert uploads and uploads[-1]["sent"] == uploads[-1]["total"] > 0
    j = api.get(f"/api/jobs/{job}").json()["job"]
    assert j["status"] == "Completed" and not j.get("currentStep") and not j.get("currentUpload")


def test_the_simulator_can_receive_file_uploads_slowly(fake):
    """/_fake/slow?upload_mbps=N reads a file upload at about N MB/s, to watch the upload bar (development only)."""
    import time
    from fastapi.testclient import TestClient
    from fakecspace.app import app as fake_app
    c = TestClient(fake_app, base_url="http://fake")
    assert c.post("/_fake/slow", params={"seconds": 0, "upload_mbps": 2}).json() == {"delay": 0.0, "upload_mbps": 2.0}
    t = time.monotonic()
    c.put("/cspace-services/media/none/blob", files={"file": ("a.jpg", b"x" * (1024 * 1024), "image/jpeg")},
          auth=("admin", "admin"))
    assert time.monotonic() - t >= 0.4  # 1 MB at 2 MB/s
    c.post("/_fake/reset")
    assert fake.upload_mbps == 0.0
