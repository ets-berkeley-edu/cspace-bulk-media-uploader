"""The BMU worker: runs scheduled jobs one row at a time, one job per tenant at a time.

Every step records the CSID it created, so a rerun skips finished steps and never creates a
record twice. The job's password is deleted when the run ends, whatever the outcome. Failures are
recorded as codes from the failure catalog (failures.yaml); the UI shows their wording.

Run: python -m bmu.worker
"""
from __future__ import annotations

import logging
import socket
import threading
import time
import uuid
from datetime import datetime

from botocore.exceptions import ClientError

from . import schedule as sched
from .config import Settings, get_settings
from .crypto import Crypto, make_crypto
from .cspace import CSpaceClient, CSpaceError, CSpaceUnavailable
from .cspace.client import display_name
from .cspace.payloads import group_xml, media_xml, object_xml, relation_xml
from .failures import JOB_LEVEL, classify
from .filetypes import HEAD_BYTES, mismatch
from .rows import (AUTHORITY_FIELDS, AUTHORITY_LABEL, authority_read_checks, created_records, describe_deletion,
                   language_map, media_created, object_step_ran, permission_checks, use_current, value_findings)
from .storage import Storage, draft_expiry, expiry_of, now
from .tenant import AUTHORITY_REF, OBJECT_STEPS, Tenant, load_tenant

log = logging.getLogger("bmu.worker")

MAX_CONSECUTIVE_SERVER_ERRORS = 5
# A job left in a temporary state (Stopping, Reverting, Expiring, Deleting) this long was interrupted part way (the
# process stopped): the sweep finishes what the state was doing. Each of those steps is safe to repeat.
TRANSIENT_GRACE_SECONDS = 600
INLINE_AUDIT_ROWS = 100  # a run's per-row audit detail goes in the entry up to this many rows, in S3 beyond
RECORD_TYPE = {"media": "Media", "upload": "Blob", "createObject": "CollectionObject", "findOrCreateObject": "CollectionObject",
               "relMediaObject": "Relation",
               "relObjectMedia": "Relation", "addToGroup": "Relation", "group": "Group"}
STOPPED_JOB = {"unavailable", "worker_stopped", "unknown"} | JOB_LEVEL  # these end the job as Failed
LINK_STEPS = OBJECT_STEPS + ("relMediaObject", "relObjectMedia", "addToGroup")  # what "Stop linking" skips
FINISHED = ("done", "not needed")
# Design (Job execution): a row's values are checked against CollectionSpace just before its records are created,
# from lookups at most this old; each distinct term is read about once a minute however many rows use it.
VALUE_CHECK_SECONDS = 60


