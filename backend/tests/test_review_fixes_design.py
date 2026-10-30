"""Code fixes from section 7 of the 29 October 2026 review (the design document's inconsistencies)."""
import io

from PIL import Image

from bmu.storage import now
from test_finished import by_file, new_job, run_once
from test_flow import _second_user


def _jpeg():
    b = io.BytesIO()
    Image.new("RGB", (60, 40), "red").save(b, "JPEG")
    return b.getvalue()


def test_an_intern_never_sees_the_images_of_a_staff_only_job(api, login, add_uploaded, services):
    """7.5: thumbnails need the role and intern-access check, not only the session and museum."""
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    assert api.post(f"/api/jobs/{job}/rows/{n}/thumbnail", content=_jpeg()).json() == {"stored": True}
    intern = _second_user(services, "intern")
    assert intern.get(f"/api/jobs/{job}/rows/{n}/thumbnail").status_code == 404
    assert api.post(f"/api/jobs/{job}/intern-access", json={"open": True}).status_code == 200
    assert intern.get(f"/api/jobs/{job}/rows/{n}/thumbnail").status_code == 200


def test_a_reverted_fix_never_points_a_row_at_a_staged_file_that_is_gone(api, login, add_uploaded, worker, services, fail_on):
    """7.4: a row restored by the revert whose staged file was removed during the fix shows its upload as failed."""
    login()
    job = new_job(api)
    add_uploaded(job, ["12-5678_1.jpg"])
    fail_on("media", status=400, match="12-5678")
    run_once(api, job, worker)
    api.post(f"/api/jobs/{job}/fix")
    api.patch(f"/api/jobs/{job}/rows/1", json={"description": "changed while fixing"})
    services.storage.delete_object(services.storage.get_row(job, 1)["s3Key"])  # e.g. removed by a retried upload
    services.storage.update_job(job, {"draftExpiresAt": now() - 1})
    assert worker.sweep_expired_drafts() == [job]
    row = by_file(api.get(f"/api/jobs/{job}").json())["12-5678_1.jpg"]
    assert row["description"] == "" and row["upload"] == {"s": "failed", "reason": "missing"}


def test_run_progress_comes_from_running_totals_not_a_read_of_every_row(api, login, add_uploaded, worker, services, monkeypatch):
    """7.13: about one read of the rows per run, not one per document."""
    login()
    job = new_job(api)
    add_uploaded(job, [f"20-0501_{i}.jpg" for i in range(6)])
    for n in range(1, 7):
        api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly"})
    reads = []
    real = services.storage.get_rows
    monkeypatch.setattr(services.storage, "get_rows", lambda jid: reads.append(jid) or real(jid))
    j = run_once(api, job, worker)
    assert j["job"]["status"] == "Completed" and j["job"]["progress"] == {"total": 6, "done": 6, "failed": 0}
    assert len(reads) < 12, len(reads)  # it was 6 + a few before
