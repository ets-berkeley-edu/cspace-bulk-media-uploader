"""The BMU worker: runs scheduled jobs one row at a time, one job per tenant at a time.

Every step records the CSID it created, so a rerun skips finished steps and never creates a
record twice. The job's password is deleted when the run ends, whatever the outcome.

Run: python -m bmu.worker
"""
from __future__ import annotations

import logging
import socket
import time
import uuid

from botocore.exceptions import ClientError

from .config import Settings, get_settings
from .crypto import Crypto, make_crypto
from .cspace import CSpaceClient, CSpaceError
from .cspace.payloads import media_xml, object_xml, relation_xml
from .storage import Storage, now
from .tenant import Tenant, load_tenant

log = logging.getLogger("bmu.worker")

JOB_LEVEL = {"auth", "account_inactive"}   # stop the whole job
MAX_CONSECUTIVE_SERVER_ERRORS = 5


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


def plan_steps(tenant: Tenant, row: dict) -> list[tuple[str, list[str]]]:
    """A row's steps in order, each with the steps it depends on (design: "Steps within a row").

    Create Media record      depends on nothing
    Find or create Object    depends on nothing
    Upload file (PUT media/{csid}/blob, which creates the Blob record)   depends on Media
    Create Relations, both directions                                    depend on Media and Object
    """
    h = tenant.handling_by_id(row["handling"])
    obj = {"existing": "findObject", "create": "createObject"}.get(h.object)
    steps: list[tuple[str, list[str]]] = [("media", [])]
    if obj:
        steps.append((obj, []))
    steps.append(("upload", ["media"]))
    if obj:
        steps += [("relMediaObject", ["media", obj]), ("relObjectMedia", ["media", obj])]
    return steps


