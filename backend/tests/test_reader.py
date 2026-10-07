"""The read-only service account that checks an intern's drafts (design: Roles; bmu/reader.py)."""
import json
import logging

import boto3
import pytest

from bmu.reader import PROTECTED_REASON, Reader, ReaderLimit, ReaderUnavailable, minimal
from test_flow import _second_user, new_job

FILE = {"name": "15-1234_1.jpg", "size": 3, "type": "image/jpeg"}


@pytest.fixture
def reader(services):
    """The simulator's reader account, set up as it is in the local stack."""
    services.settings.reader_user, services.settings.reader_password = "bmureader", "bmureader"
    return services.readers["pahma"]


def _blocks(row):
    return [c["text"] for c in row["checks"] if c["level"] == "block"]


def _intern_draft(services, add_uploaded, names):
    """A draft an intern made, with uploaded files (the intern's session adds them)."""
    intern = _second_user(services, "intern")
    job = intern.post("/api/jobs", json={"name": "Intern's"}).json()["id"]
    add_uploaded(job, names, api=intern)
    return intern, job


# ---- an intern's checks run with the reader account ---------------------------------------------------------------
def test_without_a_reader_account_an_interns_documents_are_checked_with_their_own_account(services, add_uploaded):
    intern, job = _intern_draft(services, add_uploaded, ["15-1234_1.jpg"])
    texts = _blocks(intern.post(f"/api/jobs/{job}/check").json()["rows"][0])
    assert any("can't read Object records" in t for t in texts) and any("can't read Media records" in t for t in texts)


def test_with_the_reader_account_an_interns_documents_are_really_checked(services, add_uploaded, reader, fake):
    intern, job = _intern_draft(services, add_uploaded, ["15-1234_1.jpg", "20-0777_1.jpg"])
    rows = {r["file"]: r for r in intern.post(f"/api/jobs/{job}/check").json()["rows"]}
    found, missing = rows["15-1234_1.jpg"], rows["20-0777_1.jpg"]
    assert not any("can't read" in t for r in rows.values() for t in _blocks(r))
    assert any("No object 20-0777 in CollectionSpace" in t for t in _blocks(missing))  # a real problem, found for the intern
    assert not any("No object" in t for t in _blocks(found))
    # the Media record that already has this number is reported, but not which record it is
    exists = [c["text"] for c in found["checks"] if "already exists" in c["text"]]
    assert exists == ["A Media record with ID 15-1234 already exists in CollectionSpace."]
    assert "CSID" not in json.dumps(found) and not any(found["lookups"]["media"]["csids"])
    assert "(CSID " in json.dumps(services.storage.get_row(job, found["n"])["checks"])  # staff still get it
    # nothing is held against the intern's own account: the intern acts for whoever submits (design: Roles)
    assert _blocks(found) == []
    # the lookups were the reader account's, not the intern's
    assert {c["user"] for c in fake.calls if "collectionobjects" in c["path"]} == {"bmureader"}


def test_autocomplete_vocabularies_and_dates_use_the_reader_account_for_an_intern(services, reader, login, api):
    intern = _second_user(services, "intern")
    r = intern.get("/api/authorities", params={"field": "creator", "q": "hearst"}).json()
    assert [t["displayName"] for t in r["terms"]] == ["Phoebe A. Hearst Museum of Anthropology"]
    assert len(intern.get("/api/vocabularies/languages").json()["terms"]) == 8
    assert intern.get("/api/dates/parse", params={"text": "1920s"}).json()["ok"] is True
    login()  # staff keep using their own sign-in
    assert api.get("/api/authorities", params={"field": "creator", "q": "hearst"}).status_code == 200


def test_staff_never_use_the_reader_account(api, login, add_uploaded, reader, fake):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_1.jpg"])
    assert api.post(f"/api/jobs/{job}/check").status_code == 200
    assert "bmureader" not in {c["user"] for c in fake.calls}


def test_a_protected_file_is_found_for_an_intern_but_not_why(services, add_uploaded, reader, login, api):
    intern, job = _intern_draft(services, add_uploaded, ["12-2001_1.jpg"])  # a culturally sensitive object
    row = intern.post(f"/api/jobs/{job}/check").json()["rows"][0]
    assert row["protected"] == {"reason": PROTECTED_REASON, "hides": True}
    text = json.dumps(row)
    assert "Human Remains" not in text and "culturally" not in text
    assert any(c["text"].startswith(f"Protected file: {PROTECTED_REASON}.") for c in row["checks"])
    assert "objectSensitivity" not in row["lookups"] and row["lookups"]["object"]["csids"] == [""]  # found, not which
    assert intern.get(f"/api/jobs/{job}").json()["rows"][0]["protected"]["reason"] == PROTECTED_REASON
    assert services.storage.get_row(job, 1).get("thumbKey") is None  # protected: no thumbnail is kept
    # what is stored is complete, and staff see it
    assert "Human Remains" in services.storage.get_row(job, 1)["protected"]["reason"]
    intern.post(f"/api/jobs/{job}/close")
    login()
    assert "Human Remains" in api.get(f"/api/jobs/{job}").json()["rows"][0]["protected"]["reason"]