class JobStop(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _step(row: dict, name: str) -> dict:
    res = row.get("result") or {}
    row["result"] = res
    steps = res.setdefault("steps", {})
    return steps.setdefault(name, {"s": "not run"})


def plan_steps(tenant: Tenant, row: dict, job: dict | None = None) -> list[tuple[str, list[str]]]:
    """A row's steps in order, each with the steps it depends on (design: "Steps within a row").

    Check the document (only while the Media record doesn't exist; run again every run)  depends on nothing
      its values, its Object (per the handling), the account's permissions and its staged file: Worker._check_row
    Create Media record      depends on the check
    Find, create, or find or create the Object (per the handling)       depends on the check
    Upload file (PUT media/{csid}/blob, which creates the Blob record)   depends on Media
    Create Relations, both directions                                    depend on Media and Object
    Add the Object to the job's Group (if the job creates one and the row is in it)  depends on the Relations
    """
    h = tenant.handling_by_id(row["handling"])
    obj = h.object_step
    # Design (Job execution): nothing is created for a row that wasn't checked just before. A row whose Media record
    # exists is past that point: its remaining steps make their own checks. The step keeps its first name, "values".
    check = [] if media_created(row) else ["values"]
    steps: list[tuple[str, list[str]]] = [("values", [])] if check else []
    steps.append(("media", check))
    if obj:
        steps.append((obj, check))
    steps.append(("upload", ["media"]))
    if obj:
        steps += [("relMediaObject", ["media", obj]), ("relObjectMedia", ["media", obj])]
        if job and job.get("groupOn") and row.get("group", True):
            steps.append(("addToGroup", ["relMediaObject", "relObjectMedia"]))
    return steps


def row_state(res: dict | None, planned: list[str] | None = None) -> str:
    """Design: Row state. Done: every step done (or no longer needed); Partial: the Media record exists
    and something else isn't finished; Failed: the Media record wasn't created; Not started otherwise.
    planned: the row's steps; any not recorded yet count as not run."""
    steps = dict((res or {}).get("steps") or {})
    for name in planned or []:
        steps.setdefault(name, {"s": "not run"})
    if not steps or all(st.get("s") == "not run" for st in steps.values()):
        return "Not started"
    if all(st.get("s") in FINISHED for st in steps.values()):
        return "Done"
    if (steps.get("media") or {}).get("s") == "done":
        return "Partial"
    return "Failed"


def row_counts(rows: list[dict]) -> dict:
    """Documents by result, as the Finished jobs list shows them."""
    c = {"done": 0, "partial": 0, "failed": 0, "notStarted": 0, "disabled": 0}
    key = {"Done": "done", "Partial": "partial", "Failed": "failed"}
    for r in rows:
        state = (r.get("result") or {}).get("state") or "Not started"
        if state == "In progress":
            state = row_state(r.get("result"))
        if not r.get("include") and state != "Done":
            c["disabled"] += 1
        else:
            c[key.get(state, "notStarted")] += 1
    return c


class _Heartbeat(threading.Thread):
    """Renews the running job's heartbeat and the tenant's run lock, even while one long upload runs."""

    def __init__(self, worker: "Worker", job_id: str):
        super().__init__(daemon=True, name=f"heartbeat-{job_id}")
        self.w, self.job_id = worker, job_id
        self.halt = threading.Event()

    def run(self) -> None:
        while not self.halt.wait(self.w.s.heartbeat_seconds):
            try:
                self.w.storage.heartbeat(self.job_id)
                self.w.storage.renew_lock(self.w.tenant.key, self.w.owner, self.w.s.worker_lock_seconds)
            except Exception:  # a missed beat is harmless; several in a row let the sweeper stop the job
                log.exception("heartbeat failed for job %s", self.job_id)


class Worker:
    def __init__(self, settings: Settings, storage: Storage, crypto: Crypto, client_factory, tenant: Tenant | None = None,
                 clock=None, lookup_clock=None):
        """clock: the time the job schedule is judged by (design: Job scheduling), a callable returning epoch
        seconds; tests pass their own to move time. Expiry and the sweeps keep the real time. lookup_clock: the time
        a run's value lookups age by (VALUE_CHECK_SECONDS), in seconds; tests pass their own."""
        self.s = settings
        self.clock = clock or now
        self.lookup_clock = lookup_clock or time.monotonic
        self._values: _ValueLookups | None = None  # the running job's value lookups
        self.storage = storage
        self.crypto = crypto
        self.client_factory = client_factory
        self.tenant = tenant or load_tenant(settings.tenant)
        self.owner = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self._last_sweep = 0.0
        self._last_abandoned_sweep = 0.0
        self._job_media: set[str] = set()  # Media records the running job has created
        self._perms: dict[str, bool] | None = None  # the running job's account permissions; None: couldn't be read
        self._object_found: dict[int, list[str]] = {}  # the check's Object search, per row, for its Object step
        self._job_name = ""
        self._where = ""  # where the running job is, for the detail of an unexpected error

    # ---- scheduling ------------------------------------------------------------------------
    def run_forever(self) -> None:
        log.info("worker %s started for tenant %s", self.owner, self.tenant.key)
        while True:
            try:
                if not self.tick():
                    time.sleep(self.s.worker_poll_seconds)
            except Exception:  # keep the worker alive; a stuck job is stopped by the heartbeat check
                log.exception("worker loop error")
                time.sleep(self.s.worker_poll_seconds)

    def sweep(self) -> None:
        """The periodic checks: sign-ins that expired in the queue or while running, expired drafts and fixes,
        Completed jobs past their 30 days, running jobs whose worker stopped, deletions and other temporary states
        (Stopping, Reverting, Expiring) left part way, protected files' staged uploads, idle or expired sign-in
        sessions, and (hourly) abandoned uploads."""
        self.sweep_expired_sign_ins()
        self.sweep_expired_drafts()
        self.sweep_completed()
        self.sweep_stopped_jobs()
        self.sweep_unfinished_deletions()
        self.sweep_interrupted_transitions()
        self.sweep_protected_staged()
        self.storage.sweep_sessions(self.s.session_idle_minutes * 60)
        if now() - self._last_abandoned_sweep > 3600:  # hourly is plenty for a one-day limit
            self._last_abandoned_sweep = now()
            self.sweep_abandoned_uploads()

    def sweep_unfinished_deletions(self) -> list[str]:
        """A deletion that stopped half way (the web app was stopped after marking the job Deleting) is finished
        after ten minutes; its sign-in is already gone. The web app writes the complete audit entry before deleting
        anything, so normally only the leftovers are removed here. If the web app stopped before writing it, nothing
        was deleted yet, and the entry is written here from the job as it still is, under the user who deleted it
        (storage.audit_job_deleted writes it at most once, even if the web app is still deleting)."""
        done = []
        for j in self.storage.list_jobs(self.tenant.key):
            if j["status"] == "Deleting" and float(j.get("deletingSince") or 0) < now() - TRANSIENT_GRACE_SECONDS:
                if not j.get("deleteAudited"):
                    rows = self.storage.get_rows(j["id"])
                    created = created_records(rows, j)
                    self.storage.audit_job_deleted(self.tenant.key, j["id"], j.get("deletedBy") or "BMU",
                                                   describe_deletion(j, len(rows), created, finished_by_sweep=True), created,
                                                   jobName=j.get("name", ""))
                self.storage.delete_job_and_files(j["id"])
                done.append(j["id"])
        return done

    def sweep_interrupted_transitions(self) -> list[str]:
        """Design (State rules): the worker's own temporary states are finished like an interrupted deletion, ten
        minutes after the job entered them (the *Since field set with the state). Stopping: the stopped run is
        ended as worker_stopped (what sweep_stopped_jobs does). Reverting: the abandoned fix is reverted again.
        Expiring: the expired draft or Completed job is deleted again. Each is safe to repeat part way."""
        done = []
        limit = now() - TRANSIENT_GRACE_SECONDS
        for j in self.storage.list_jobs(self.tenant.key):
            status = j["status"]
            since = float(j.get({"Stopping": "stoppingSince", "Reverting": "revertingSince",
                                 "Expiring": "expiringSince"}.get(status, "")) or 0)
            if status not in ("Stopping", "Reverting", "Expiring") or since >= limit:
                continue
            if status == "Stopping":
                self._stop(j)
            elif status == "Reverting":
                self._revert(j)
            else:
                self._expire(j)
            done.append(j["id"])
        return done

    def sweep_expired_sign_ins(self) -> list[str]:
        """A queued job whose saved sign-in reached its time limit leaves the queue for Drafts (design: State
        rules, Sign-in expired while waiting); anyone can submit it again with their own sign-in."""
        moved = []
        for j in self.storage.list_jobs(self.tenant.key):
            if j["status"] == "Queued" and j.get("credentialExpires") and j["credentialExpires"] < now():
                if self._sign_in_expired(j):
                    moved.append(j["id"])
            elif j["status"] == "Running" and j.get("credentialExpires") and j["credentialExpires"] < now():
                # Design (Credentials): the stored sign-in of a job still running past the time limit is deleted too.
                # The run in progress keeps the copy it decrypted when it started, until it ends.
                if self.storage.get_credential(j["id"]):
                    self.storage.delete_credential(j["id"])
                    self.storage.audit(self.tenant.key, "Sign-in expired", "BMU", j["id"],
                                       f"Deleted the saved sign-in of “{j.get('name') or 'Untitled job'}”: it was still running "
                                       f"{self.s.credential_hours:g} hours after it was submitted.")
        return moved

    def _sign_in_expired(self, j: dict) -> bool:
        """A queued job whose saved sign-in expired goes back to Drafts, expiring like any draft (7 days with
        protected files, 30 otherwise)."""
        if not self.storage.update_job(j["id"], {"status": "Draft", "queuePos": None, "lastSavedAt": now(),
                                                 **draft_expiry(j, now() + self.s.draft_days_for(j) * 86400),
                                                 "note": "Sign-in expired while waiting in the queue; submit it again to run it with your sign-in."},
                                       expect_status="Queued"):
            return False
        self.storage.delete_credential(j["id"])
        self.storage.audit(self.tenant.key, "Sign-in expired", "BMU", j["id"],
                           f"“{j.get('name') or 'Untitled job'}” moved to Drafts: its saved sign-in expired while it waited.")
        return True

    def sweep_expired_drafts(self) -> list[str]:
        """Drafts past their expiry (design: Drafts, Expiry; State rules, Abandoned fixes). A draft that has
        never run is deleted with its rows and staged files. A fix of a job that has run is reverted: its
        edits are discarded and the job returns to Needs attention or Failed with its rows, run history and
        CSIDs intact. Both are written to the audit log. A fix's expiry is its draftExpiresAt (see draft_expiry)."""
        done = []
        for j in self.storage.list_jobs(self.tenant.key):
            expires = expiry_of(j) if j["status"] == "Draft" else None
            if not expires or expires >= now():
                continue
            if j.get("fixFrom"):
                if self.revert_fix(j):
                    done.append(j["id"])
            elif not j.get("run"):
                if self.storage.update_job(j["id"], {"status": "Expiring", "expiringSince": now(), "expiringFrom": "Draft"},
                                           expect_status="Draft"):
                    self._expire({**j, "expiringFrom": "Draft"})
                    done.append(j["id"])
        return done

    def _expire(self, j: dict) -> None:
        """Delete a job that is Expiring: a draft that never ran, or a Completed job past its 30 days. The audit
        entry is written first, once (storage.audit_once), so an interrupted expiry redone by the sweep neither loses
        nor repeats it."""
        if not j.get("expiryAudited"):
            n = len(self.storage.get_rows(j["id"]))
            name = j.get("name") or "Untitled job"
            if j.get("expiringFrom") == "Completed":
                kind, text = "Job expired", f"Removed “{name}” ({n} documents), {self.s.completed_days} days after it completed."
            else:
                kind, text = "Draft expired", (f"Deleted “{name}” ({n} documents), {self.s.draft_days_for(j)} days after it "
                                               "was last saved; it had never run.")
            self.storage.audit_once(self.tenant.key, j["id"], "Expiring", "expiryAudited", kind, "BMU", text)
        self.storage.delete_job_and_files(j["id"])

    def revert_fix(self, job: dict) -> bool:
        """Discard a fix's edits: put back every row it changed, remove documents it added, and return the
        job to the state it came from. Rows deleted during the fix stay deleted (deleting is permanent)."""
        if not self.storage.update_job(job["id"], {"status": "Reverting", "revertingSince": now()}, expect_status="Draft"):
            return False
        self._revert(job)
        return True

    def _revert(self, job: dict) -> None:
        """The revert itself, for a job in Reverting; repeated from the start by the sweep if it was interrupted
        (restoring a row again, or removing a row already removed, changes nothing)."""
        fix = job["fixFrom"]
        current = {r["n"]: r for r in self.storage.get_rows(job["id"])}
        for orig in self.storage.fix_originals(job["id"]):
            cur = current.get(orig["n"])
            if cur is None:
                continue
            if cur.get("s3Key") and cur["s3Key"] != orig.get("s3Key"):
                self.storage.delete_object(cur["s3Key"])  # a replacement file added during the fix
            self.storage.restore_row(job["id"], orig)
        added = [r for r in current.values() if r.get("addedInFix")]
        for r in added:
            if r.get("s3Key"):
                self.storage.delete_object(r["s3Key"])
            self.storage.delete_row(job["id"], r["n"])
        self.storage.drop_fix_originals(job["id"])
        self.storage.clear_editing(job["id"])
        if not self.storage.update_job(job["id"], {"status": fix["status"], "code": fix.get("code", ""),
                                                   "codeDetail": fix.get("codeDetail", ""), "fixFrom": None,
                                                   "expiresAt": None, "draftExpiresAt": None, "note": ""},
                                       expect_status="Reverting"):
            return  # finished meanwhile by another sweep
        self.storage.audit(self.tenant.key, "Fix reverted", "BMU", job["id"],
                           f"Fix and reschedule of “{job.get('name') or 'Untitled job'}” was not finished within "
                           f"{self.s.draft_days_for(job)} days; the edits were discarded and the job returned to "
                           f"{'Needs attention' if fix['status'] == 'NeedsAttention' else fix['status']} with its history.")

    def sweep_completed(self) -> list[str]:
        """Completed jobs are removed 30 days after they finish (their run audit entries stay for a year)."""
        gone = []
        for j in self.storage.list_jobs(self.tenant.key):
            if j["status"] == "Completed" and j.get("expiresAt") and j["expiresAt"] < now():
                if self.storage.update_job(j["id"], {"status": "Expiring", "expiringSince": now(), "expiringFrom": "Completed"},
                                           expect_status="Completed"):
                    self._expire({**j, "expiringFrom": "Completed"})
                    gone.append(j["id"])
        return gone

    def sweep_protected_staged(self) -> list[tuple[str, int]]:
        """Design: Protected files, Cleanup. In jobs that need attention or failed, a protected file's staged
        upload is removed after a time limit even though the job stays; a fix adds the file again."""
        removed = []
        limit = now() - self.s.protected_staged_days * 86400
        for j in self.storage.list_jobs(self.tenant.key):
            if j["status"] not in ("NeedsAttention", "Failed") or (j.get("finishedAt") or now()) > limit:
                continue
            for r in self.storage.get_rows(j["id"]):
                upload_open = ((r.get("result") or {}).get("steps") or {}).get("upload", {}).get("s") != "done"
                if r.get("protected") and upload_open and (r.get("upload") or {}).get("s") == "done" and r.get("s3Key"):
                    self._delete_key(r["s3Key"])
                    r["upload"] = {"s": "failed", "reason": "removed"}
                    self.storage.put_row(j["id"], r, guard=False)
                    removed.append((j["id"], r["n"]))
            if any(jid == j["id"] for jid, _ in removed):
                self.storage.audit(self.tenant.key, "Protected files removed", "BMU", j["id"],
                                   f"Removed the staged uploads of {sum(1 for jid, _ in removed if jid == j['id'])} protected file(s) "
                                   f"from “{j.get('name') or 'Untitled job'}”, {self.s.protected_staged_days} days after it stopped.")
        return removed

    def sweep_abandoned_uploads(self) -> list[str]:
        """Design (Browser uploads, Abandoned uploads): staged objects that no document refers to (an upload that
        arrived after its document was deleted, a replacement never used) are deleted after about a day."""
        referenced: set[str] = set()
        for j in self.storage.list_jobs(self.tenant.key):
            for r in self.storage.get_rows(j["id"]) + self.storage.fix_originals(j["id"]):
                referenced |= {r.get("s3Key"), r.get("supersededKey"), r.get("thumbKey")}
        limit = now() - self.s.abandoned_upload_hours * 3600
        gone = []
        for key, modified in self.storage.list_staged(f"staging/{self.tenant.key}/"):
            if key not in referenced and modified < limit:
                self._delete_key(key)
                gone.append(key)
        if gone:
            log.info("deleted %d abandoned staged files", len(gone))
        return gone

    def sweep_stopped_jobs(self) -> list[str]:
        """A Running job whose heartbeat went stale lost its worker: it stops as Failed with code
        worker_stopped, and its saved sign-in is deleted. Its rows keep the steps already recorded."""
        stopped = []
        limit = now() - self.s.heartbeat_stale_seconds
        for j in self.storage.list_jobs(self.tenant.key):
            beat = j.get("heartbeatAt") or j.get("startedAt") or 0
            if j["status"] == "Running" and beat < limit:
                # the technical detail, kept with the state so an interrupted stop (sweep_interrupted_transitions) has it
                detail = (f"No heartbeat for {int((now() - float(beat)) // 60)} minutes" if beat else "No heartbeat") + \
                    (f"; the run was on document {j['currentRow']}" if j.get("currentRow") else "")
                if self.storage.update_job(j["id"], {"status": "Stopping", "stoppingSince": now(), "codeDetail": detail},
                                           expect_status="Running"):
                    self._stop({**j, "codeDetail": detail})
                    stopped.append(j["id"])
        return stopped

    def _stop(self, j: dict) -> None:
        """End the run of a job in Stopping as worker_stopped; repeated by the sweep if it was interrupted."""
        self.storage.delete_credential(j["id"])
        self._finish(j["id"], int(j.get("run", 0)), "worker_stopped", j.get("scheduledBy") or "BMU", [],
                     j.get("codeDetail") or "No heartbeat")

    def maybe_sweep(self) -> None:
        """The periodic checks, at most once a minute. Also called between documents during a run, so a long
        run doesn't hold up draft expiry, cleanup, or stopping another worker's stalled job."""
        if now() - self._last_sweep > 60:
            self._last_sweep = now()
            try:
                self.sweep()
            except Exception:  # a failed check must never stop the job being run; it is tried again next time
                log.exception("periodic checks failed")

    def tick(self) -> bool:
        """Run the next job for this tenant, if any. Returns True if a job ran."""
        self.maybe_sweep()
        if not self.storage.acquire_lock(self.tenant.key, self.owner, self.s.worker_lock_seconds):
            return False  # another worker is running this tenant's job
        try:
            job = self._next_job()
            if not job:
                return False
            self.run_job(job["id"])
            return True
        finally:
            self.storage.release_lock(self.tenant.key, self.owner)

    def _next_job(self) -> dict | None:
        """The first due job (design: Job scheduling): Run now jobs first, then the rest in queue order; none while
        the queue is paused, never a held job, and a job without its own run time only in its run window (every
        moment with Settings.always_run_time). Not-due jobs wait. See bmu.schedule.pick_next."""
        # A job left Running by a worker that stopped is not resumed: the heartbeat check stops it as
        # "worker_stopped", and a user reschedules it (its finished steps are skipped). No job starts while one of
        # the tenant's jobs is Running, even if the run lock was lost: the next job waits for the heartbeat check.
        schedule = sched.load(self.storage, self.tenant.key)
        return sched.pick_next(self.storage.list_jobs(self.tenant.key), schedule, self.clock(), self.s.always_run_time)

    # ---- one job ------------------------------------------------------------------------------
    def run_job(self, job_id: str) -> None:
        job = self.storage.get_job(job_id)
        cred = self.storage.get_credential(job_id)
        if not cred:
            # The 72-hour sign-in limit passed while waiting (the store's TTL removed it first): back to Drafts.
            self._sign_in_expired(job)
            return
        run_no = int(job.get("run", 0)) + 1
        self._job_name = job.get("name", "")
        t = now()
        # Claim it only if it is still Queued and its sign-in is still stored (one conditional write)
        if not self.storage.claim_job(job_id, {"status": "Running", "run": run_no, "startedAt": t, "heartbeatAt": t, "code": "",
                                               "codeDetail": "",
                                               "fixFrom": None, "expiresAt": None, "draftExpiresAt": None, "cancelledBy": "",
                                               "runNow": False, "runAt": None}):  # used: they were for this start
            if not self.storage.get_credential(job_id) and (self.storage.get_job(job_id) or {}).get("status") == "Queued":
                self._sign_in_expired(job)
            return
        beat = _Heartbeat(self, job_id)
        beat.start()
        client: CSpaceClient | None = None
        code, code_detail = "", ""
        created: list[dict] = []
        self._where = "while starting the run"
        try:
            self._start_run(job, run_no, t)
            pw = self.crypto.decrypt("job", cred["token"], {"user": cred["user"], "job": job_id})
            client = self.client_factory(cred["user"], pw)
            del pw
            # Design: five failed requests in a row stop the job; the client sends nothing after the fifth
            client.max_failures_in_a_row = MAX_CONSECUTIVE_SERVER_ERRORS
            code = self._run_rows(job_id, client, run_no, created)
        except JobStop as e:
            code, code_detail = e.code, e.detail
            log.warning("job %s stopped: %s", job_id, e.detail)
        except Exception as e:
            # Design (Finished jobs and error messages): a failure the BMU has no code for is "unknown", with the
            # technical detail. Anything unexpected (DynamoDB, S3, decryption, a bug) ends the run here the normal
            # way, so the job doesn't stay Running until the heartbeat check. The detail names the exception's type
            # and where it happened, never its message, which could hold anything.
            log.exception("job %s: unexpected error %s", job_id, self._where)
            code, code_detail = "unknown", _unexpected(e, self._where)
        finally:
            beat.halt.set()
            # Never keep the password after the run.
            self.storage.delete_credential(job_id)
            if client:
                client.close()
        self._finish(job_id, run_no, code, cred["user"], created, code_detail)

    def _start_run(self, job: dict, run_no: int, started: float) -> None:
        """The run item: who scheduled it and when, and the documents excluded or deleted since the last run.
        A run that starts also commits the fix it came from: its saved originals are no longer needed."""
        job_id = job["id"]
        runs = self.storage.get_runs(job_id)
        since = runs[-1]["startedAt"] if runs else 0
        rows = self.storage.get_rows(job_id)
        disabled = [{"n": r["n"], "file": r["file"], "by": r.get("disabledBy", ""), "at": r.get("disabledAt")}
                    for r in rows if not r.get("include") and (r.get("disabledAt") or 0) >= since
                    and (r.get("result") or {}).get("state") != "Done"]
        deleted = [d for d in job.get("deletedRows") or [] if d.get("at", 0) >= since]
        self.storage.put_run(job_id, {"run": run_no, "scheduledBy": job.get("scheduledBy", ""), "scheduledAt": job.get("queuedAt"),
                                      "startedAt": started, "outcome": "Running", "disabledBefore": disabled, "deletedBefore": deleted})
        if job.get("deletedRows"):  # now in the run item; the job item lists only the deletions since this run
            self.storage.update_job(job_id, {"deletedRows": []})
        self.storage.drop_fix_originals(job_id)
        for r in rows:
            if r.get("supersededKey") or r.get("addedInFix"):
                if r.get("supersededKey"):
                    self._delete_key(r["supersededKey"])
                r.pop("supersededKey", None)
                r.pop("addedInFix", None)
                self.storage.put_row(job_id, r, guard=False)

    def _finish(self, job_id: str, run_no: int, code: str, user: str, created: list[dict], code_detail: str = "") -> None:
        """End a run however it ended: settle the rows, complete the run item and write its audit entry (one
        transaction), then set the job's status and counts. A Completed job gets its 30-day expiry. code_detail:
        the technical detail of a job-level code (design: "technical detail shown on request"), kept on the job and
        the run item."""
        rows = self.storage.get_rows(job_id)
        job_before = self.storage.get_job(job_id) or {}
        group = job_before.get("groupStep") or {}
        if not code and group.get("s") == "failed" and group.get("run") == run_no:
            code = "group_failed"  # the job needs attention; the rows' other steps still ran
            code_detail = f"Creating the group: {group.get('detail') or 'failed'}"
        for r in rows:
            res = r.get("result")
            if res and res.get("state") == "In progress":  # the worker stopped while on this row
                res["state"] = row_state(res, [n for n, _ in plan_steps(self.tenant, r, job_before)])
                # A create may have reached CollectionSpace before its CSID was recorded, so the row stays
                # undeletable (design: Deleting a row) until a later run finishes it.
                res["interrupted"] = run_no
                self.storage.put_row(job_id, r, guard=False)
        work = [r for r in rows if r.get("include")]
        states = [((r.get("result") or {}).get("state") or "Not started") for r in work]
        if code in STOPPED_JOB:
            status = "Failed"
        elif all(st == "Done" for st in states):
            status = "Completed"
        else:
            status = "NeedsAttention"
        job = self.storage.get_job(job_id) or {}
        cancel = job.get("cancelRequested") if code == "cancelled" else None
        if cancel:
            code_detail = f"Cancel requested by {cancel.get('by') or 'a user'}" + (
                f", {datetime.fromtimestamp(float(cancel['at']), sched.TZ):%Y-%m-%d %H:%M} Pacific time" if cancel.get("at") else "")
        code_detail = code_detail if code else ""
        t = now()
        counts = row_counts(rows)
        run = next((x for x in self.storage.get_runs(job_id) if int(x["run"]) == run_no), {"run": run_no})
        cancelled_by, cancelled_at = (cancel or {}).get("by", ""), (cancel or {}).get("at")
        if run.get("auditKey"):
            # An earlier _finish of this run wrote the run item and its audit entry, then stopped before the job
            # item (the heartbeat check is finishing it now): the run as recorded stands, only the job follows it.
            status, code, code_detail = run["outcome"], run.get("code", ""), run.get("codeDetail", "")
            counts, t = run.get("counts") or counts, float(run.get("endedAt") or t)
            cancelled_by, cancelled_at = run.get("cancelledBy", ""), run.get("cancelledAt")
        else:
            run.update(outcome=status, code=code, codeDetail=code_detail, endedAt=t, counts=counts,
                       cancelledBy=cancelled_by, cancelledAt=cancelled_at)
            # Design (Retention and audit): each run's entry holds, for every row, its filename, object number, CSIDs
            # and error codes; for large runs that detail is a JSON object in S3 and the entry points to it.
            detail = [{"n": r["n"], "file": r["file"], "obj": r.get("obj", ""), "idnum": r.get("idnum", ""),
                       "state": (r.get("result") or {}).get("state") or ("Excluded" if not r.get("include") else "Not started"),
                       "csids": {k: v["csid"] for k, v in ((r.get("result") or {}).get("steps") or {}).items() if v.get("csid") and v.get("s") == "done"},
                       "errors": sorted({v["code"] for v in ((r.get("result") or {}).get("steps") or {}).values() if v.get("s") == "failed" and v.get("code")})}
                      for r in rows]
            where: dict = {"rows": detail} if len(detail) <= INLINE_AUDIT_ROWS else \
                {"detailKey": self.storage.put_audit_detail(self.tenant.key, job_id, run_no, detail)}
            # Design (Job data model, Run items): the finished run item and its "Run" audit entry in one transaction,
            # the entry's key on the run item (auditKey). If it fails, neither is written and the job stays Running
            # until the heartbeat check finishes it (worker_stopped), with its entry.
            self.storage.finish_run(self.tenant.key, job_id, run, user,
                                    f"Run {run_no}: {status}" + (f" ({code})" if code else "") +
                                    f" · {counts['done']} done, {counts['partial']} partial, {counts['failed']} failed, "
                                    f"{counts['notStarted']} not started, {counts['disabled']} excluded"
                                    + (f" · cancelled by {cancelled_by}" if cancel else ""),
                                    created if "rows" in where else [], run=run_no, jobName=job.get("name", ""), counts=counts,
                                    codeDetail=code_detail, **where)
        self.storage.update_job(job_id, {
            "status": status, "code": code, "codeDetail": code_detail, "finishedAt": t, "progress": _progress(rows), "counts": counts,
            "currentRow": None, "currentFile": "", "currentStep": "", "currentUpload": None, "cancelRequested": None, "cancelledBy": cancelled_by,
            "runBy": job.get("scheduledBy") or user,
            "expiresAt": t + self.s.completed_days * 86400 if status == "Completed" else None})

    def _run_rows(self, job_id: str, client: CSpaceClient, run_no: int, created: list[dict]) -> str:
        rows = self.storage.get_rows(job_id)
        self._job_media = {((r.get("result") or {}).get("steps") or {}).get("media", {}).get("csid") for r in rows} - {None}
        self._values = _ValueLookups(self.tenant, client, self.lookup_clock)
        self._where = "while checking values before the first document"
        self._check_all_values(client, rows)
        self._where = "while reading the account's permissions before the first document"
        self._perms = self._read_permissions(client)
        self._object_found = {}
        for row in self.storage.get_rows(job_id):
            if not row.get("include") or (row.get("result") or {}).get("state") == "Done":
                continue
            self.maybe_sweep()
            job = self.storage.get_job(job_id)
            if job.get("cancelRequested"):
                return "cancelled"
            self._where = f"at document {row['n']}"
            self.storage.acquire_lock(self.tenant.key, self.owner, self.s.worker_lock_seconds)
            self.storage.update_job(job_id, {"currentRow": row["n"], "currentFile": row["file"], "currentStep": "",
                                             "currentUpload": None, "heartbeatAt": now()})
            self._progress_job = job_id
            err = self.run_row(client, job_id, row, run_no, created)
            if err in JOB_LEVEL:
                e = (row.get("result") or {}).get("error") or {}
                raise JobStop(err, f"Document {row['n']}, step {e.get('step', '?')}: {e.get('detail') or err}")
            self._where = f"at document {row['n']}, after its steps"
            self.storage.update_job(job_id, {"progress": _progress(self.storage.get_rows(job_id))})
        self._where = "while finishing the run"
        return ""

    # ---- one row ------------------------------------------------------------------------------
    def run_row(self, client: CSpaceClient, job_id: str, row: dict, run_no: int, created: list[dict]) -> str:
        """Run a row's unfinished steps. Returns the first error code, or "" when the row is done.

        Each step ends as done (with its CSID), failed (with a catalog code and the technical detail) or
        skipped (naming the step it depended on). A step whose own dependencies are done still runs after
        another step failed: e.g. a failed upload doesn't stop the Relations. Only a job-level error (401,
        inactive account) stops the row at once. Each result is written to the row right after its call.
        A row whose user chose "Stop linking" marks its unfinished object and relation steps not needed.
        """
        res = row.get("result") or {}
        res.update(state="In progress", error=None, run=run_no)
        res.pop("notices", None)
        res.pop("interrupted", None)  # settled again below, or by _finish if this run stops too
        row["result"] = res
        self.storage.put_row(job_id, row, guard=False)
        first_error = ""
        job = self.storage.get_job(job_id) or {}
        plan = plan_steps(self.tenant, row, job)
        planned = {n for n, _ in plan}
        for name, st in (res.get("steps") or {}).items():
            if name not in planned and st.get("s") not in FINISHED:
                st.clear()
                st.update(s="not needed")  # e.g. the job's group was turned off, or the row left it, while fixing
        for name, deps in plan:
            # Design: five requests in a row with a 5xx or no answer stop the job; the row in progress is settled
            # by _finish, and the documents not reached stay not started. Checked before every step, so no step
            # (the group steps included) is skipped by the count.
            if getattr(client, "failures_in_a_row", 0) >= MAX_CONSECUTIVE_SERVER_ERRORS:
                raise JobStop("unavailable", _unavailable(client, row, name))
            self._where = f"at document {row['n']}, step {name}"
            st = _step(row, name)
            if st.get("s") in FINISHED and name != "values":
                continue  # a rerun never repeats a done step (the value check is made again before every run's creates)
            if row.get("skipLink") and name in LINK_STEPS:
                st.clear()
                st.update(s="not needed")
                continue
            blocked = next((d for d in deps if _step(row, d).get("s") != "done"), None)
            if blocked:
                st.clear()
                st.update(s="skipped", after=blocked)
                self.storage.put_row(job_id, row, guard=False)
                continue
            # Design (The job queue): the queue shows the step in progress, and while the file is sent its progress
            self.storage.update_job(job_id, {"currentStep": name, "currentUpload": None})
            try:
                if name == "values":
                    self._check_row(client, job, row)
                    st.clear()
                    st.update(s="done", run=run_no)
                    continue
                if name == "media":
                    self._notice_new_duplicates(client, row)
                if name == "addToGroup":
                    self._add_to_group(client, job_id, row, st, run_no, created)
                    continue
                csid, found = self._do(client, name, row)
                st.clear()
                st.update(s="done", csid=csid, run=run_no)
                if name == "media":
                    self._job_media.add(csid)
                if found:
                    st["found"] = True  # an existing record, not one this job created
                if name != "findObject" and not found and csid:
                    self._record(created, job_id, run_no, {"row": row["n"], "file": row["file"], "step": name, "csid": csid})
                if name == "upload":
                    self._delete_staged(row)
            except CSpaceUnavailable as e:
                # the fifth failure in a row came from an earlier request: this one was never sent, so the step
                # stays as it was, and the job stops (_finish settles the row)
                raise JobStop("unavailable", _unavailable(client, row, name)) from e
            except (CSpaceError, _RowError) as e:
                code, detail = (e.code, e.detail) if isinstance(e, _RowError) else classify(name, e)
                st.clear()
                st.update(s="failed", code=code, detail=detail, run=run_no)
                if name in OBJECT_STEPS:
                    st["obj"] = row.get("obj", "")  # the object number that failed, so the editor knows if it changed
                if not first_error:
                    first_error = code
                    res["error"] = {"code": code, "detail": detail, "step": name}
                if code in JOB_LEVEL:
                    self.storage.put_row(job_id, row, guard=False)
                    break
            finally:
                self.storage.put_row(job_id, row, guard=False)
        if getattr(client, "failures_in_a_row", 0) >= MAX_CONSECUTIVE_SERVER_ERRORS:
            raise JobStop("unavailable", _unavailable(client, row, plan[-1][0]))
        res["state"] = row_state(res)
        if res["state"] == "Done":
            res["error"] = None
        elif not res.get("error"):
            failed = next(((n, st) for n, st in res["steps"].items() if st.get("s") == "failed"), None)
            res["error"] = ({"code": failed[1].get("code", "unknown"), "detail": failed[1].get("detail", ""), "step": failed[0]}
                            if failed else None)
            if not failed and (res["steps"].get("addToGroup") or {}).get("after") == "group":
                g = (self.storage.get_job(job_id) or {}).get("groupStep") or {}
                res["error"] = {"code": "group_failed", "detail": g.get("detail", ""), "step": "addToGroup"}
        self.storage.put_row(job_id, row, guard=False)
        return first_error

    def _record(self, created: list[dict], job_id: str, run_no: int, entry: dict) -> None:
        """A record this run created: kept for the run's audit entry, and written to the CSID index at once."""
        created.append(entry)
        self.storage.index_csid(self.tenant.key, entry["csid"], job=job_id, jobName=self._job_name, run=run_no, row=entry["row"],
                                file=entry["file"], step=entry["step"], recordType=RECORD_TYPE.get(entry["step"], ""))

    # ---- the job's Group (design: Groups; The Group step) ---------------------------------------------
    def _ensure_group(self, client: CSpaceClient, job_id: str, run_no: int, created: list[dict]) -> str | None:
        """The job's Group CSID, creating the Group the first time a row is ready to join it. Reruns reuse
        the recorded CSID and never create a second Group. Returns None if creating it failed in this run."""
        job = self.storage.get_job(job_id) or {}
        g = job.get("groupStep") or {}
        if g.get("s") == "done":
            return g["csid"]
        if g.get("s") == "failed" and g.get("run") == run_no:
            return None
        try:
            csid = client.create_group(group_xml(job.get("groupTitle") or ""))
        except CSpaceUnavailable:
            raise  # nothing was sent: run_row stops the job
        except CSpaceError as e:
            code, detail = classify("group", e)
            if code in JOB_LEVEL:
                # CollectionSpace refused the sign-in, so nothing was created: the row's addToGroup step fails with
                # this code and run_row settles the row and stops the job, as for any other step (not interrupted)
                raise _RowError(code, detail) from e
            self.storage.update_job(job_id, {"groupStep": {"s": "failed", "code": "group_failed", "detail": detail, "run": run_no}})
            return None
        self.storage.update_job(job_id, {"groupStep": {"s": "done", "csid": csid, "run": run_no}})
        self._record(created, job_id, run_no, {"row": 0, "file": "", "step": "group", "csid": csid})
        return csid

    def _add_to_group(self, client: CSpaceClient, job_id: str, row: dict, st: dict, run_no: int, created: list[dict]) -> None:
        """Relate the row's Object to the job's Group, both ways, once per Object: when several rows relate to
        the same Object, only the first adds it; the others record the step as done, pointing to that row."""
        group = self._ensure_group(client, job_id, run_no, created)
        if group is None:
            st.clear()
            st.update(s="skipped", after="group")
            return
        steps = row["result"]["steps"]
        obj = object_csid(steps)
        members = (self.storage.get_job(job_id) or {}).get("groupMembers") or {}
        first = members.get(obj)
        if first and first["n"] != row["n"]:
            st.clear()
            st.update(s="done", csid=first["csid"], sameAs=first["n"], run=run_no)
            return
        pair = []
        for subj, subj_type, tgt, tgt_type in ((group, "Group", obj, "CollectionObject"), (obj, "CollectionObject", group, "Group")):
            existing = client.find_relations(subj, tgt)  # a rerun never creates a duplicate relation
            csid = existing[0] if existing else client.create_relation(relation_xml(subj, subj_type, tgt, tgt_type))
            if not existing:
                self._record(created, job_id, run_no, {"row": row["n"], "file": row["file"], "step": "addToGroup", "csid": csid})
            pair.append(csid)
        st.clear()
        st.update(s="done", csid=pair[0], csid2=pair[1], run=run_no)
        self.storage.update_job(job_id, {"groupMembers": {**members, obj: {"n": row["n"], "csid": pair[0]}}})

    def _notice_new_duplicates(self, client: CSpaceClient, row: dict) -> None:
        """Design: duplicate_at_run. A Media record with the same identification number that appeared after
        scheduling is noted on the row; the row still runs, as it would have after the editor's warning."""
        idn = row.get("idnum") or ""
        if not idn:
            return
        try:
            existing = client.find_media(idn)
        except CSpaceUnavailable:
            raise  # not sent: the job stops (run_row)
        except CSpaceError:
            return  # only a notice; the create itself reports real failures
        known = set(((row.get("lookups") or {}).get("media") or {}).get("csids") or [])
        known |= self._job_media  # Media records this job created aren't news: the editor warned about IDs shared in the job
        new = [c for c in existing if c not in known]
        if new:
            row["result"].setdefault("notices", []).append(
                {"code": "duplicate_at_run", "detail": f"GET media?as=identificationNumber = \"{idn}\" found {', '.join(new[:5])}"})

    def _report_upload(self, sent: int, total: int) -> None:
        """Design (The job queue): the bytes of the document in progress sent to CollectionSpace so far, for the
        queue's upload bar; written at most every UPLOAD_PROGRESS_SECONDS, and at the end."""
        job_id = getattr(self, "_progress_job", None)
        if job_id:
            self.storage.update_job(job_id, {"currentUpload": {"sent": sent, "total": total}})

    # ---- values (design: Job execution; Authority term fields) ----------------------------------------
    def _check_all_values(self, client: CSpaceClient, rows: list[dict]) -> None:
        """The check before the first document: look up every distinct authority term and the languages vocabulary
        that the rows about to create their Media records use (media types come from the tenant's own list). The
        answers are kept for VALUE_CHECK_SECONDS, so the per-row checks (the "values" step, _check_values) of the
        first rows reuse them. A lookup that fails here is asked again by the check of the row that uses it, which
        records the failure on that row; a refused sign-in or five failures in a row stop the job at once."""
        todo = [r for r in rows if r.get("include") and (r.get("result") or {}).get("state") != "Done" and not media_created(r)]
        refs = list(dict.fromkeys(r.get(f) for r in todo for f in AUTHORITY_LABEL if r.get(f)))
        lookups: list = [lambda ref=ref: self._values.term(ref) for ref in refs]
        if any(r.get("language") for r in todo):
            lookups.append(self._values.languages)
        for look in lookups:
            try:  # after five failures in a row the client sends nothing more (CSpaceUnavailable)
                look()
            except CSpaceUnavailable as e:
                raise JobStop("unavailable", _unavailable_before(client)) from e
            except CSpaceError as e:
                code, detail = classify("values", e)
                if code in JOB_LEVEL:
                    raise JobStop(code, f"Checking values before the first document: {detail}") from e

    def _read_permissions(self, client: CSpaceClient) -> dict[str, bool] | None:
        """The account's permissions, read once per run (they can change between submitting and running). If they
        can't be read, the per-document permission check is skipped and a refusal shows up at the step it hits; a
        refused sign-in or five failures in a row stop the job at once."""
        try:
            return client.account_permissions().summary
        except CSpaceUnavailable as e:
            raise JobStop("unavailable", _unavailable_before(client)) from e
        except CSpaceError as e:
            code, detail = classify("values", e)
            if code in JOB_LEVEL:
                raise JobStop(code, f"Reading the account's permissions before the first document: {detail}") from e
            return None

    def _check_row(self, client: CSpaceClient, job: dict, row: dict) -> None:
        """The "values" step (design: Job execution, Steps within a row): the document is checked again just before
        its records are created, as the editor checks it, so that a change in CollectionSpace since the job was
        submitted fails the document with nothing created, not part way. In turn: its values, the account's
        permissions, its Object (per the handling), its staged file. The first problem fails the step; what the
        check can't know (a create CollectionSpace refuses, a failed upload) still fails at its own step."""
        self._check_values(row)
        self._check_permissions(job, row)
        self._check_object(client, row)
        self._check_file(row)

    def _check_permissions(self, job: dict, row: dict) -> None:
        """The handling's permissions and read on the authorities of its terms (rows.permission_checks,
        rows.authority_read_checks: the editor's rules and wording)."""
        if self._perms is None:
            return
        group_exists = (job.get("groupStep") or {}).get("s") == "done"
        blocks = (permission_checks(self.tenant, row, self._perms, bool(job.get("groupOn")), group_exists)
                  + authority_read_checks(row, self._perms))
        if not self._perms.get("media"):
            blocks.insert(0, {"level": "block", "text": "Your account can't create Media records (create on media)."})
        if blocks:
            raise _RowError("no_permission", " ".join(b["text"] for b in blocks))

    def _check_object(self, client: CSpaceClient, row: dict) -> None:
        """The Object as the handling needs it, before the Media record is created: "Link to existing object" needs
        exactly one, "Create new object + link" none, "Link to object (create if missing)" at most one, and create
        on objects when there is none. The search is kept for the Object step, which doesn't repeat it."""
        h = self.tenant.handling_by_id(row["handling"])
        if h.object == "none" or row.get("skipLink") or object_step_ran(row):
            return
        num = row.get("obj") or ""
        found = client.find_objects(num)
        row.setdefault("lookups", {})["object"] = {"value": num, "csids": list(found), "at": int(now())}
        search = f"GET collectionobjects?as=objectNumber = \"{num}\" found {len(found)} object{'' if len(found) == 1 else 's'}"
        if h.object == "create" and found:
            raise _RowError("object_exists", search)
        if h.object != "create" and len(found) > 1:
            raise _RowError("object_ambiguous", search)
        if h.object == "existing" and not found:
            raise _RowError("object_gone", search)
        if h.object == "either" and not found and self._perms is not None and not self._perms.get("objects"):
            raise _RowError("no_permission", f"{search}, and your account can't create Object records (create on collectionobjects).")
        self._object_found[row["n"]] = list(found)

    def _check_file(self, row: dict) -> None:
        """The staged file is still there and is what its name says (the upload step checks again when it runs)."""
        version = (row.get("upload") or {}).get("version") or None
        try:
            wrong = mismatch(row["file"], self.storage.read_head(row["s3Key"], version, HEAD_BYTES))
        except ClientError as e:
            raise _RowError("file_missing", f"S3 GetObject {e.response['Error'].get('Code', '')}: the staged file is gone") from e
        if wrong:
            raise _RowError("file_type_rejected", f"Content check before creating the Media record: {wrong}")

    def _check_values(self, row: dict) -> None:
        """The values part of the check: the row's values again just before its records are created (rows.value_findings,
        as the editor checks them, from lookups at most VALUE_CHECK_SECONDS old). A renamed term or language: the
        row takes its current refName (saved with the step; the Media record is sent with it) and gets a
        term_renamed notice. A value that no longer exists fails the step (value_missing), so nothing is created
        for the row. A lookup that failed raises its CSpaceError, recorded like any failed request."""
        findings = value_findings(self.tenant, row, lambda _field, ref: self._values.term(ref), self._values.languages)
        for f in findings:
            if f["field"] in AUTHORITY_FIELDS and f["kind"] in ("missing", "renamed"):
                # the editor's checks reuse this lookup, so a fix sees at once what the run saw
                current = f.get("current")
                row.setdefault("lookups", {})[f"term:{f['field']}"] = {"value": current or f["value"],
                                                                        "csids": [current] if current else [], "at": int(now())}
        errors = [f["error"] for f in findings if f["kind"] == "unchecked"]
        for e in errors:  # a refused sign-in, or a request not sent after five failures, stops the job first
            if isinstance(e, CSpaceUnavailable) or classify("values", e)[0] in JOB_LEVEL:
                raise e
        missing = [f for f in findings if f["kind"] == "missing"]
        if missing:
            raise _RowError("value_missing", "; ".join(self._missing_text(f) for f in missing))
        if errors:
            raise errors[0]
        for f in findings:  # renamed
            use_current(row, f)
            row["result"].setdefault("notices", []).append(
                {"code": "term_renamed", "detail": f"{f['label']} “{display_name(f['value'])}” → “{display_name(f['current'])}”"})

    def _missing_text(self, f: dict) -> str:
        why = {"deleted": "deleted in CollectionSpace", "404": "not found (404)", "language": "not in the language list",
               "type": f"not in {self.tenant.name}’s media types"}.get(f["why"], f"not a term of {self.tenant.name}’s authorities")
        return f"{f['label']} “{display_name(f['value'])}”: {why}"

    def _delete_staged(self, row: dict) -> None:
        # the staged file and its thumbnail are no longer needed once the file is in CollectionSpace, whose own
        # derivatives are shown from then on
        self._delete_key(row["s3Key"])
        if row.get("thumbKey"):
            self._delete_key(row["thumbKey"])
            row["thumbKey"] = None

    def _delete_key(self, key: str) -> None:
        try:
            self.storage.delete_object(key)
        except ClientError:
            log.warning("could not delete staged file %s", key)

    def _do(self, client: CSpaceClient, name: str, row: dict) -> tuple[str, bool]:
        """Run one step. Returns (CSID, found): found is True when an existing record was used."""
        steps = row["result"]["steps"]
        if name == "media":
            return client.create_media(media_xml(self.tenant, row)), False
        if name in OBJECT_STEPS:
            # Design (Handling per document): "Find object" needs exactly one existing object; "Create object"
            # needs none to exist (an object added since the job was checked fails the row, object_exists);
            # "Find or create object" links to the one it finds and creates it only when there is none.
            # The check just before (Worker._check_object) made this search for a row whose Media record didn't exist
            # yet; a rerun of a row that is past the check searches here.
            found = self._object_found.pop(row["n"], None)
            if found is None:
                found = client.find_objects(row["obj"])
            # the editor's checks reuse this search, so a fix sees what the run saw
            row.setdefault("lookups", {})["object"] = {"value": row["obj"], "csids": list(found), "at": int(now())}
            search = f"GET collectionobjects?as=objectNumber = \"{row['obj']}\" found {len(found)} object{'' if len(found) == 1 else 's'}"
            if name == "createObject":
                if found:
                    raise _RowError("object_exists", search)
                return client.create_object(object_xml(row["obj"])), False
            if len(found) > 1:
                raise _RowError("object_ambiguous", search)
            if found:
                return found[0], True
            if name == "findObject":
                raise _RowError("object_gone", search)
            return client.create_object(object_xml(row["obj"])), False
        media = steps["media"]["csid"]
        if name == "upload":
            # An upload retry targets the existing Media record.
            version = (row.get("upload") or {}).get("version") or None
            try:
                wrong = mismatch(row["file"], self.storage.read_head(row["s3Key"], version, HEAD_BYTES))
            except ClientError as e:
                raise _RowError("file_missing", f"S3 GetObject {e.response['Error'].get('Code', '')}: the staged file is gone") from e
            if wrong:  # design: the worker checks each file's actual type before uploading it
                raise _RowError("file_type_rejected", f"Content check before upload: {wrong}")
            try:
                body = self.storage.open_object(row["s3Key"], version)
            except ClientError as e:
                raise _RowError("file_missing", f"S3 GetObject {e.response['Error'].get('Code', '')}: the staged file is gone") from e
            sent = _UploadProgress(body, int(row.get("size") or 0), self._report_upload)
            try:
                blob = client.upload_file(media, row["file"], sent, row.get("contentType") or "application/octet-stream")
            finally:
                body.close()
            return blob or client.media_blob_csid(media), False
        obj = object_csid(steps)
        if name == "relMediaObject":
            subj, subj_type, tgt, tgt_type = media, "Media", obj, "CollectionObject"
        elif name == "relObjectMedia":
            subj, subj_type, tgt, tgt_type = obj, "CollectionObject", media, "Media"
        else:
            raise ValueError(name)
        existing = client.find_relations(subj, tgt)  # never create a duplicate relation on a rerun
        if existing:
            return existing[0], False
        return client.create_relation(relation_xml(subj, subj_type, tgt, tgt_type)), False


def object_csid(steps: dict) -> str:
    """The CSID of the Object the row's object step found or created."""
    return next(steps[n]["csid"] for n in OBJECT_STEPS if (steps.get(n) or {}).get("s") == "done")


class _RowError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _unavailable(client: CSpaceClient, row: dict, step: str) -> str:
    """The technical detail of a job stopped as "unavailable": the failures in a row and the last one, and where."""
    last = getattr(client, "last_failure", "")
    return (f"{client.failures_in_a_row} requests in a row to CollectionSpace failed" + (f", the last: {last}" if last else "") +
            f"; stopped at document {row['n']}, step {step}")


def _unavailable_before(client: CSpaceClient) -> str:
    """As _unavailable, for a job stopped while checking values before its first document."""
    last = getattr(client, "last_failure", "")
    return (f"{client.failures_in_a_row} requests in a row to CollectionSpace failed" + (f", the last: {last}" if last else "") +
            "; stopped while checking values before the first document")


UPLOAD_PROGRESS_SECONDS = 2.0


class _UploadProgress:
    """A read-only file object around the staged file's S3 stream that counts the bytes read (so sent) while the
    file is streamed to CollectionSpace, and reports them at most every UPLOAD_PROGRESS_SECONDS and when the
    stream ends. It adds no seek or fileno, so the request is sent exactly as it was from the stream itself."""

    def __init__(self, stream, total: int, report, clock=time.monotonic):
        self.stream, self.total, self.report, self.clock = stream, total, report, clock
        self.sent = 0
        self._last = clock()
        self._ended = False

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size) if size is not None and size >= 0 else self.stream.read()
        self.sent += len(data)
        if not data or (self.total and self.sent >= self.total):
            if not self._ended:
                self._ended = True
                self._send()
        elif self.clock() - self._last >= UPLOAD_PROGRESS_SECONDS:
            self._send()
        return data

    def _send(self) -> None:
        self._last = self.clock()
        try:
            self.report(self.sent, self.total or self.sent)
        except Exception:  # progress is only shown; never let it stop the upload
            log.warning("upload progress not recorded", exc_info=True)

    def close(self) -> None:
        self.stream.close()


