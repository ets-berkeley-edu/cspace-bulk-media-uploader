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

from botocore.exceptions import ClientError

from .config import Settings, get_settings
from .crypto import Crypto, make_crypto
from .cspace import CSpaceClient, CSpaceError
from .cspace.payloads import group_xml, media_xml, object_xml, relation_xml
from .failures import JOB_LEVEL, classify
from .filetypes import HEAD_BYTES, mismatch
from .storage import Storage, now
from .tenant import Tenant, load_tenant

log = logging.getLogger("bmu.worker")

MAX_CONSECUTIVE_SERVER_ERRORS = 5
INLINE_AUDIT_ROWS = 100  # a run's per-row audit detail goes in the entry up to this many rows, in S3 beyond
RECORD_TYPE = {"media": "Media", "upload": "Blob", "createObject": "CollectionObject", "relMediaObject": "Relation",
               "relObjectMedia": "Relation", "addToGroup": "Relation", "group": "Group"}
STOPPED_JOB = {"unavailable", "worker_stopped"} | JOB_LEVEL  # these end the job as Failed
OBJECT_STEPS = ("findObject", "createObject", "relMediaObject", "relObjectMedia", "addToGroup")
FINISHED = ("done", "not needed")


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

    Create Media record      depends on nothing
    Find or create Object    depends on nothing
    Upload file (PUT media/{csid}/blob, which creates the Blob record)   depends on Media
    Create Relations, both directions                                    depend on Media and Object
    Add the Object to the job's Group (if the job creates one and the row is in it)  depends on the Relations
    """
    h = tenant.handling_by_id(row["handling"])
    obj = {"existing": "findObject", "create": "createObject"}.get(h.object)
    steps: list[tuple[str, list[str]]] = [("media", [])]
    if obj:
        steps.append((obj, []))
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
    def __init__(self, settings: Settings, storage: Storage, crypto: Crypto, client_factory, tenant: Tenant | None = None):
        self.s = settings
        self.storage = storage
        self.crypto = crypto
        self.client_factory = client_factory
        self.tenant = tenant or load_tenant(settings.tenant)
        self.owner = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self._last_sweep = 0.0
        self._last_abandoned_sweep = 0.0
        self._job_media: set[str] = set()  # Media records the running job has created
        self._job_name = ""

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
        """The periodic checks: sign-ins that expired in the queue, expired drafts and fixes, Completed jobs
        past their 30 days, and running jobs whose worker stopped."""
        self.sweep_expired_sign_ins()
        self.sweep_expired_drafts()
        self.sweep_completed()
        self.sweep_stopped_jobs()
        self.sweep_protected_staged()
        if now() - self._last_abandoned_sweep > 3600:  # hourly is plenty for a one-day limit
            self._last_abandoned_sweep = now()
            self.sweep_abandoned_uploads()

    def sweep_expired_sign_ins(self) -> list[str]:
        """A queued job whose saved sign-in reached its time limit leaves the queue for Drafts (design: State
        rules, Sign-in expired while waiting); anyone can schedule it again with their own sign-in."""
        moved = []
        for j in self.storage.list_jobs(self.tenant.key):
            if j["status"] == "Queued" and j.get("credentialExpires") and j["credentialExpires"] < now():
                if self.storage.update_job(j["id"], {"status": "Draft", "queuePos": None, "lastSavedAt": now(),
                                                     "expiresAt": now() + self.s.draft_days * 86400,
                                                     "note": "Sign-in expired while waiting in the queue; schedule it again to run it with your sign-in."},
                                           expect_status="Queued"):
                    self.storage.delete_credential(j["id"])
                    self.storage.audit(self.tenant.key, "Sign-in expired", "BMU", j["id"],
                                       f"“{j.get('name') or 'Untitled job'}” moved to Drafts: its saved sign-in expired while it waited.")
                    moved.append(j["id"])
        return moved

    def sweep_expired_drafts(self) -> list[str]:
        """Drafts past their expiry (design: Drafts, Expiry; State rules, Abandoned fixes). A draft that has
        never run is deleted with its rows and staged files. A fix of a job that has run is reverted: its
        edits are discarded and the job returns to Needs attention or Failed with its rows, run history and
        CSIDs intact. Both are written to the audit log."""
        done = []
        for j in self.storage.list_jobs(self.tenant.key):
            if j["status"] != "Draft" or not j.get("expiresAt") or j["expiresAt"] >= now():
                continue
            if j.get("fixFrom"):
                if self.revert_fix(j):
                    done.append(j["id"])
            elif not j.get("run"):
                if self.storage.update_job(j["id"], {"status": "Expiring"}, expect_status="Draft"):
                    rows = self.storage.delete_job_and_files(j["id"])
                    self.storage.audit(self.tenant.key, "Draft expired", "BMU", j["id"],
                                       f"Deleted “{j.get('name') or 'Untitled job'}” ({len(rows)} documents), "
                                       f"{self.s.draft_days} days after it was last saved; it had never run.")
                    done.append(j["id"])
        return done

    def revert_fix(self, job: dict) -> bool:
        """Discard a fix's edits: put back every row it changed, remove documents it added, and return the
        job to the state it came from. Rows deleted during the fix stay deleted (deleting is permanent)."""
        fix = job["fixFrom"]
        if not self.storage.update_job(job["id"], {"status": "Reverting"}, expect_status="Draft"):
            return False
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
        self.storage.update_job(job["id"], {"status": fix["status"], "code": fix.get("code", ""), "fixFrom": None,
                                            "expiresAt": None, "note": ""})
        self.storage.audit(self.tenant.key, "Fix reverted", "BMU", job["id"],
                           f"Fix and reschedule of “{job.get('name') or 'Untitled job'}” was not finished within "
                           f"{self.s.draft_days} days; the edits were discarded and the job returned to "
                           f"{'Needs attention' if fix['status'] == 'NeedsAttention' else fix['status']} with its history.")
        return True

    def sweep_completed(self) -> list[str]:
        """Completed jobs are removed 30 days after they finish (their run audit entries stay for a year)."""
        gone = []
        for j in self.storage.list_jobs(self.tenant.key):
            if j["status"] == "Completed" and j.get("expiresAt") and j["expiresAt"] < now():
                if self.storage.update_job(j["id"], {"status": "Expiring"}, expect_status="Completed"):
                    rows = self.storage.delete_job_and_files(j["id"])
                    self.storage.audit(self.tenant.key, "Job expired", "BMU", j["id"],
                                       f"Removed “{j.get('name') or 'Untitled job'}” ({len(rows)} documents), "
                                       f"{self.s.completed_days} days after it completed.")
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
            if j["status"] == "Running" and (j.get("heartbeatAt") or j.get("startedAt") or 0) < limit:
                if self.storage.update_job(j["id"], {"status": "Stopping"}, expect_status="Running"):
                    self.storage.delete_credential(j["id"])
                    self._finish(j["id"], int(j.get("run", 0)), "worker_stopped", j.get("scheduledBy") or "BMU", [])
                    stopped.append(j["id"])
        return stopped

    def tick(self) -> bool:
        """Run the next job for this tenant, if any. Returns True if a job ran."""
        if now() - self._last_sweep > 60:
            self._last_sweep = now()
            self.sweep()
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
        # A job left Running by a worker that stopped is not resumed: the heartbeat check stops it as
        # "worker_stopped", and a user reschedules it (its finished steps are skipped).
        queued = sorted((j for j in self.storage.list_jobs(self.tenant.key) if j["status"] == "Queued"),
                        key=lambda j: (j.get("queuePos", 0), j.get("queuedAt", 0)))
        return queued[0] if queued else None

    # ---- one job ------------------------------------------------------------------------------
    def run_job(self, job_id: str) -> None:
        job = self.storage.get_job(job_id)
        cred = self.storage.get_credential(job_id)
        if not cred:
            # The 72-hour sign-in limit passed while waiting: back to Drafts, to be scheduled again.
            self.storage.update_job(job_id, {"status": "Draft", "note": "Sign-in expired while waiting in the queue. Schedule it again."},
                                    expect_status=["Queued"])
            self.storage.audit(self.tenant.key, "Run", "BMU", job_id, "Not run: the job's sign-in expired while it waited.")
            return
        run_no = int(job.get("run", 0)) + 1
        self._job_name = job.get("name", "")
        t = now()
        if not self.storage.update_job(job_id, {"status": "Running", "run": run_no, "startedAt": t, "heartbeatAt": t, "code": "",
                                                "fixFrom": None, "expiresAt": None, "cancelledBy": ""}, expect_status="Queued"):
            return
        self._start_run(job, run_no, t)
        beat = _Heartbeat(self, job_id)
        beat.start()
        client: CSpaceClient | None = None
        code = ""
        created: list[dict] = []
        try:
            pw = self.crypto.decrypt("job", cred["token"], {"user": cred["user"], "job": job_id})
            client = self.client_factory(cred["user"], pw)
            del pw
            code = self._run_rows(job_id, client, run_no, created)
        except JobStop as e:
            code = e.code
            log.warning("job %s stopped: %s", job_id, e.detail)
        finally:
            beat.halt.set()
            # Never keep the password after the run.
            self.storage.delete_credential(job_id)
            if client:
                client.close()
        self._finish(job_id, run_no, code, cred["user"], created)

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
        self.storage.drop_fix_originals(job_id)
        for r in rows:
            if r.get("supersededKey") or r.get("addedInFix"):
                if r.get("supersededKey"):
                    self._delete_key(r["supersededKey"])
                r.pop("supersededKey", None)
                r.pop("addedInFix", None)
                self.storage.put_row(job_id, r, guard=False)

    def _finish(self, job_id: str, run_no: int, code: str, user: str, created: list[dict]) -> None:
        """End a run however it ended: settle the rows, set the job's status and counts, complete the run
        item and write the audit entry. A Completed job gets its 30-day expiry."""
        rows = self.storage.get_rows(job_id)
        job_before = self.storage.get_job(job_id) or {}
        group = job_before.get("groupStep") or {}
        if not code and group.get("s") == "failed" and group.get("run") == run_no:
            code = "group_failed"  # the job needs attention; the rows' other steps still ran
        for r in rows:
            res = r.get("result")
            if res and res.get("state") == "In progress":  # the worker stopped while on this row
                res["state"] = row_state(res, [n for n, _ in plan_steps(self.tenant, r, job_before)])
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
        t = now()
        counts = row_counts(rows)
        self.storage.update_job(job_id, {
            "status": status, "code": code, "finishedAt": t, "progress": _progress(rows), "counts": counts,
            "currentRow": None, "currentFile": "", "cancelRequested": None, "cancelledBy": (cancel or {}).get("by", ""),
            "runBy": job.get("scheduledBy") or user,
            "expiresAt": t + self.s.completed_days * 86400 if status == "Completed" else None})
        run = next((x for x in self.storage.get_runs(job_id) if int(x["run"]) == run_no), {"run": run_no})
        run.update(outcome=status, code=code, endedAt=t, counts=counts,
                   cancelledBy=(cancel or {}).get("by", ""), cancelledAt=(cancel or {}).get("at"))
        self.storage.put_run(job_id, run)
        # Design (Retention and audit): each run's entry holds, for every row, its filename, object number, CSIDs and
        # error codes; for large runs that detail is a JSON object in S3 and the entry points to it.
        detail = [{"n": r["n"], "file": r["file"], "obj": r.get("obj", ""), "idnum": r.get("idnum", ""),
                   "state": (r.get("result") or {}).get("state") or ("Excluded" if not r.get("include") else "Not started"),
                   "csids": {k: v["csid"] for k, v in ((r.get("result") or {}).get("steps") or {}).items() if v.get("csid") and v.get("s") == "done"},
                   "errors": sorted({v["code"] for v in ((r.get("result") or {}).get("steps") or {}).values() if v.get("s") == "failed" and v.get("code")})}
                  for r in rows]
        where: dict = {"rows": detail} if len(detail) <= INLINE_AUDIT_ROWS else \
            {"detailKey": self.storage.put_audit_detail(self.tenant.key, job_id, run_no, detail)}
        self.storage.audit(self.tenant.key, "Run", user, job_id,
                           f"Run {run_no}: {status}" + (f" ({code})" if code else "") +
                           f" · {counts['done']} done, {counts['partial']} partial, {counts['failed']} failed, "
                           f"{counts['notStarted']} not started, {counts['disabled']} excluded"
                           + (f" · cancelled by {cancel.get('by')}" if cancel else ""),
                           created if "rows" in where else [], run=run_no, jobName=job.get("name", ""), counts=counts, **where)

    def _run_rows(self, job_id: str, client: CSpaceClient, run_no: int, created: list[dict]) -> str:
        server_errors = 0
        self._job_media = {((r.get("result") or {}).get("steps") or {}).get("media", {}).get("csid")
                           for r in self.storage.get_rows(job_id)} - {None}
        for row in self.storage.get_rows(job_id):
            if not row.get("include") or (row.get("result") or {}).get("state") == "Done":
                continue
            job = self.storage.get_job(job_id)
            if job.get("cancelRequested"):
                return "cancelled"
            self.storage.acquire_lock(self.tenant.key, self.owner, self.s.worker_lock_seconds)
            self.storage.update_job(job_id, {"currentRow": row["n"], "currentFile": row["file"], "heartbeatAt": now()})
            err = self.run_row(client, job_id, row, run_no, created)
            if err in JOB_LEVEL:
                raise JobStop(err, f"row {row['n']}: {err}")
            server_errors = server_errors + 1 if err == "server_error" else 0
            if server_errors >= MAX_CONSECUTIVE_SERVER_ERRORS:
                raise JobStop("unavailable", "CollectionSpace failed repeatedly")
            self.storage.update_job(job_id, {"progress": _progress(self.storage.get_rows(job_id))})
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
            st = _step(row, name)
            if st.get("s") in FINISHED:
                continue  # a rerun never repeats a done step
            if row.get("skipLink") and name in OBJECT_STEPS:
                st.clear()
                st.update(s="not needed")
                continue
            blocked = next((d for d in deps if _step(row, d).get("s") != "done"), None)
            if blocked:
                st.clear()
                st.update(s="skipped", after=blocked)
                self.storage.put_row(job_id, row, guard=False)
                continue
            try:
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
            except (CSpaceError, _RowError) as e:
                code, detail = (e.code, e.detail) if isinstance(e, _RowError) else classify(name, e)
                st.clear()
                st.update(s="failed", code=code, detail=detail, run=run_no)
                if name in ("findObject", "createObject"):
                    st["obj"] = row.get("obj", "")  # the object number that failed, so the editor knows if it changed
                if not first_error:
                    first_error = code
                    res["error"] = {"code": code, "detail": detail, "step": name}
                if code in JOB_LEVEL:
                    self.storage.put_row(job_id, row, guard=False)
                    break
            finally:
                self.storage.put_row(job_id, row, guard=False)
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
        except CSpaceError as e:
            code, detail = classify("group", e)
            if code in JOB_LEVEL:
                raise JobStop(code, detail) from e
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
        obj = (steps.get("findObject") or steps.get("createObject"))["csid"]
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
        except CSpaceError:
            return  # only a notice; the create itself reports real failures
        known = set(((row.get("lookups") or {}).get("media") or {}).get("csids") or [])
        known |= self._job_media  # Media records this job created aren't news: the editor warned about IDs shared in the job
        new = [c for c in existing if c not in known]
        if new:
            row["result"]["notices"] = [{"code": "duplicate_at_run",
                                         "detail": f"GET media?as=identificationNumber = \"{idn}\" found {', '.join(new[:5])}"}]

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
        if name in ("findObject", "createObject"):
            # Find or create: a rerun, or an Object added since scheduling, links to the existing record.
            found = client.find_objects(row["obj"])
            if len(found) > 1:
                raise _RowError("object_ambiguous", f"GET collectionobjects?as=objectNumber = \"{row['obj']}\" found {len(found)} objects")
            if found:
                return found[0], True
            if name == "findObject":
                raise _RowError("object_gone", f"GET collectionobjects?as=objectNumber = \"{row['obj']}\" found no object")
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
            try:
                blob = client.upload_file(media, row["file"], body, row.get("contentType") or "application/octet-stream")
            finally:
                body.close()
            return blob or client.media_blob_csid(media), False
        obj = (steps.get("findObject") or steps.get("createObject"))["csid"]
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


class _RowError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


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
