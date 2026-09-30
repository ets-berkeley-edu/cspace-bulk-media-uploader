"""The worker checks rows' values again before creating their records (design: Job execution; Authority term fields):
once for the whole run before the first document, then just before each document, from lookups at most a minute old.
Terms deleted meanwhile fail only their document (value_missing, nothing created); renamed terms are sent with their
current name (term_renamed)."""
import dataclasses

import pytest

from bmu.rows import is_locked
from bmu.tenant import Option
from bmu.worker import VALUE_CHECK_SECONDS, Worker
from conftest import worker_factory

DOMAIN = "pahma.cspace.berkeley.edu"
LESLIE = f"urn:cspace:{DOMAIN}:personauthorities:name(person):item:name(7475)'Leslie Freund'"
LESLIE_RENAMED = LESLIE.replace("'Leslie Freund'", "'Leslie F. Freund'")
HEARST = (f"urn:cspace:{DOMAIN}:orgauthorities:name(organization):item:name(PhoebeAHearstMuseumofAnthropology1400000000000)"
          "'Phoebe A. Hearst Museum of Anthropology'")
HEARST_SHORT = "PhoebeAHearstMuseumofAnthropology1400000000000"
SPA = f"urn:cspace:{DOMAIN}:vocabularies:name(languages):item:name(spa)'Spanish'"
ENG = f"urn:cspace:{DOMAIN}:vocabularies:name(languages):item:name(eng)'English'"