class _ValueLookups:
    """A run's CollectionSpace lookups for the value checks (design: Job execution), each kept VALUE_CHECK_SECONDS
    from when its answer arrived: authority terms by refName, and the languages vocabulary. A failed lookup isn't
    kept, so the next check asks again. clock: seconds, e.g. time.monotonic."""

    def __init__(self, tenant: Tenant, client: CSpaceClient, clock):
        self.client, self.clock = client, clock
        self.services = {a["service"] for a in tenant.authorities.values()}
        self._terms: dict[str, tuple[float, dict]] = {}
        self._languages: tuple[float, dict[str, str]] | None = None

    def _fresh(self, at: float) -> bool:
        return self.clock() - at < VALUE_CHECK_SECONDS

    def term(self, ref: str) -> dict:
        """{"current": the term's current refName or None, "why": "deleted", "404", "authority" or ""}, as
        rows.value_findings takes it. Raises CSpaceError if the term couldn't be read."""
        hit = self._terms.get(ref)
        if hit and self._fresh(hit[0]):
            return hit[1]
        m = AUTHORITY_REF.match(ref)
        if m and m["service"] in self.services:
            current, why = self.client.authority_term_state(m["service"], m["vocab"], m["short"])
        else:  # not a refName of one of the tenant's authorities: it can't name an existing term
            current, why = None, "authority"
        state = {"current": current, "why": why}
        self._terms[ref] = (self.clock(), state)
        return state

    def languages(self) -> dict[str, str]:
        """The languages vocabulary (rows.language_map). Raises CSpaceError if it couldn't be read."""
        if self._languages and self._fresh(self._languages[0]):
            return self._languages[1]
        terms = language_map(self.client.vocabulary_items("languages"))
        self._languages = (self.clock(), terms)
        return terms


def _unexpected(e: Exception, where: str) -> str:
    """The technical detail of an unexpected error (code "unknown"): the exception's type, for an AWS call its
    operation and error code, and where the run was. Never the message, which could quote a request or a secret."""
    what = type(e).__name__
    if isinstance(e, ClientError):
        what += f" {e.response.get('Error', {}).get('Code', '')} in {e.operation_name}".replace("  ", " ")
    return f"Unexpected {what} {where or 'while running the job'}"


def _progress(rows: list[dict]) -> dict:
    work = [r for r in rows if r.get("include")]
    states = [((r.get("result") or {}).get("state") or "Not started") for r in work]
    return {"total": len(work), "done": states.count("Done"),
            "failed": states.count("Failed") + states.count("Partial")}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    storage = Storage(s)
    if s.create_tables:
        storage.create_tables()
    worker = Worker(s, storage, make_crypto(s),
                    lambda u, p: CSpaceClient(s.cspace_url, u, p, timeout=s.cspace_timeout_seconds, agent="bmu-worker"))
    worker.run_forever()


if __name__ == "__main__":
    main()