def test_minimal_cuts_rows_wherever_they_are_in_an_answer():
    row = {"n": 1, "checks": [{"level": "warn", "text": "Object 1-2 has a loan restriction, a note. Consider checking Restricted."}],
           "protected": None, "softSignals": ["a loan restriction", "a note"],
           "lookups": {"object": {"value": "1-2", "csids": ["abc", "def"]}, "objectSensitivity": {"protect": ["x"]}, "date": {"value": "1920s", "ok": True}}}
    out = minimal({"job": {"name": "n"}, "rows": [row], "others": {"row": {"n": 2, "checks": [], "protected": {"reason": "secret", "hides": False}}}})
    r = out["rows"][0]
    assert r["checks"][0]["text"] == "Object 1-2 has a note about access in CollectionSpace. Consider checking Restricted."
    assert r["softSignals"] == ["a note about access in CollectionSpace"]
    assert r["lookups"] == {"object": {"value": "1-2", "csids": ["", ""]}, "date": {"value": "1920s", "ok": True}}
    assert out["others"]["row"]["protected"]["reason"] == PROTECTED_REASON and out["job"] == {"name": "n"}


# ---- when the reader account can't be used --------------------------------------------------------------------------
def test_a_refused_reader_account_is_reported_as_the_bmus_problem_not_the_interns_sign_in(services, add_uploaded, reader, fake):
    intern, job = _intern_draft(services, add_uploaded, ["15-1234_1.jpg"])
    services.settings.reader_password = "wrong"
    reader.forget()
    r = intern.post(f"/api/jobs/{job}/check")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "reader"
    assert "CollectionSpace refused its sign-in" in r.json()["detail"]["message"]
    assert intern.get("/api/me").status_code == 200  # the intern is still signed in
    assert intern.get("/api/authorities", params={"field": "creator", "q": "hearst"}).status_code == 503


def test_each_interns_lookups_are_counted_logged_and_limited(services, add_uploaded, reader, caplog):
    with caplog.at_level(logging.INFO, logger="bmu.reader"):
        intern, job = _intern_draft(services, add_uploaded, ["15-1234_1.jpg"])  # checked as it is added
    assert any(m.startswith("reader: intern made ") and f"(checking job {job})" in m for m in caplog.messages)
    assert reader._used["intern"][1] > 0
    services.settings.reader_lookups_per_hour = reader._used["intern"][1]  # no more are allowed this hour
    r = intern.get("/api/authorities", params={"field": "creator", "q": "hearst"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "reader_limit"
    assert "within the hour" in r.json()["detail"]["message"]


def test_the_limit_is_each_interns_own_and_starts_again_after_an_hour(settings):
    t = [1000.0]
    settings.reader_user, settings.reader_password, settings.reader_lookups_per_hour = "u", "p", 2
    r = Reader(settings, lambda u, p: None, clock=lambda: t[0])
    r._count("kim"); r._count("kim")
    with pytest.raises(ReaderLimit):
        r._count("kim")
    r._count("lee")  # another intern is not affected
    t[0] += 3600
    r._count("kim")


def test_an_interns_use_reaches_the_log_even_when_logging_was_not_configured(capsys):
    """Under uvicorn the root logger has no handler, and INFO would be dropped."""
    from bmu import reader as mod
    root = logging.getLogger()
    kept, level, own = root.handlers[:], mod.log.level, mod.log.handlers[:]
    root.handlers[:] = []
    try:
        mod.ensure_logged()
        mod.ensure_logged()  # twice adds one handler
        assert len(mod.log.handlers) == 1
        mod.log.info("reader: %s made %d lookups (%s)", "kim", 3, "checking job j1")
    finally:
        root.handlers[:] = kept
        mod.log.handlers[:] = own
        mod.log.setLevel(level)
    assert "bmu.reader: reader: kim made 3 lookups (checking job j1)" in capsys.readouterr().err


# ---- where its sign-in comes from -----------------------------------------------------------------------------------
def test_in_aws_the_sign_in_comes_from_secrets_manager_and_is_kept_only_in_memory(settings, aws, caplog):
    sm = boto3.client("secretsmanager", region_name=settings.aws_region)
    sm.create_secret(Name="bmu-dev/cspace-reader", SecretString=json.dumps({"username": "svc", "password": "s3cret"}))
    settings.reader_secret_id = "bmu-dev/cspace-reader"
    t = [0.0]
    r = Reader(settings, lambda u, p: None, clock=lambda: t[0])
    assert r.configured and r.credentials() == ("svc", "s3cret")
    sm.put_secret_value(SecretId="bmu-dev/cspace-reader", SecretString=json.dumps({"username": "svc", "password": "changed"}))
    assert r.credentials() == ("svc", "s3cret")  # kept for a few minutes
    t[0] += settings.reader_cache_seconds + 1
    assert r.credentials() == ("svc", "changed")  # a changed password takes effect without a restart
    settings.reader_secret_id = "bmu-dev/missing"
    r.forget()
    with caplog.at_level(logging.ERROR, logger="bmu.reader"), pytest.raises(ReaderUnavailable):
        r.credentials()
    assert "s3cret" not in caplog.text and "changed" not in caplog.text


def test_a_secret_without_a_password_yet_is_not_usable(settings):
    settings.reader_secret_id = "x"
    for text in ['{"username": "svc", "password": ""}', "not json", '{"user": "svc"}']:
        with pytest.raises(ReaderUnavailable):
            Reader(settings, lambda u, p: None, fetch_secret=lambda _id: text).credentials()


def test_not_set_up_means_not_configured(settings):
    assert Reader(settings, lambda u, p: None).configured is False
    settings.reader_user = "bmureader"  # a user name alone is not enough
    assert Reader(settings, lambda u, p: None).configured is False