class Clock:
    """The worker's lookup clock, moved by the tests."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def worker(services, clock):
    return Worker(services.settings, services.storage, services.crypto, worker_factory, lookup_clock=clock)


def make_job(api, add_uploaded, rows: dict[str, dict], name="Value checks"):
    """A job of media-only documents (filename -> field values), returned as (job id, {filename: n})."""
    job = api.post("/api/jobs", json={"name": name}).json()["id"]
    added = add_uploaded(job, list(rows))
    ns = {}
    for r in added:
        resp = api.patch(f"/api/jobs/{job}/rows/{r['n']}", json={"handling": "mediaonly", **rows[r["file"]]})
        assert resp.status_code == 200, resp.text
        ns[r["file"]] = r["n"]
    return job, ns


def schedule(api, job, fake):
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 200, r.text
    fake.term_reads.clear()


def run(api, job, worker):
    assert worker.tick() is True
    j = api.get(f"/api/jobs/{job}").json()
    return j, {r["file"]: r for r in j["rows"]}


def media_ids(fake):
    return sorted(m["identificationNumber"] for m in fake.media.values())


def after_each_row(worker, fn):
    """Call fn(n) after the worker finishes each document."""
    orig = worker.run_row

    def wrapped(client, job_id, row, run_no, created):
        try:
            return orig(client, job_id, row, run_no, created)
        finally:
            fn(row["n"])
    worker.run_row = wrapped


# ---- deleted terms ------------------------------------------------------------------------------------
@pytest.mark.parametrize("how,why", [("deleted", "deleted in CollectionSpace"), ("gone", "not found (404)")])
def test_a_term_deleted_after_submit_fails_only_its_document(api, login, add_uploaded, worker, fake, how, why):
    login()
    job, ns = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE}, "12-5678_1.jpg": {"contributor": HEARST}})
    schedule(api, job, fake)
    before = media_ids(fake)
    fake.term_states["7475"] = how
    j, rows = run(api, job, worker)
    bad, good = rows["15-1234_1.jpg"], rows["12-5678_1.jpg"]
    assert bad["result"]["state"] == "Failed"
    assert bad["result"]["error"] == {"code": "value_missing", "detail": f"Creator “Leslie Freund”: {why}", "step": "values"}
    steps = bad["result"]["steps"]
    assert steps["values"]["s"] == "failed" and steps["media"] == {"s": "skipped", "after": "values"}
    assert steps["upload"] == {"s": "skipped", "after": "media"}
    assert good["result"]["state"] == "Done" and good["result"]["steps"]["values"]["s"] == "done"
    # nothing was sent for the failed document: only the other one's Media record is new
    assert media_ids(fake) == sorted(before + ["12-5678_1"])
    assert j["job"]["status"] == "NeedsAttention" and j["job"]["code"] == ""
    assert j["job"]["counts"] == {"done": 1, "partial": 0, "failed": 1, "notStarted": 0, "disabled": 0}
    assert j["runs"][0]["counts"]["failed"] == 1
    # it created nothing, so it can be deleted, and every field can be fixed
    assert not is_locked(bad)
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    checked = api.post(f"/api/jobs/{job}/check", json={}).json()["rows"]
    blocks = [c["text"] for r in checked if r["n"] == ns["15-1234_1.jpg"] for c in r["checks"] if c["level"] == "block"]
    assert any("Creator “Leslie Freund” no longer exists in CollectionSpace" in t for t in blocks)
    r = api.patch(f"/api/jobs/{job}/rows/{ns['15-1234_1.jpg']}", json={"creator": ""})
    assert r.status_code == 200, r.text
    assert api.delete(f"/api/jobs/{job}/rows/{ns['15-1234_1.jpg']}").status_code == 200


def test_a_language_removed_after_submit_fails_its_document(api, login, add_uploaded, worker, fake):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"language": [ENG, SPA]}, "12-5678_1.jpg": {}})
    schedule(api, job, fake)
    fake.deleted_languages.add("spa")
    j, rows = run(api, job, worker)
    bad = rows["15-1234_1.jpg"]
    assert bad["result"]["error"] == {"code": "value_missing", "detail": "Language “Spanish”: not in the language list",
                                      "step": "values"}
    assert rows["12-5678_1.jpg"]["result"]["state"] == "Done" and "15-1234_1" not in media_ids(fake)
    assert j["job"]["status"] == "NeedsAttention"


def test_a_media_type_no_longer_in_the_tenant_list_fails_its_document(api, login, add_uploaded, services, fake):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"type": ["slide", "image"]}, "12-5678_1.jpg": {"type": ["image"]}})
    schedule(api, job, fake)
    # the tenant's list changed (a new deployment) after the job was submitted
    base = services.tenant
    tenant = dataclasses.replace(base, media_types=tuple(o for o in base.media_types if o.value != "slide"))
    assert isinstance(tenant.media_types[0], Option)
    w = Worker(services.settings, services.storage, services.crypto, worker_factory, tenant=tenant)
    j, rows = run(api, job, w)
    assert rows["15-1234_1.jpg"]["result"]["error"] == {
        "code": "value_missing", "detail": "Media type “slide”: not in PAHMA’s media types", "step": "values"}
    assert rows["12-5678_1.jpg"]["result"]["state"] == "Done"


def test_several_missing_values_are_all_named(api, login, add_uploaded, worker, fake):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE, "rightsHolder": HEARST, "language": [SPA]}})
    schedule(api, job, fake)
    fake.term_states.update({"7475": "deleted", HEARST_SHORT: "gone"})
    fake.deleted_languages.add("spa")
    _, rows = run(api, job, worker)
    assert rows["15-1234_1.jpg"]["result"]["error"]["detail"] == (
        "Creator “Leslie Freund”: deleted in CollectionSpace; Rights holder “Phoebe A. Hearst Museum of Anthropology”: "
        "not found (404); Language “Spanish”: not in the language list")


# ---- renamed terms ------------------------------------------------------------------------------------
def test_a_term_renamed_after_submit_is_sent_with_its_current_name(api, login, add_uploaded, worker, fake, services):
    login()
    job, ns = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE, "language": [SPA]}})
    schedule(api, job, fake)
    fake.term_renames["7475"] = "Leslie F. Freund"
    fake.language_renames["spa"] = "Español"
    j, rows = run(api, job, worker)
    row = rows["15-1234_1.jpg"]
    assert j["job"]["status"] == "Completed" and row["result"]["state"] == "Done"
    spa_now = SPA.replace("'Spanish'", "'Español'")
    xml = fake.media[row["result"]["steps"]["media"]["csid"]]["xml"]
    assert "Leslie F. Freund" in xml and "'Leslie Freund'" not in xml and "Español" in xml
    # the row holds what was sent
    stored = services.storage.get_row(job, ns["15-1234_1.jpg"])
    assert stored["creator"] == LESLIE_RENAMED and stored["language"] == [spa_now]
    assert row["result"]["notices"] == [
        {"code": "term_renamed", "detail": "Creator “Leslie Freund” → “Leslie F. Freund”"},
        {"code": "term_renamed", "detail": "Language “Spanish” → “Español”"}]


# ---- checked again before each document -------------------------------------------------------------------
def test_a_term_deleted_during_the_run_is_caught_before_the_next_document(api, login, add_uploaded, worker, fake, clock):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE}, "12-5678_1.jpg": {"creator": LESLIE},
                                          "15-1240_1.jpg": {"creator": LESLIE}})

    def between(n):
        if n == 1:  # deleted in CollectionSpace while the first document was running, a minute into the run
            fake.term_states["7475"] = "deleted"
            clock.t += VALUE_CHECK_SECONDS
    after_each_row(worker, between)
    schedule(api, job, fake)
    j, rows = run(api, job, worker)
    assert rows["15-1234_1.jpg"]["result"]["state"] == "Done"
    for f in ("12-5678_1.jpg", "15-1240_1.jpg"):
        assert rows[f]["result"]["error"]["code"] == "value_missing" and f.split(".")[0] not in media_ids(fake)
    assert j["job"]["status"] == "NeedsAttention"


def test_value_lookups_are_reused_for_a_minute(api, login, add_uploaded, worker, fake, clock):
    """One request per distinct term per minute, not one per document."""
    login()
    names = [f"15-1234_{i}.jpg" for i in range(1, 7)]
    job, _ = make_job(api, add_uploaded, {n: {"creator": LESLIE, "contributor": HEARST if i % 2 else ""}
                                         for i, n in enumerate(names)})
    after_each_row(worker, lambda n: setattr(clock, "t", clock.t + 25))  # each document takes 25 seconds
    schedule(api, job, fake)
    j, _ = run(api, job, worker)
    assert j["job"]["status"] == "Completed"
    # read before the first document (t=0), then again by the 4th document's check (t=75), cached otherwise
    assert sorted(fake.term_reads) == sorted(["7475", HEARST_SHORT] * 2)


def test_a_term_changed_within_the_minute_is_still_read_from_the_cache(api, login, add_uploaded, worker, fake, clock):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE}, "12-5678_1.jpg": {"creator": LESLIE}})
    after_each_row(worker, lambda n: fake.term_states.update({"7475": "deleted"}))  # clock unchanged
    schedule(api, job, fake)
    _, rows = run(api, job, worker)
    assert all(r["result"]["state"] == "Done" for r in rows.values()) and fake.term_reads == ["7475"]


# ---- lookups that fail -----------------------------------------------------------------------------------
def test_a_failed_lookup_fails_the_document_and_creates_nothing(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE}, "12-5678_1.jpg": {}})
    schedule(api, job, fake)
    fail_on("termRead", status=503, match="7475", count=2)  # the check before the run and the document's own check
    j, rows = run(api, job, worker)
    bad = rows["15-1234_1.jpg"]
    assert bad["result"]["state"] == "Failed" and bad["result"]["error"]["code"] == "server_error"
    assert bad["result"]["error"]["step"] == "values" and "503" in bad["result"]["error"]["detail"]
    assert bad["result"]["steps"]["media"] == {"s": "skipped", "after": "values"} and "15-1234_1" not in media_ids(fake)
    assert rows["12-5678_1.jpg"]["result"]["state"] == "Done"
    assert j["job"]["status"] == "NeedsAttention" and j["job"]["code"] == ""


def test_a_lookup_that_failed_before_the_run_is_asked_again(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE}})
    schedule(api, job, fake)
    fail_on("termRead", status=500, count=1)
    j, rows = run(api, job, worker)
    assert j["job"]["status"] == "Completed" and fake.term_reads == ["7475", "7475"]


def test_failing_lookups_count_toward_five_in_a_row(api, login, add_uploaded, worker, fake, fail_on):
    login()
    names = [f"15-1234_{i}.jpg" for i in range(1, 8)]
    job, _ = make_job(api, add_uploaded, {n: {"creator": LESLIE} for n in names})
    schedule(api, job, fake)
    before = media_ids(fake)
    fail_on("termRead", status=503, count=0)
    j, rows = run(api, job, worker)
    assert j["job"]["status"] == "Failed" and j["job"]["code"] == "unavailable"
    # the check before the run fails once, but the language list read after it succeeds; then documents 1-5 fail
    # their checks, five in a row, and the job stops before document 5's next step; documents 6-7 aren't started
    assert j["job"]["codeDetail"].startswith("5 requests in a row to CollectionSpace failed, the last: GET personauthorities/")
    assert j["job"]["codeDetail"].endswith("stopped at document 5, step media")
    assert j["job"]["counts"]["failed"] == 5 and j["job"]["counts"]["notStarted"] == 2
    assert media_ids(fake) == before


def test_a_refused_sign_in_while_checking_values_stops_the_job(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job, _ = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE}})
    schedule(api, job, fake)
    fail_on("termRead", status=401, count=0)
    j, _ = run(api, job, worker)
    assert j["job"]["status"] == "Failed" and j["job"]["code"] == "auth"
    assert j["job"]["codeDetail"].startswith("Checking values before the first document:")


# ---- documents whose Media record exists aren't checked again -------------------------------------------------
def test_a_partial_document_is_not_checked_again(api, login, add_uploaded, worker, fake, fail_on):
    login()
    job, ns = make_job(api, add_uploaded, {"15-1234_1.jpg": {"creator": LESLIE}})
    schedule(api, job, fake)
    fail_on("upload", status=500)
    j, rows = run(api, job, worker)
    assert rows["15-1234_1.jpg"]["result"]["state"] == "Partial"
    fake.term_states["7475"] = "deleted"  # its Media record already holds the creator
    assert api.post(f"/api/jobs/{job}/fix").status_code == 200
    schedule(api, job, fake)
    j, rows = run(api, job, worker)
    row = rows["15-1234_1.jpg"]
    assert j["job"]["status"] == "Completed" and row["result"]["state"] == "Done"
    assert fake.term_reads == [] and row["result"]["steps"]["values"]["run"] == 1
