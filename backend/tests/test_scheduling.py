"""Job scheduling (design: Job scheduling): the schedule and its planner, the scheduler role, the scheduler's
queue actions, and the worker claiming only due jobs. These tests turn Settings.always_run_time off (conftest
turns it on for the rest) and move an injected clock."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bmu import schedule as sched
from bmu.cspace import AccountRoles
from bmu.storage import now
from bmu.tenant import load_tenant, role_name
from bmu.worker import Worker
from conftest import worker_factory
from test_flow import _second_user, new_job

LA_TZ = ZoneInfo("America/Los_Angeles")
REFUSED = ("Only users with the BMU_Staff role can do this. Interns can create drafts and edit the drafts that are "
           "open to interns.")


def LA(*args) -> float:
    """Epoch seconds of a Pacific wall-clock time."""
    return datetime(*args, tzinfo=LA_TZ).timestamp()


def utc_hour(t: float) -> int:
    return datetime.fromtimestamp(t, ZoneInfo("UTC")).hour


def S(days=(1, 2, 3, 4, 5, 6, 7), start="19:00", end="", paused=None) -> dict:
    return sched.normalize({"days": list(days), "start": start, "end": end, "paused": paused})


# 2026-01-05 is a Monday; DST starts Sunday 2026-03-08 and ends Sunday 2026-11-01.
MON = (2026, 1, 5)


# ---- validation ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("days,start,end,message", [
    ([], "19:00", "", "at least one run day"),
    ([1, 2, 3, 4, 5, 6, 7], "", "", "Enter a start time"),
    ([1, 2, 3, 4, 5, 6, 7], "7pm", "", "isn't a time"),
    ([1, 2, 3, 4, 5, 6, 7], "24:00", "", "isn't a time"),
    ([1, 2, 3, 4, 5, 6, 7], "19:00", "19:00", "must differ"),
    ([1, 2, 3, 4, 5, 6, 7], "19:00", "6:00", "isn't a time"),
    ([0, 1], "19:00", "", "weekday numbers"),
    ([1, 5], "19:00", "", "at most 3 days apart"),        # Mon → Fri is 4 days
    ([3], "19:00", "", "at most 3 days apart"),           # one day a week: 7 days
    ([1, 4], "19:00", "", "at most 3 days apart"),        # Mon → Thu 3, but Thu → Mon 4 (round the week)
])
def test_invalid_schedules_are_refused_with_a_clear_message(days, start, end, message):
    with pytest.raises(sched.ScheduleError, match=message):
        sched.validate(days, start, end)


def test_valid_schedules_are_normalized():
    assert sched.validate([5, 3, 1, 3], "19:00", "") == {"days": [1, 3, 5], "start": "19:00", "end": ""}
    assert sched.validate([1, 2, 3, 4, 5], "07:30", " 06:00 ")["end"] == "06:00"  # Fri → Mon is 3 days: allowed
    assert sched.validate([1, 4, 7], "00:00", "23:59")["days"] == [1, 4, 7]


def test_defaults_and_summary():
    d = sched.normalize(None)
    assert d["days"] == [1, 2, 3, 4, 5, 6, 7] and d["start"] == "19:00" and d["end"] == "" and d["paused"] is None
    assert d["timezone"] == "America/Los_Angeles"
    assert sched.describe(d) == "every day at 19:00 (Pacific time)"
    assert sched.describe(S([1, 2, 3, 4, 5], end="06:00")) == "weekdays at 19:00; no new jobs after 06:00 (Pacific time)"
    assert sched.describe(S([1, 3, 5])) == "Mon, Wed, Fri at 19:00 (Pacific time)"


# ---- run times ------------------------------------------------------------------------------------------
def test_starts_follow_the_run_days():
    s = S([1, 3, 5])
    tue = LA(2026, 1, 6, 10, 0)
    assert sched.latest_start(s, tue) == LA(*MON, 19, 0)
    assert sched.next_start(s, tue) == LA(2026, 1, 7, 19, 0)  # Wednesday
    fri_night = LA(2026, 1, 9, 23, 0)
    assert sched.next_start(s, fri_night) == LA(2026, 1, 12, 19, 0)  # the next Monday
    assert sched.next_start(s, LA(*MON, 19, 0)) == LA(*MON, 19, 0)  # a start at exactly now counts
    assert sched.latest_start(s, LA(*MON, 18, 59)) == LA(2026, 1, 2, 19, 0)  # the Friday before


def test_an_end_time_before_the_start_is_on_the_next_day():
    s = S(end="06:00")
    start = LA(*MON, 19, 0)
    assert sched.window_end(s, start) == LA(2026, 1, 6, 6, 0)
    assert sched.window_open(s, LA(2026, 1, 6, 2, 0))       # 2 AM Tuesday is still Monday's window
    assert not sched.window_open(s, LA(2026, 1, 6, 6, 0))    # the end itself is outside
    assert not sched.window_open(s, LA(2026, 1, 6, 12, 0))
    assert sched.window_end(S(end="23:00"), start) == LA(*MON, 23, 0)
    assert sched.window_end(S(), start) is None
    # a window that crosses midnight into a day that isn't a run day still belongs to the day it started
    fri = S([1, 3, 5], end="04:00")
    assert sched.window_open(fri, LA(2026, 1, 10, 3, 0))    # Saturday 3 AM: Friday's window


def test_starts_stay_at_local_wall_clock_time_across_daylight_saving_changes():
    s = S()
    # spring forward (Sunday 2026-03-08): 7 PM is 03:00 UTC before, 02:00 UTC after
    assert utc_hour(sched.next_start(s, LA(2026, 3, 7, 20, 0))) == 2
    assert sched.next_start(s, LA(2026, 3, 7, 20, 0)) == LA(2026, 3, 8, 19, 0)
    assert utc_hour(sched.latest_start(s, LA(2026, 3, 8, 12, 0))) == 3  # Saturday's, before the change
    # fall back (Sunday 2026-11-01): 7 PM is 02:00 UTC before, 03:00 UTC after
    assert utc_hour(sched.latest_start(s, LA(2026, 10, 31, 20, 0))) == 2
    assert utc_hour(sched.next_start(s, LA(2026, 10, 31, 20, 0))) == 3
    assert sched.next_start(s, LA(2026, 10, 31, 20, 0)) - sched.latest_start(s, LA(2026, 10, 31, 20, 0)) == 25 * 3600
    # a start in the spring-forward gap runs at 3:30 AM PDT; an end across the change keeps its wall-clock time
    gap = S(start="02:30")
    assert sched.next_start(gap, LA(2026, 3, 8, 0, 0)) == datetime(2026, 3, 8, 10, 30, tzinfo=ZoneInfo("UTC")).timestamp()
    night = S(start="19:00", end="06:00")
    assert sched.window_end(night, LA(2026, 3, 7, 19, 0)) == LA(2026, 3, 8, 6, 0)
    assert sched.window_end(night, LA(2026, 3, 7, 19, 0)) - LA(2026, 3, 7, 19, 0) == 10 * 3600  # one hour shorter


# ---- due jobs ---------------------------------------------------------------------------------------------
def J(id="a", queued=LA(*MON, 12, 0), **kw) -> dict:
    return {"id": id, "status": "Queued", "queuedAt": queued, "queuePos": queued, "credentialExpires": queued + 72 * 3600, **kw}


def test_a_job_starts_at_the_first_run_time_after_it_was_submitted():
    s = S()
    job = J()
    assert not sched.is_due(job, s, LA(*MON, 18, 59))
    assert sched.is_due(job, s, LA(*MON, 19, 0))
    assert sched.is_due(job, s, LA(2026, 1, 6, 3, 0))  # no end time: still due after midnight
    late = J(queued=LA(*MON, 19, 30))  # submitted after tonight's start: tomorrow's
    assert not sched.is_due(late, s, LA(*MON, 22, 0))
    assert sched.is_due(late, s, LA(2026, 1, 6, 19, 0))


def test_a_job_does_not_start_after_its_run_windows_end():
    s = S(end="06:00")
    job = J()
    assert sched.is_due(job, s, LA(2026, 1, 6, 5, 59))
    assert not sched.is_due(job, s, LA(2026, 1, 6, 6, 0))   # missed: waits for the next start
    assert sched.is_due(job, s, LA(2026, 1, 6, 19, 0))
    assert not sched.is_due(J(queued=LA(*MON, 20, 0)), s, LA(2026, 1, 6, 1, 0))  # submitted inside the window


def test_run_now_run_at_hold_pause_and_always_run_time():
    s, t = S(), LA(*MON, 12, 0)
    assert sched.is_due(J(runNow=True), s, t)
    assert not sched.is_due(J(runAt=t + 60), s, t) and sched.is_due(J(runAt=t + 60), s, t + 60)
    assert sched.is_due(J(runAt=LA(*MON, 3, 0), queued=LA(*MON, 2, 0)), s, t)  # its own time, outside the window
    assert not sched.is_due(J(runAt=LA(*MON, 20, 0)), s, LA(*MON, 19, 30))   # its own time replaces the schedule's
    assert not sched.is_due(J(runNow=True, held={"by": "x", "at": t}), s, t)
    paused = S(paused={"by": "x", "at": t, "reason": "upgrade"})
    assert not sched.is_due(J(runNow=True), paused, t) and not sched.is_due(J(), paused, LA(*MON, 20, 0))
    assert sched.is_due(J(), s, t, always_run_time=True)
    assert not sched.is_due(J(), paused, t, always_run_time=True)
    assert not sched.is_due(J(held={"by": "x", "at": t}), s, t, always_run_time=True)


def test_the_worker_picks_run_now_first_then_queue_order_skipping_held_and_waiting_jobs():
    s, t = S(), LA(*MON, 20, 0)
    a = J("a", queuePos=1)
    b = J("b", queuePos=2, runNow=True)
    c = J("c", queuePos=3, held={"by": "x", "at": 0})
    d = J("d", queuePos=4, runAt=t + 3600)
    assert sched.pick_next([a, b, c, d], s, t)["id"] == "b"
    assert sched.pick_next([a, c, d], s, t)["id"] == "a"
    assert sched.pick_next([c, d], s, t) is None
    assert sched.pick_next([c, d], s, t + 3600)["id"] == "d"
    assert sched.pick_next([{**a, "status": "Running"}, c], s, t) is None
    # one job per tenant at a time: nothing starts while another job is Running, even a due Run now job
    assert sched.pick_next([J("r", status="Running"), a, b], s, t) is None
    assert sched.pick_next([J("r", status="Failed"), a, b], s, t)["id"] == "b"


def test_plans_say_when_each_job_starts_and_how_many_go_first():
    s, t = S(), LA(*MON, 12, 0)  # noon: tonight's start is 7 PM
    tonight = LA(*MON, 19, 0)
    jobs = [{"id": "r", "status": "Running"},
            J("a", queuePos=1), J("b", queuePos=2), J("h", queuePos=3, held={"by": "x", "at": t}),
            J("n", queuePos=4, runNow=True), J("e", queuePos=5, runAt=LA(*MON, 15, 0)),
            J("x", queuePos=6, runAt=LA(2026, 1, 9, 19, 0)),
            {"id": "d", "status": "Draft"}]
    p = sched.plans(jobs, s, t)
    assert set(p) == {"r", "a", "b", "h", "n", "e", "x"}
    assert p["r"] == {"kind": "running", "at": None, "ahead": 0, "signInExpiresFirst": False}
    assert p["n"] == {"kind": "runNow", "at": None, "ahead": 0, "signInExpiresFirst": False}
    assert p["e"] == {"kind": "at", "at": LA(*MON, 15, 0), "ahead": 1, "signInExpiresFirst": False}
    assert p["a"] == {"kind": "schedule", "at": tonight, "ahead": 2, "signInExpiresFirst": False}
    assert p["b"]["ahead"] == 3 and p["b"]["at"] == tonight
    assert p["h"] == {"kind": "held", "at": None, "ahead": 0, "signInExpiresFirst": False}
    assert p["x"]["kind"] == "at" and p["x"]["ahead"] == 4 and p["x"]["signInExpiresFirst"]  # after its sign-in expires
    # at 8 PM, "a", "b" and "e" are all due: the worker takes them in queue order
    later = sched.plans(jobs, s, LA(*MON, 20, 0))
    assert [later[k]["ahead"] for k in ("a", "b", "e")] == [1, 2, 3]
    assert later["a"]["at"] == tonight  # the run time that made it due
    # paused: every queued job says so; the order is kept for when it resumes
    paused = sched.plans(jobs, S(paused={"by": "x", "at": t, "reason": "r"}), t)
    assert paused["a"]["kind"] == "paused" and paused["a"]["at"] is None and paused["a"]["ahead"] == 2
    assert paused["h"]["kind"] == "held" and paused["r"]["kind"] == "running"


def test_plans_of_jobs_that_miss_a_window_or_wait_long():
    s = S([1, 3, 5], end="06:00")
    late = J("l", queued=LA(*MON, 20, 0))  # inside Monday's window: Wednesday's start
    p = sched.plans([late], s, LA(*MON, 21, 0))["l"]
    assert p["kind"] == "schedule" and p["at"] == LA(2026, 1, 7, 19, 0) and not p["signInExpiresFirst"]
    short = {**late, "credentialExpires": LA(2026, 1, 7, 12, 0)}  # its sign-in ends before Wednesday's run
    assert sched.plans([short], s, LA(*MON, 21, 0))["l"]["signInExpiresFirst"]
    dev = sched.plans([late], s, LA(*MON, 21, 0), always_run_time=True)["l"]
    assert dev["kind"] == "schedule" and dev["at"] == late["queuedAt"]


# ---- the scheduler role --------------------------------------------------------------------------------------
def test_the_role_rule():
    t = load_tenant("pahma")
    assert t.staff_roles == ("BMU_Staff",) and t.intern_roles == ("BMU_Intern",)
    assert t.role_of("15", ["ROLE_15_TENANT_READER", "ROLE_15_BMU_STAFF"]) == "staff"
    assert t.role_of("15", ["role_15_bmu_staff"]) == "staff"  # compared case-insensitively
    assert t.role_of("15", ["ROLE_15_BMU_INTERN"]) == "intern"
    assert t.role_of("15", ["ROLE_15_BMU_INTERN", "ROLE_15_BMU_STAFF"]) == "staff"  # staff wins
    assert t.role_of("15", ["ROLE_16_BMU_STAFF"]) == ""  # another tenant's role
    assert t.role_of("15", ["ROLE_15_TENANT_ADMINISTRATOR"]) == ""
    assert t.role_of("", ["ROLE_15_BMU_STAFF"]) == ""


def test_role_name_follows_cspace_sanitizing():
    # cspace-ui: upper-case, spaces -> _, drop all but A-Z 0-9 _, collapse repeated _; services: add ROLE_<t>_
    assert role_name("15", "BMU_Staff") == "ROLE_15_BMU_STAFF"
    assert role_name("15", "BMU Staff") == "ROLE_15_BMU_STAFF"
    assert role_name("15", "bmu  staff") == "ROLE_15_BMU_STAFF"  # repeated underscores collapse
    assert role_name("15", "BMU-Staff (PAHMA)") == "ROLE_15_BMUSTAFF_PAHMA"
    assert role_name("15", "+ cow") == "ROLE_15__COW"  # the prefix is added after the collapse
    assert role_name("15", "ROLE_15_BMU_STAFF") == "ROLE_15_BMU_STAFF"  # prefix not added twice
    assert role_name("16", "BMU_Staff") == "ROLE_16_BMU_STAFF"


def test_account_roles_are_parsed_from_collectionspace_xml():
    xml = (b'<ns2:account_role xmlns:ns2="http://collectionspace.org/services/authorization"><account><accountId>a1</accountId>'
           b'<screenName>Jo</screenName><userId>jo@example.org</userId><tenantId>15</tenantId></account>'
           b'<role><roleRelationshipId>r1</roleRelationshipId><roleId>x</roleId><roleName>ROLE_15_TENANT_READER</roleName></role>'
           b'<role><roleRelationshipId>r2</roleRelationshipId><roleId>y</roleId><roleName>ROLE_15_BMU_STAFF</roleName></role>'
           b'</ns2:account_role>')
    r = AccountRoles.from_xml(xml)
    assert r.tenant_id == "15" and r.role_names == ["ROLE_15_TENANT_READER", "ROLE_15_BMU_STAFF"]


def test_me_says_the_users_role(api, login, fake, services):
    assert login()["role"] == "staff"
    assert api.get("/api/me").json()["role"] == "staff"
    assert _second_user(services, "limited").get("/api/me").json()["role"] == "staff"
    assert _second_user(services, "intern").get("/api/me").json()["role"] == "intern"


def test_sign_in_is_refused_when_the_roles_cannot_be_read(api, fake):
    fake.fail_next["accountroles"] = 403  # CollectionSpace refuses the roles request: no role, so no sign-in
    r = api.post("/api/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "no_role"
    fake.fail_next["accountroles"] = 500  # CollectionSpace itself is failing: say that instead
    assert api.post("/api/login", json={"username": "admin", "password": "admin"}).status_code == 503


def test_the_roles_are_read_again_for_every_schedule_change(api, login, fake):
    login()
    assert api.put("/api/schedule", json={"days": [1, 2, 3, 4, 5, 6, 7], "start": "18:00"}).status_code == 200
    fake.role_overrides["admin"] = ["ROLE_15_TENANT_ADMINISTRATOR"]  # the role was removed after signing in
    r = api.put("/api/schedule", json={"days": [1, 2, 3, 4, 5, 6, 7], "start": "20:00"})
    assert r.status_code == 403 and r.json()["detail"] == REFUSED
    assert api.get("/api/me").json()["role"] == "staff"  # the session keeps its role; each staff action asks again
    assert api.get("/api/schedule").json()["start"] == "18:00"
    fake.role_overrides["admin"] = ["ROLE_15_Bmu_Staff"]  # given back (any case)
    assert api.post("/api/schedule/pause", json={"reason": "x"}).status_code == 200
    assert api.get("/api/me").json()["role"] == "staff"


# ---- the schedule API ----------------------------------------------------------------------------------------
def test_schedule_defaults_changes_and_validation(api, login, services):
    login()
    t = LA(*MON, 12, 0)
    services.clock = lambda: t
    services.settings.always_run_time = False
    g = api.get("/api/schedule").json()
    assert g == {"days": [1, 2, 3, 4, 5, 6, 7], "start": "19:00", "end": "", "timezone": "America/Los_Angeles",
                 "paused": None, "updatedBy": None, "updatedAt": None, "nextRunAt": LA(*MON, 19, 0),
                 "windowOpen": True, "alwaysRunTime": False}  # no end time: yesterday's window is still open
    r = api.put("/api/schedule", json={"days": [1, 5], "start": "19:00", "end": ""})
    assert r.status_code == 422 and "at most 3 days apart" in r.json()["detail"]
    r = api.put("/api/schedule", json={"days": [1, 3, 5], "start": "21:30", "end": "06:00"}).json()
    assert r["days"] == [1, 3, 5] and r["start"] == "21:30" and r["end"] == "06:00" and r["updatedBy"] == "admin"
    assert r["nextRunAt"] == LA(*MON, 21, 30) and r["windowOpen"] is False  # Friday's window ended at 6 AM Saturday
    assert api.get("/api/schedule").json()["end"] == "06:00"
    audit = [a for a in services.storage.list_audit("pahma") if a["type"] == "Schedule changed"]
    assert len(audit) == 1 and audit[0]["user"] == "admin"
    assert audit[0]["detail"] == ("Jobs run every day at 19:00 (Pacific time) → Mon, Wed, Fri at 21:30; no new jobs "
                                  "after 06:00 (Pacific time).")
    services.settings.always_run_time = True
    assert api.get("/api/schedule").json()["alwaysRunTime"] is True


def test_pause_and_resume(api, login, services):
    login()
    assert api.post("/api/schedule/pause", json={"reason": ""}).status_code == 422
    assert api.post("/api/schedule/pause", json={"reason": "x" * 201}).status_code == 422
    p = api.post("/api/schedule/pause", json={"reason": "CollectionSpace upgrade"}).json()["paused"]
    assert p["by"] == "admin" and p["reason"] == "CollectionSpace upgrade" and p["at"]
    assert api.post("/api/schedule/pause", json={"reason": "again"}).status_code == 409
    # saving the schedule keeps the pause
    assert api.put("/api/schedule", json={"days": [1, 2, 3, 4, 5], "start": "19:00"}).json()["paused"]["by"] == "admin"
    assert api.post("/api/schedule/resume").json()["paused"] is None
    assert api.post("/api/schedule/resume").json()["paused"] is None  # not paused: nothing to do
    types = [a["type"] for a in services.storage.list_audit("pahma")]
    assert types.count("Queue paused") == 1 and types.count("Queue resumed") == 1
    assert any(a["detail"] == "Paused the job queue: CollectionSpace upgrade" for a in services.storage.list_audit("pahma"))


def test_only_staff_change_the_schedule_and_the_queue(api, login, add_uploaded, services):
    login()
    job = new_job(api)
    add_uploaded(job, ["15-1234_a.jpg"])
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    other = _second_user(services, "intern")
    assert other.get("/api/schedule").status_code == 200  # everyone sees it
    for method, path, body in [("put", "/api/schedule", {"days": [1, 2, 3, 4, 5, 6, 7], "start": "19:00"}),
                               ("post", "/api/schedule/pause", {"reason": "x"}), ("post", "/api/schedule/resume", None),
                               ("post", f"/api/jobs/{job}/move", {"toIndex": 0}), ("post", f"/api/jobs/{job}/run-now", {"on": True}),
                               ("post", f"/api/jobs/{job}/run-at", {"at": None}), ("post", f"/api/jobs/{job}/hold", {"on": True})]:
        r = getattr(other, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 403 and r.json()["detail"] == REFUSED, (path, r.text)


# ---- queue actions ----------------------------------------------------------------------------------------------
def _submit(api, add_uploaded, name="Job", files=("15-1234_a.jpg",)):
    job = new_job(api, name)
    add_uploaded(job, list(files))
    r = api.post(f"/api/jobs/{job}/schedule")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_submit_response_and_job_lists_carry_the_plan(api, login, add_uploaded, services):
    login()
    services.settings.always_run_time = False
    first = _submit(api, add_uploaded, "First")
    t = now()
    services.clock = lambda: t
    second = _submit(api, add_uploaded, "Second", ["1-2345_1.jpg"])
    assert second["runNow"] is False and second["runAt"] is None and second["held"] is None
    nxt = sched.next_start(sched.normalize(None), second["queuedAt"])
    assert second["plan"] == {"kind": "schedule", "at": nxt, "ahead": 1, "signInExpiresFirst": False}
    jobs = {j["id"]: j for j in api.get("/api/jobs").json()["jobs"]}
    assert jobs[first["id"]]["plan"]["ahead"] == 0 and jobs[second["id"]]["plan"]["ahead"] == 1
    assert api.get(f"/api/jobs/{first['id']}").json()["job"]["plan"]["kind"] == "schedule"
    draft = new_job(api)
    assert "plan" not in api.get(f"/api/jobs/{draft}").json()["job"]
    # paused: the submit response says so
    api.post("/api/schedule/pause", json={"reason": "r"})
    assert _submit(api, add_uploaded, "Third", ["12-5678_1.jpg"])["plan"]["kind"] == "paused"


def test_run_now_run_at_and_hold(api, login, add_uploaded, services):
    login()
    services.settings.always_run_time = False
    a = _submit(api, add_uploaded, "A")["id"]
    b = _submit(api, add_uploaded, "B", ["1-2345_1.jpg"])["id"]
    j = api.post(f"/api/jobs/{b}/run-now", json={"on": True}).json()["job"]
    assert j["runNow"] is True and j["plan"] == {"kind": "runNow", "at": None, "ahead": 0, "signInExpiresFirst": False}
    assert api.get(f"/api/jobs/{a}").json()["job"]["plan"]["ahead"] == 1
    assert api.post(f"/api/jobs/{b}/run-now", json={"on": False}).json()["job"]["runNow"] is False

    t = now()
    services.clock = lambda: t
    expires = api.get(f"/api/jobs/{a}").json()["job"]["credentialExpires"]
    assert api.post(f"/api/jobs/{a}/run-at", json={"at": t - 3600}).status_code == 422
    assert api.post(f"/api/jobs/{a}/run-at", json={"at": expires + 60}).status_code == 422
    j = api.post(f"/api/jobs/{a}/run-at", json={"at": t + 7200}).json()["job"]
    assert j["runAt"] == t + 7200 and j["plan"]["kind"] == "at" and j["plan"]["at"] == t + 7200
    assert api.post(f"/api/jobs/{a}/run-at", json={"at": t - 30}).status_code == 200  # a minute's grace
    assert api.post(f"/api/jobs/{a}/run-at", json={"at": None}).json()["job"]["runAt"] is None

    j = api.post(f"/api/jobs/{a}/hold", json={"on": True}).json()["job"]
    assert j["held"]["by"] == "admin" and j["plan"]["kind"] == "held"
    assert api.get(f"/api/jobs/{b}").json()["job"]["plan"]["ahead"] == 0  # a held job doesn't go first
    assert api.post(f"/api/jobs/{a}/hold", json={"on": False}).json()["job"]["held"] is None

    types = [x["type"] for x in services.storage.list_audit("pahma")]
    for kind in ("Run now", "Run now undone", "Run time set", "Run time cleared", "Job held", "Job released"):
        assert kind in types, kind
    # only queued jobs
    draft = new_job(api)
    for path, body in [("run-now", {"on": True}), ("run-at", {"at": None}), ("hold", {"on": True})]:
        assert api.post(f"/api/jobs/{draft}/{path}", json=body).status_code == 409


def test_resubmitting_forgets_the_old_queue_settings(api, login, add_uploaded, services):
    login()
    job = _submit(api, add_uploaded)["id"]
    api.post(f"/api/jobs/{job}/run-now", json={"on": True})
    api.post(f"/api/jobs/{job}/hold", json={"on": True})
    assert api.post(f"/api/jobs/{job}/edit").status_code == 200
    j = api.post(f"/api/jobs/{job}/schedule").json()
    assert j["runNow"] is False and j["held"] is None and j["runAt"] is None


def test_reordering_is_audited(api, login, add_uploaded, services):
    login()
    a = _submit(api, add_uploaded, "A")["id"]
    b = _submit(api, add_uploaded, "B", ["1-2345_1.jpg"])["id"]
    jobs = api.post(f"/api/jobs/{b}/move", json={"toIndex": 0}).json()["jobs"]
    assert [j["id"] for j in jobs] == [b, a] and [j["plan"]["ahead"] for j in jobs] == [0, 1]
    assert [x["detail"] for x in services.storage.list_audit("pahma") if x["type"] == "Queue reordered"] == \
        ["Moved “B” to place 1 of 2 in the queue."]


def test_cancel_run_is_for_staff(api, login, add_uploaded, services, fake):
    login()
    job = _submit(api, add_uploaded)["id"]
    services.storage.update_job(job, {"status": "Running"})  # as if the worker started it
    r = _second_user(services, "intern").post(f"/api/jobs/{job}/cancel")
    assert r.status_code == 403 and r.json()["detail"] == REFUSED
    fake.role_overrides["admin"] = ["ROLE_15_TENANT_READER"]  # the submitter lost the role: no longer theirs to cancel
    assert api.post(f"/api/jobs/{job}/cancel").status_code == 403
    j = _second_user(services, "limited").post(f"/api/jobs/{job}/cancel").json()  # any staff member, any job
    assert j["cancelRequested"]["by"] == "limited" and j["plan"]["kind"] == "running"
    assert any(a["type"] == "Run cancelled" for a in services.storage.list_audit("pahma"))


# ---- the worker ---------------------------------------------------------------------------------------------
@pytest.fixture
def clocked(services):
    """A worker and web app judging the schedule by a clock the test sets; always_run_time off."""
    services.settings.always_run_time = False
    clock = {"t": now()}
    services.clock = lambda: clock["t"]
    w = Worker(services.settings, services.storage, services.crypto, worker_factory, clock=lambda: clock["t"])
    return w, clock


def test_the_worker_runs_a_job_at_its_run_time_only(api, login, add_uploaded, services, clocked):
    worker, clock = clocked
    login()
    job = _submit(api, add_uploaded)
    start = sched.next_start(sched.normalize(None), job["queuedAt"])
    clock["t"] = start - 60
    assert worker.tick() is False and services.storage.get_job(job["id"])["status"] == "Queued"
    clock["t"] = start + 60
    assert worker.tick() is True
    j = services.storage.get_job(job["id"])
    assert j["status"] == "Completed" and not j.get("runNow")


def test_the_worker_respects_pause_hold_and_run_now(api, login, add_uploaded, services, clocked):
    worker, clock = clocked
    login()
    a = _submit(api, add_uploaded, "A")["id"]
    b = _submit(api, add_uploaded, "B", ["1-2345_1.jpg"])["id"]
    c = _submit(api, add_uploaded, "C", ["12-5678_1.jpg"])["id"]
    api.post("/api/schedule/pause", json={"reason": "r"})
    api.post(f"/api/jobs/{c}/run-now", json={"on": True})
    assert worker.tick() is False  # paused: not even Run now
    api.post("/api/schedule/resume")
    assert worker.tick() is True and services.storage.get_job(c)["status"] == "Completed"  # before the run time
    assert worker.tick() is False  # the others wait for the run time
    api.post(f"/api/jobs/{a}/hold", json={"on": True})
    clock["t"] = sched.next_start(sched.normalize(None), clock["t"]) + 1
    assert worker.tick() is True
    assert services.storage.get_job(b)["status"] == "Completed" and services.storage.get_job(a)["status"] == "Queued"
    assert worker.tick() is False  # held
    api.post(f"/api/jobs/{a}/hold", json={"on": False})
    assert worker.tick() is True and services.storage.get_job(a)["status"] == "Completed"


def test_the_worker_runs_a_job_at_its_own_run_time(api, login, add_uploaded, services, clocked):
    worker, clock = clocked
    login()
    a = _submit(api, add_uploaded)["id"]
    at = clock["t"] + 1800
    api.post(f"/api/jobs/{a}/run-at", json={"at": at})
    clock["t"] = at - 1
    assert worker.tick() is False
    clock["t"] = at
    assert worker.tick() is True and services.storage.get_job(a)["status"] == "Completed"


def test_a_job_held_after_the_worker_chose_it_is_not_claimed(api, login, add_uploaded, services, worker):
    login()
    a = _submit(api, add_uploaded)["id"]
    services.storage.update_job(a, {"held": {"by": "admin", "at": now()}})
    worker.run_job(a)  # the claim's condition refuses it
    assert services.storage.get_job(a)["status"] == "Queued"


def test_development_mode_runs_queued_jobs_at_once(api, login, add_uploaded, services, worker):
    login()
    job = _submit(api, add_uploaded)
    assert job["plan"]["kind"] == "schedule" and job["plan"]["at"] == job["queuedAt"]
    assert worker.tick() is True


def test_a_run_time_that_puts_a_job_first_is_warned_about_when_it_makes_a_document_fail(api, login, add_uploaded, services):
    """Design (Jobs that collide in the queue): the job's own run time decides when it runs, whatever its place."""
    services.settings.always_run_time = False
    clock = {"t": LA(*MON, 9, 0)}
    services.clock = lambda: clock["t"]
    login()
    creates = new_job(api, "Creates it")
    n = add_uploaded(creates, ["20-0501.jpg"])[0]["n"]
    api.patch(f"/api/jobs/{creates}/rows/{n}", json={"handling": "create"})
    assert api.post(f"/api/jobs/{creates}/schedule").status_code == 200
    links = new_job(api, "Links or creates")
    n = add_uploaded(links, ["20-0501_b.jpg"])[0]["n"]
    api.patch(f"/api/jobs/{links}/rows/{n}", json={"handling": "linkorcreate"})
    assert api.post(f"/api/jobs/{links}/schedule").status_code == 200
    r = api.post(f"/api/jobs/{links}/run-at", json={"at": LA(*MON, 12, 0)})  # before tonight's 7:00 PM start
    assert r.status_code == 409 and r.json()["detail"]["code"] == "would_fail"
    assert api.post(f"/api/jobs/{links}/run-at", json={"at": LA(*MON, 21, 0)}).status_code == 200  # after it: fine
    assert api.post(f"/api/jobs/{links}/run-at", json={"at": LA(*MON, 12, 0), "confirm": True}).status_code == 200
    plan = api.get("/api/queue/collisions").json()
    assert "“Links or creates” has its own run time" in plan["remaining"][0] and plan["changes"] is False
