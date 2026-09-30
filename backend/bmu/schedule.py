"""The tenant's job schedule and the queue planner (design: Job scheduling).

Each tenant has one schedule: run days (ISO weekday numbers, 1 = Monday … 7 = Sunday), a start time and an
optional end time ("don't start new jobs after"), in Pacific time, and a pause. A queued job without a run time
of its own starts at the first scheduled start after it was submitted, and not after that start's run window
ends; a scheduler can also run a job now, give it its own run time, or hold it.

Every start is computed as a local wall-clock time on its day (zoneinfo), so the run time stays 7:00 PM across
the changes to and from daylight saving time. A start that falls in the spring-forward gap (e.g. 2:30 AM) runs
at the same instant as the time before the change would give (3:30 AM PDT); one in the repeated fall-back hour
runs at its first occurrence.

The web app (GET /api/schedule, the job's plan) and the worker (which job to claim) both use this module, so
what the queue shows and what the worker does agree. Both take `now` from an injectable clock.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

TIMEZONE = "America/Los_Angeles"
TZ = ZoneInfo(TIMEZONE)
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]
DEFAULT = {"days": ALL_DAYS, "start": "19:00", "end": "", "timezone": TIMEZONE, "paused": None,
           "updatedBy": None, "updatedAt": None}
# A queued job's saved sign-in lasts 72 hours (Settings.credential_hours), so run days may be at most 3 days apart
MAX_GAP_DAYS = 3
DAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    """A schedule that can't be saved; the message is shown to the user as is (422)."""


# ---- validation ------------------------------------------------------------------------------------------
def _hm(text: str) -> tuple[int, int]:
    m = _HHMM.match(text or "")
    if not m:
        raise ScheduleError(f"“{text}” isn't a time; use HH:MM (24-hour), for example 19:00.")
    return int(m.group(1)), int(m.group(2))


def validate(days: Iterable[Any], start: str, end: str | None) -> dict:
    """The schedule fields to save, normalized, or ScheduleError. Design (Job scheduling): at least one run day;
    a start time; an end time, if given, that differs from the start; and no gap of more than 3 days between
    consecutive run days, counted round the week (from the last run day to the first of the next week), because
    a queued job's saved sign-in lasts 72 hours."""
    try:
        ds = sorted({int(d) for d in days})
    except (TypeError, ValueError):
        raise ScheduleError("Run days are weekday numbers, 1 (Monday) to 7 (Sunday).") from None
    if not ds:
        raise ScheduleError("Choose at least one run day.")
    if any(d < 1 or d > 7 for d in ds):
        raise ScheduleError("Run days are weekday numbers, 1 (Monday) to 7 (Sunday).")
    if not (start or "").strip():
        raise ScheduleError("Enter a start time.")
    start = start.strip()
    _hm(start)
    end = (end or "").strip()
    if end:
        _hm(end)
        if end == start:
            raise ScheduleError("The end time must differ from the start time (leave it empty for no end time).")
    gaps = [(b - a) for a, b in zip(ds, ds[1:])] + [ds[0] + 7 - ds[-1]]
    if max(gaps) > MAX_GAP_DAYS:
        raise ScheduleError(f"Run days can be at most {MAX_GAP_DAYS} days apart, also from the last run day of the week "
                            "to the first: a queued job's saved sign-in lasts 72 hours, so a longer gap would let it "
                            "expire before the next run time.")
    return {"days": ds, "start": start, "end": end}


def normalize(item: dict | None) -> dict:
    """The stored schedule item (or None: never saved) with the defaults filled in."""
    out = {**DEFAULT, **{k: v for k, v in (item or {}).items() if k in DEFAULT}}
    out["days"] = sorted(int(d) for d in out["days"] or ALL_DAYS)
    out["end"] = out.get("end") or ""
    out["timezone"] = TIMEZONE  # fixed (design: "Pacific time")
    out["paused"] = out.get("paused") or None
    return out


def load(storage: Any, tenant: str) -> dict:
    """The tenant's schedule, with the defaults for anything never saved."""
    return normalize(storage.get_schedule(tenant))


def describe(schedule: dict) -> str:
    """A one-line summary for the audit log, e.g. "Mon, Wed, Fri at 19:00; no new jobs after 06:00"."""
    days = schedule["days"]
    if days == ALL_DAYS:
        when = "every day"
    elif days == [1, 2, 3, 4, 5]:
        when = "weekdays"
    else:
        when = ", ".join(DAY_NAMES[d] for d in days)
    out = f"{when} at {schedule['start']}"
    if schedule.get("end"):
        out += f"; no new jobs after {schedule['end']}"
    return out + " (Pacific time)"


# ---- run times ----------------------------------------------------------------------------------------------
def _instant(d: date, hm: tuple[int, int]) -> float:
    """The epoch time of a local wall-clock time on a local date (see the module docstring for DST)."""
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=TZ).timestamp()


def _local_date(t: float) -> date:
    return datetime.fromtimestamp(t, TZ).date()


def latest_start(schedule: dict, now: float) -> float | None:
    """The latest scheduled start at or before now (None only if the schedule has no run days)."""
    days, hm, today = set(schedule["days"]), _hm(schedule["start"]), _local_date(now)
    for k in range(0, 9):
        d = today - timedelta(days=k)
        if d.isoweekday() in days and (s := _instant(d, hm)) <= now:
            return s
    return None


