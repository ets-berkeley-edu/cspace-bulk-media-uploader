"""Uploads that finish together: a file that reached S3 is never marked failed because of a race between saves
(design: Browser uploads). moto runs every transaction alone, so the conflicts real DynamoDB reports
(TransactionConflict) are simulated here."""
import pytest
from botocore.exceptions import ClientError

from bmu import storage as storage_module

CONTENT = b"\xff\xd8\xff\xe0 fake JPEG bytes"


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(storage_module.time, "sleep", lambda s: None)


def staged(api, services, names):
    """A draft with these files added and sent to S3, not yet confirmed with /uploaded."""
    job = api.post("/api/jobs", json={"name": "Races"}).json()["id"]
    r = api.post(f"/api/jobs/{job}/files", json={"files": [{"name": n, "size": len(CONTENT), "type": "image/jpeg"} for n in names]})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    for row in rows:
        services.storage.s3.put_object(Bucket=services.settings.s3_bucket, Key=row["s3Key"], Body=CONTENT)
    return job, rows


def cancel_row_puts(monkeypatch, services, n, reasons, times):
    """DynamoDB cancels the next `times` transactions that save row n, with these cancellation reasons."""
    client = services.storage.dynamodb.meta.client
    real = client.transact_write_items
    seen = []

    def cancelled(TransactItems, **kw):
        sk = TransactItems[0].get("Put", {}).get("Item", {}).get("SK")
        if sk == f"ROW#{n:05d}" and len(seen) < times:
            seen.append(sk)
            raise ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
                               "CancellationReasons": [{"Code": c} for c in reasons]}, "TransactWriteItems")
        return real(TransactItems=TransactItems, **kw)
    monkeypatch.setattr(client, "transact_write_items", cancelled)
    return seen


def test_a_transaction_conflict_is_tried_again(api, login, services, monkeypatch):
    """Seen on real DynamoDB: three files added at once, and one /uploaded answered 409 while the others were saved,
    so the page marked a file that was in S3 "Upload failed"."""
    login()
    job, rows = staged(api, services, ["15-1234_1.jpg", "15-1234_2.jpg", "15-1234_3.jpg"])
    n = rows[0]["n"]
    seen = cancel_row_puts(monkeypatch, services, n, ["None", "TransactionConflict"], times=2)
    r = api.post(f"/api/jobs/{job}/rows/{n}/uploaded")
    assert r.status_code == 200, r.text
    assert len(seen) == 2
    assert r.json()["row"]["upload"]["s"] == "done"
    assert services.storage.get_row(job, n)["upload"]["s"] == "done"
    for row in rows[1:]:
        assert api.post(f"/api/jobs/{job}/rows/{row['n']}/uploaded").json()["row"]["upload"]["s"] == "done"


def test_a_row_saved_meanwhile_is_read_again(api, login, services, monkeypatch):
    """Another save of the document lands between /uploaded's read and its write: the row is read again, so the
    upload is recorded and the other save is kept."""
    login()
    job, rows = staged(api, services, ["15-1234_1.jpg"])
    n = rows[0]["n"]
    real = services.storage.head_object
    calls = []

    def head_then_save(key):
        if not calls:
            other = services.storage.get_row(job, n)
            other["description"] = "saved meanwhile"
            services.storage.put_row(job, other)
        calls.append(key)
        return real(key)
    monkeypatch.setattr(services.storage, "head_object", head_then_save)
    r = api.post(f"/api/jobs/{job}/rows/{n}/uploaded")
    assert r.status_code == 200, r.text
    assert len(calls) == 2
    row = services.storage.get_row(job, n)
    assert row["upload"]["s"] == "done" and row["description"] == "saved meanwhile"


def test_a_conflict_that_never_clears_still_answers_409(api, login, services, monkeypatch):
    """The retries are bounded: a conflict on every try is still a 409 (the page then shows Retry), never a hang."""
    login()
    job, rows = staged(api, services, ["15-1234_1.jpg"])
    n = rows[0]["n"]
    seen = cancel_row_puts(monkeypatch, services, n, ["TransactionConflict", "None"], times=1000)
    r = api.post(f"/api/jobs/{job}/rows/{n}/uploaded")
    assert r.status_code == 409
    from bmu.app import UPLOADED_ATTEMPTS
    assert len(seen) == UPLOADED_ATTEMPTS * storage_module.TRANSACTION_ATTEMPTS
    assert services.storage.get_row(job, n)["upload"]["s"] == "pending"


def test_a_job_no_longer_being_edited_is_not_tried_again(api, login, services, monkeypatch):
    """A failed check on the job item (taken over, submitted) is not a conflict: answered at once, not retried."""
    login()
    job, rows = staged(api, services, ["15-1234_1.jpg"])
    n = rows[0]["n"]
    seen = cancel_row_puts(monkeypatch, services, n, ["None", "ConditionalCheckFailed"], times=1000)
    r = api.post(f"/api/jobs/{job}/rows/{n}/uploaded")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_editing"
    assert len(seen) == 1