class Worker:
    def __init__(self, settings: Settings, storage: Storage, crypto: Crypto, client_factory, tenant: Tenant | None = None):
        self.s = settings
        self.storage = storage
        self.crypto = crypto
        self.client_factory = client_factory
        self.tenant = tenant or load_tenant(settings.tenant)
        self.owner = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"

    # ---- scheduling ------------------------------------------------------------------------
    def run_forever(self) -> None:
        log.info("worker %s started for tenant %s", self.owner, self.tenant.key)
        while True:
            try:
                if not self.tick():
                    time.sleep(self.s.worker_poll_seconds)
            except Exception:  # keep the worker alive; the job's heartbeat lets another worker resume
                log.exception("worker loop error")
                time.sleep(self.s.worker_poll_seconds)

    def tick(self) -> bool:
        """Run the next job for this tenant, if any. Returns True if a job ran."""
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
        jobs = self.storage.list_jobs(self.tenant.key)
        # A job left Running by a stopped worker is resumed first (its finished steps are skipped).
        running = [j for j in jobs if j["status"] == "Running"]
        if running:
            return running[0]
        queued = sorted((j for j in jobs if j["status"] == "Queued"), key=lambda j: (j.get("queuePos", 0), j.get("queuedAt", 0)))
        return queued[0] if queued else None

    # ---- one job ------------------------------------------------------------------------------
    def run_job(self, job_id: str) -> None:
        job = self.storage.get_job(job_id)
        cred = self.storage.get_credential(job_id)
        if not cred:
            # The 72-hour sign-in limit passed while waiting: back to Drafts, to be scheduled again.
            self.storage.update_job(job_id, {"status": "Draft", "note": "Sign-in expired while waiting in the queue. Schedule it again."},
                                    expect_status=["Queued", "Running"])
            self.storage.audit(self.tenant.key, "Run", "BMU", job_id, "Not run: the job's sign-in expired while it waited.")
            return
        run_no = int(job.get("run", 0)) + 1
        self.storage.update_job(job_id, {"status": "Running", "run": run_no, "startedAt": now(), "code": ""},
                                expect_status=["Queued", "Running"])
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
            # Never keep the password after the run.
            self.storage.delete_credential(job_id)
            if client:
                client.close()
        rows = self.storage.get_rows(job_id)
        work = [r for r in rows if r.get("include")]
        states = [((r.get("result") or {}).get("state") or "Not started") for r in work]
        if code in JOB_LEVEL or code == "unavailable":
            status = "Failed"
        elif all(st == "Done" for st in states):
            status = "Completed"
        else:
            status = "NeedsAttention"
        self.storage.update_job(job_id, {"status": status, "code": code, "finishedAt": now(),
                                         "progress": _progress(rows)})
        self.storage.audit(self.tenant.key, "Run", cred["user"], job_id,
                           f"Run {run_no}: {status}" + (f" ({code})" if code else "") +
                           f" · {states.count('Done')} done, {states.count('Failed') + states.count('Partial')} failed",
                           created)

    def _run_rows(self, job_id: str, client: CSpaceClient, run_no: int, created: list[dict]) -> str:
        server_errors = 0
        for row in self.storage.get_rows(job_id):
            if not row.get("include") or (row.get("result") or {}).get("state") == "Done":
                continue
            job = self.storage.get_job(job_id)
            if job.get("cancelRequested"):
                return "cancelled"
            self.storage.acquire_lock(self.tenant.key, self.owner, self.s.worker_lock_seconds)  # heartbeat
            self.storage.update_job(job_id, {"currentRow": row["n"]})
            err = self.run_row(client, job_id, row, run_no, created)
            if err in JOB_LEVEL:
                raise JobStop(err, f"row {row['n']}: {err}")
            server_errors = server_errors + 1 if err in ("server", "unavailable") else 0
            if server_errors >= MAX_CONSECUTIVE_SERVER_ERRORS:
                raise JobStop("unavailable", "CollectionSpace failed repeatedly")
            self.storage.update_job(job_id, {"progress": _progress(self.storage.get_rows(job_id))})
        return ""

    # ---- one row ------------------------------------------------------------------------------
    def run_row(self, client: CSpaceClient, job_id: str, row: dict, run_no: int, created: list[dict]) -> str:
        """Run a row's unfinished steps. Returns the first error code, or "" when the row is done.

        Each step ends as done (with its CSID), failed (with a reason) or skipped (naming the step it
        depended on). A step whose own dependencies are done still runs after another step failed:
        e.g. a failed upload doesn't stop the Relations. Only a job-level error (401, inactive account)
        stops the row at once. Each result is written to the row right after its call.
        """
        res = row.get("result") or {}
        res.update(state="In progress", error=None, run=run_no)
        row["result"] = res
        self.storage.put_row(job_id, row)
        first_error = ""
        for name, deps in plan_steps(self.tenant, row):
            st = _step(row, name)
            if st.get("s") == "done":
                continue  # a rerun never repeats a done step
            blocked = next((d for d in deps if _step(row, d).get("s") != "done"), None)
            if blocked:
                st.clear()
                st.update(s="skipped", after=blocked)
                self.storage.put_row(job_id, row)
                continue
            try:
                csid = self._do(client, name, row)
                st.clear()
                st.update(s="done", csid=csid, run=run_no)
                if name not in ("findObject",) and csid:
                    created.append({"row": row["n"], "file": row["file"], "step": name, "csid": csid})
                if name == "upload":
                    self._delete_staged(row)
            except (CSpaceError, _RowError) as e:
                st.clear()
                st.update(s="failed", code=e.code, detail=e.detail, run=run_no)
                if not first_error:
                    first_error = e.code
                    res["error"] = {"code": e.code, "detail": e.detail, "step": name}
                if e.code in JOB_LEVEL:
                    self.storage.put_row(job_id, row)
                    break
            finally:
                self.storage.put_row(job_id, row)
        steps = res["steps"]
        if all(st.get("s") == "done" for st in steps.values()):
            res["state"] = "Done"
            res["error"] = None
        elif steps.get("media", {}).get("s") == "done":
            res["state"] = "Partial"
        else:
            res["state"] = "Failed"
        if res["state"] != "Done" and not res.get("error"):
            skipped = next(n for n, st in steps.items() if st.get("s") != "done")
            res["error"] = {"code": "skipped", "detail": f"Step {skipped} didn't run", "step": skipped}
        self.storage.put_row(job_id, row)
        return first_error

    def _delete_staged(self, row: dict) -> None:
        # the staged file is no longer needed once it is in CollectionSpace
        try:
            self.storage.delete_object(row["s3Key"])
        except ClientError:
            log.warning("could not delete staged file for row %s", row["n"])

    def _do(self, client: CSpaceClient, name: str, row: dict) -> str:
        steps = row["result"]["steps"]
        if name == "media":
            return client.create_media(media_xml(self.tenant, row))
        if name == "findObject":
            found = client.find_objects(row["obj"])
            if not found:
                raise _RowError("objnotfound", f"No object {row['obj']} in CollectionSpace")
            if len(found) > 1:
                raise _RowError("objamb", f"Object number {row['obj']} matches {len(found)} objects")
            return found[0]
        if name == "createObject":
            if client.find_objects(row["obj"]):
                raise _RowError("objexists", f"Object {row['obj']} already exists")
            return client.create_object(object_xml(row["obj"]))
        media = steps["media"]["csid"]
        if name == "upload":
            # An upload retry targets the existing Media record.
            try:
                body = self.storage.open_object(row["s3Key"], (row.get("upload") or {}).get("version") or None)
            except ClientError as e:
                raise _RowError("upload", "The staged file is missing; add the file again") from e
            try:
                blob = client.upload_file(media, row["file"], body, row.get("contentType") or "application/octet-stream")
            finally:
                body.close()
            return blob or client.media_blob_csid(media)
        obj = (steps.get("findObject") or steps.get("createObject"))["csid"]
        if name == "relMediaObject":
            subj, subj_type, tgt, tgt_type = media, "Media", obj, "CollectionObject"
        elif name == "relObjectMedia":
            subj, subj_type, tgt, tgt_type = obj, "CollectionObject", media, "Media"
        else:
            raise ValueError(name)
        existing = client.find_relations(subj, tgt)  # never create a duplicate relation on a rerun
        if existing:
            return existing[0]
        return client.create_relation(relation_xml(subj, subj_type, tgt, tgt_type))


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
                    lambda u, p: CSpaceClient(s.cspace_url, u, p, timeout=s.cspace_timeout_seconds))
    worker.run_forever()


if __name__ == "__main__":
    main()