def next_start(schedule: dict, now: float) -> float | None:
    """The next scheduled start at or after now."""
    days, hm, today = set(schedule["days"]), _hm(schedule["start"]), _local_date(now)
    for k in range(0, 9):
        d = today + timedelta(days=k)
        if d.isoweekday() in days and (s := _instant(d, hm)) >= now:
            return s
    return None


def window_end(schedule: dict, start: float) -> float | None:
    """When the run window that opened at `start` ends (no new job starts from then on), or None without an end
    time. An end time at or before the start time is on the next day: the window belongs to the day it starts."""
    if not schedule.get("end"):
        return None
    s_hm, e_hm = _hm(schedule["start"]), _hm(schedule["end"])
    d = _local_date(start)
    if e_hm <= s_hm:
        d += timedelta(days=1)
    return _instant(d, e_hm)


def window_open(schedule: dict, now: float) -> bool:
    """Whether now is inside a run window (after a start, before its end if there is one)."""
    s = latest_start(schedule, now)
    if s is None:
        return False
    e = window_end(schedule, s)
    return e is None or now < e


def is_due(job: dict, schedule: dict, now: float, always_run_time: bool = False) -> bool:
    """Design (Job scheduling): a job is due when it isn't held, the queue isn't paused, and it is to run now,
    or its own run time has come, or (without one) the latest scheduled start is at or after the moment it was
    queued and that start's window hasn't ended. always_run_time (development) makes every moment a run time."""
    if job.get("held") or schedule.get("paused"):
        return False
    if job.get("runNow"):
        return True
    if job.get("runAt") is not None:
        return now >= float(job["runAt"])
    if always_run_time:
        return True
    s = latest_start(schedule, now)
    if s is None or s < float(job.get("queuedAt") or 0):
        return False
    e = window_end(schedule, s)
    return e is None or now < e


# ---- the queue ----------------------------------------------------------------------------------------------
def queue_key(job: dict) -> tuple:
    """The queue order the Job queue tab shows (Move changes queuePos)."""
    return (job.get("queuePos", 0) or 0, job.get("queuedAt", 0) or 0)


def pick_next(jobs: list[dict], schedule: dict, now: float, always_run_time: bool = False) -> dict | None:
    """The job the worker claims next: the first due Run now job in queue order, else the first due job. None
    while one of the tenant's jobs is Running (design: one job per tenant at a time): also when the run lock was
    lost, e.g. a run whose worker stopped, which the heartbeat check ends; the next job waits for that."""
    if any(j.get("status") == "Running" for j in jobs):
        return None
    due = [j for j in sorted((j for j in jobs if j.get("status") == "Queued"), key=queue_key)
           if is_due(j, schedule, now, always_run_time)]
    return next((j for j in due if j.get("runNow")), None) or (due[0] if due else None)


def _planned_at(job: dict, schedule: dict, now: float, always_run_time: bool) -> float | None:
    """A queued job's planned start ignoring pause and hold: its own run time, else the scheduled start it waits
    for (the one that made it due, if it is due now), or in development mode the moment it was queued."""
    if job.get("runAt") is not None:
        return float(job["runAt"])
    if always_run_time:
        return float(job.get("queuedAt") or now)
    unpaused = {**schedule, "paused": None}
    if is_due({**job, "held": None}, unpaused, now):
        return latest_start(schedule, now)
    return next_start(schedule, now)


def plans(jobs: list[dict], schedule: dict, now: float, always_run_time: bool = False) -> dict[str, dict]:
    """The plan of every Queued or Running job, by job id: {kind, at, ahead, signInExpiresFirst}.

    kind: running | held | paused | runNow | at (its own run time) | schedule. at: the planned start (runAt, or
    the scheduled start for "schedule"), else None. ahead: the not-held queued jobs the worker will pick before
    it, in the worker's order (pick_next): Run now jobs first in queue order, then by planned start, jobs that
    are due now counting as starting now, so due jobs go in queue order. A paused queue plans as if resumed."""
    queued = [j for j in sorted((j for j in jobs if j.get("status") == "Queued"), key=queue_key)]
    order = {}
    for i, j in enumerate(queued):
        if j.get("runNow"):
            order[j["id"]] = (0, 0.0, i)
        else:
            at = _planned_at(j, schedule, now, always_run_time)
            order[j["id"]] = (1, max(at, now) if at is not None else float("inf"), i)
    out: dict[str, dict] = {}
    for j in jobs:
        if j.get("status") == "Running":
            out[j["id"]] = {"kind": "running", "at": None, "ahead": 0, "signInExpiresFirst": False}
    for j in queued:
        if j.get("held"):
            out[j["id"]] = {"kind": "held", "at": None, "ahead": 0, "signInExpiresFirst": False}
            continue
        ahead = sum(1 for o in queued if o["id"] != j["id"] and not o.get("held") and order[o["id"]] < order[j["id"]])
        if schedule.get("paused"):
            kind, at = "paused", None
        elif j.get("runNow"):
            kind, at = "runNow", None
        elif j.get("runAt") is not None:
            kind, at = "at", float(j["runAt"])
        else:
            kind, at = "schedule", _planned_at(j, schedule, now, always_run_time)
        expires = j.get("credentialExpires")
        out[j["id"]] = {"kind": kind, "at": at, "ahead": ahead,
                        "signInExpiresFirst": bool(at is not None and expires and at > float(expires))}
    return out


def view(schedule: dict, now: float, always_run_time: bool) -> dict:
    """The schedule as GET /api/schedule shows it."""
    return {**schedule, "nextRunAt": next_start(schedule, now),
            "windowOpen": bool(always_run_time or window_open(schedule, now)), "alwaysRunTime": bool(always_run_time)}
