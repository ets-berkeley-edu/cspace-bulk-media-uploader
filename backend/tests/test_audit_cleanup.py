"""Decisions of October 3 (design: Status): the run's audit entry carries its start and end times, and a deleted staged
file is gone at once, every version of it."""
from botocore.exceptions import ClientError

from test_finished import new_job, run_once


def _versions(services, key):
    r = services.storage.s3.list_object_versions(Bucket=services.settings.s3_bucket, Prefix=key)
    return r.get("Versions", []) + r.get("DeleteMarkers", [])


def test_the_run_audit_entry_has_the_runs_start_and_end(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    j = run_once(api, job, worker)
    run = j["runs"][0]
    entry = next(a for a in services.storage.list_audit("pahma") if a["type"] == "Run" and a["job"] == job)
    assert entry["startedAt"] == run["startedAt"] and entry["endedAt"] == run["endedAt"]
    assert entry["startedAt"] <= entry["endedAt"]


def test_a_staged_file_is_gone_for_good_once_its_upload_succeeds(api, login, add_uploaded, worker, services):
    login()
    job = new_job(api)
    rows = add_uploaded(job, ["15-1234_1.jpg"])
    key = rows[0]["s3Key"]
    assert _versions(services, key)  # the bucket keeps versions
    j = run_once(api, job, worker)
    assert j["rows"][0]["result"]["state"] == "Done"
    assert _versions(services, key) == []  # no hidden version and no delete marker left behind


def test_deleting_removes_every_version_and_marker(services):
    s3, bucket, key = services.storage.s3, services.settings.s3_bucket, "staging/pahma/job/00001/abc"
    s3.put_object(Bucket=bucket, Key=key, Body=b"one")
    s3.put_object(Bucket=bucket, Key=key, Body=b"two")
    s3.put_object(Bucket=bucket, Key=key + "-other", Body=b"a different object with the same prefix")
    s3.delete_object(Bucket=bucket, Key=key)  # a plain delete: a marker on top of two versions
    assert len(_versions(services, key + "x")) == 0 and len([v for v in _versions(services, key) if v["Key"] == key]) == 3
    services.storage.delete_object(key)
    assert [v["Key"] for v in _versions(services, key)] == [key + "-other"]
    services.storage.delete_object(key)  # already gone: nothing to do, no error


def test_deleting_falls_back_to_a_plain_delete_when_versions_cannot_be_listed(services, monkeypatch):
    s3, bucket, key = services.storage.s3, services.settings.s3_bucket, "staging/pahma/job/00002/abc"
    s3.put_object(Bucket=bucket, Key=key, Body=b"one")

    def denied(name):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListObjectVersions")
    monkeypatch.setattr(s3, "get_paginator", denied)
    services.storage.delete_object(key)
    assert services.storage.head_object(key) is None  # hidden; the lifecycle rule removes the old version


def test_deleting_several_objects_removes_every_version_of_those_only(services):
    s3, bucket = services.storage.s3, services.settings.s3_bucket
    keys = [f"staging/pahma/jobx/{n:05d}/file{n}" for n in range(1, 7)]
    for key in keys:
        s3.put_object(Bucket=bucket, Key=key, Body=b"one")
    s3.put_object(Bucket=bucket, Key=keys[0], Body=b"two")  # a second version
    s3.delete_object(Bucket=bucket, Key=keys[1])            # a delete marker on top of a version
    services.storage.delete_objects(keys[:5] + [None, "", "staging/pahma/jobx/00009/never-uploaded"])
    assert [v["Key"] for v in _versions(services, "staging/pahma/jobx/")] == [keys[5]]


def test_deleting_several_objects_falls_back_to_one_by_one(services, monkeypatch):
    s3, bucket = services.storage.s3, services.settings.s3_bucket
    keys = [f"staging/pahma/joby/{n:05d}/file{n}" for n in range(1, 6)]
    for key in keys:
        s3.put_object(Bucket=bucket, Key=key, Body=b"one")

    def denied(name):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListObjectVersions")
    monkeypatch.setattr(s3, "get_paginator", denied)
    services.storage.delete_objects(keys)
    assert all(services.storage.head_object(key) is None for key in keys)
