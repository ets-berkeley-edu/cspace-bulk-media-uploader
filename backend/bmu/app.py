"""BMU web API (FastAPI). The Vue app calls these endpoints; the worker runs scheduled jobs."""
from __future__ import annotations

import copy
import hashlib
import logging
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import demo
from . import logsafe
from . import schedule as sched
from .config import Settings, get_settings
from .crypto import Crypto, make_crypto
from .cspace import CSpaceClient, CSpaceError
from .failures import catalog
from .filetypes import content_type, unsupported
from .rows import (PROBLEM_TEXT, apply_edit, can_replace_file, check_rows, clean_filename, collision_checks, created_records,
                   describe_deletion, edit_problem, is_locked, media_created, new_row, worst)
from .storage import RowChanged, Storage, draft_expiry, expiry_of, now
from .thumbnails import MAX_BROWSER_BYTES, TIFF_EXTENSIONS, NotAnImage, make_thumbnail, tiff_thumbnail_step
from .tenant import Tenant, load_tenant

log = logging.getLogger("bmu.app")

CSRF_HEADER = "x-bmu"
# Only drafts are scheduled. A job that needs attention or failed goes to Drafts first (Fix and reschedule).
RESCHEDULABLE = ("Draft",)
FIXABLE = ("NeedsAttention", "Failed")

ClientFactory = Callable[[str, str], CSpaceClient]

RUN_AT_GRACE_SECONDS = 60  # a job's own run time may be this far in the past (the browser picks whole minutes)

AUTOCOMPLETE_PAGE = 20  # the first page of each source, as the CollectionSpace UI fetches

# Vocabularies the BMU offers whole (their terms change rarely, so they are cached for an hour).
VOCABULARIES = ("languages",)
VOCAB_CACHE_SECONDS = 3600
_VOCAB_CACHE: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def vocabulary_terms(tenant: str, client: CSpaceClient, name: str, fresh: bool = False) -> list[dict]:
    """A vocabulary's terms, sorted by display name, from the cache (an hour) or CollectionSpace. The Language
    picker offers them and the row checks compare rows' languages with them; fresh=True (scheduling) reads the
    vocabulary again."""
    key = (tenant, name)
    hit = _VOCAB_CACHE.get(key)
    if hit and not fresh and now() - hit[0] < VOCAB_CACHE_SECONDS:
        return hit[1]
    terms = sorted(client.vocabulary_items(name), key=lambda t: t["displayName"].lower())
    _VOCAB_CACHE[key] = (now(), terms)
    return terms


class Services:
    """Everything a request needs; replaced in tests."""

    def __init__(self, settings: Settings, storage: Storage, crypto: Crypto, client_factory: ClientFactory,
                 clock: Callable[[], float] | None = None):
        self.settings = settings
        self.storage = storage
        self.crypto = crypto
        self.client_factory = client_factory
        self.tenant: Tenant = load_tenant(settings.tenant)
        # The time the job schedule is judged by (design: Job scheduling); tests replace it to move time.
        self.clock: Callable[[], float] = clock or now
        self.demo = demo.DemoState(settings)  # Demo tools (BMU_DEMO only); tests replace its HTTP clients
        # The queued and running jobs with their rows, by tenant, kept a few seconds (see _queue_rows)
        self.queue_rows: dict[str, tuple[float, list[tuple[dict, list[dict]]]]] = {}


def create_app(services: Services | None = None) -> FastAPI:
    app = FastAPI(title="New BMU (prototype)", docs_url="/api/docs", openapi_url="/api/openapi.json")
    logsafe.install()  # uvicorn has set up its logging by the time the app is created
    if services is None:
        s = get_settings()
        storage = Storage(s)
        if s.create_tables:
            storage.create_tables()
        services = Services(s, storage, make_crypto(s),
                            lambda u, p: CSpaceClient(s.cspace_url, u, p, timeout=s.cspace_timeout_seconds))
    app.state.svc = services

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Cookie-authenticated API: state-changing requests must carry a custom header, which a
        # cross-site form can't send (the session cookie is also SameSite=Strict).
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": "Missing X-BMU header"}, status_code=403)
        resp = await call_next(request)
        # The built app's files have content hashes in their names, so they never change; everything else is fresh.
        immutable = request.url.path.startswith("/assets/") and resp.status_code == 200
        resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-store")
        return resp

    @app.exception_handler(RowChanged)
    async def row_changed(request: Request, exc: RowChanged):
        return JSONResponse({"detail": f"Document {exc.n} changed while you were working on it (for example its upload "
                                       "finished). Nothing was saved; try again."}, status_code=409)

    _routes(app)
    demo.register(app)

    static = services.settings.static_dir
    if static and Path(static).is_dir():
        app.mount("/assets", StaticFiles(directory=Path(static) / "assets"), name="assets")

        root = Path(static).resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            # A file of the built app (favicon and the like), else the app itself, which routes in the browser. Only
            # files inside the build: the path arrives decoded, so "..%2f" or "%2fetc" must not reach other files.
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "Not found")
            f = (root / path).resolve()
            return FileResponse(f if path and f.is_relative_to(root) and f.is_file() else root / "index.html")

    return app


# ---- dependencies ------------------------------------------------------------------------
def svc(request: Request) -> Services:
    return request.app.state.svc


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Session(BaseModel):
    key: str
    user: str
    tenant: str
    perms: dict[str, bool]
    password_token: str
    scheduler: bool = False  # a BMU scheduler when signing in (design: Job scheduling)

    def client(self, s: Services) -> CSpaceClient:
        pw = s.crypto.decrypt("session", self.password_token, {"user": self.user, "session": self.key})
        return s.client_factory(self.user, pw)


def current_session(request: Request, s: Services = Depends(svc)) -> Session:
    """The signed-in session. Design (Login and session): an idle timeout (30 minutes) and an absolute one
    (8 hours) bound how long a password sits in the session store. Background refreshes (X-BMU-Poll) don't count
    as activity, so an open tab left alone still signs out."""
    token = request.cookies.get(s.settings.cookie_name)
    item = s.storage.get_session(_hash(token)) if token else None
    if not item:
        raise HTTPException(401, "Please sign in with your CollectionSpace account.")
    t = now()
    last = float(item.get("lastSeen") or item.get("expires", t) - s.settings.session_hours * 3600)
    if t - last > s.settings.session_idle_minutes * 60:
        s.storage.end_session(item["PK"], item.get("tenant"))  # with its hold on any draft it was editing
        raise HTTPException(401, f"You were signed out after {s.settings.session_idle_minutes} minutes without activity. "
                                 "Please sign in again; everything you changed was saved.")
    if request.headers.get("x-bmu-poll") != "1" and t - last > 60:
        s.storage.touch_session(item["PK"], t)
    return Session(key=item["PK"], user=item["user"], tenant=item["tenant"], perms=item["perms"],
                   password_token=item["password"], scheduler=bool(item.get("scheduler")))


EDIT_REFUSED = ("Your CollectionSpace account can't create and update Media records, so it can't create or edit jobs. "
                "You can still view them.")


def can_edit(perms: dict[str, bool]) -> bool:
    """Creating or editing a job needs create and update on media, since every job creates Media records and
    attaches files to them (design: Authentication, permissions)."""
    return bool(perms.get("media")) and bool(perms.get("mediaUpdate", True))


def editor_session(sess: Session = Depends(current_session)) -> Session:
    """The signed-in session of a request that creates or changes a job: every such endpoint takes this instead
    of current_session, so a user who may only view jobs is refused before anything is read or written."""
    if not can_edit(sess.perms):
        raise HTTPException(403, EDIT_REFUSED)
    return sess


SCHEDULER_REFUSED = "Only users with the BMU_Scheduler role can change the schedule or the job queue."
CANCEL_REFUSED = "Only a BMU scheduler or the person who submitted the job can cancel its run."


def _read_scheduler(s: Services, client: CSpaceClient, user: str) -> bool:
    """Whether the account is a BMU scheduler for this tenant: one of its CollectionSpace roles is one of the
    tenant's scheduler_roles (design: Job scheduling). Raises CSpaceError if the roles can't be read."""
    roles = client.account_roles()
    return s.tenant.is_scheduler(roles.tenant_id, roles.role_names)


def _scheduler_now(s: Services, sess: Session) -> bool:
    """Read the session user's roles again, with their credentials, and keep the session's flag up to date, so
    a role removed in CollectionSpace takes effect at once. A refused roles request means not a scheduler; a
    CollectionSpace that doesn't answer (or no longer accepts the sign-in) is reported as such."""
    client = sess.client(s)
    try:
        scheduler = _read_scheduler(s, client, sess.user)
    except CSpaceError as e:
        if e.code in ("auth", "unavailable", "server"):
            raise _cspace_http(e)
        log.warning("reading the roles of %s failed (%s); not a scheduler", sess.user, e)
        scheduler = False
    finally:
        client.close()
    if scheduler != sess.scheduler:
        s.storage.update_session_scheduler(sess.key, scheduler)
    return scheduler


def scheduler_session(sess: Session = Depends(current_session), s: Services = Depends(svc)) -> Session:
    """The signed-in session of a request that changes the schedule or the job queue: only BMU schedulers,
    checked against CollectionSpace on every such request (design: Job scheduling). Separate from editing
    rights: a scheduler who can't create Media records can still manage the schedule and the queue."""
    if not _scheduler_now(s, sess):
        raise HTTPException(403, SCHEDULER_REFUSED)
    return sess.model_copy(update={"scheduler": True})


def _job_or_404(s: Services, sess: Session, job_id: str) -> dict:
    job = s.storage.get_job(job_id)
    if not job or job["tenant"] != sess.tenant:
        raise HTTPException(404, "No such job")
    return job


def _editable(job: dict, sess: "Session | None" = None) -> None:
    """Changes are made to drafts only, and (with sess) only by the session that is editing the draft."""
    if job["status"] != "Draft":
        raise HTTPException(409, f"The job is {job['status']}; only jobs being prepared can be changed.")
    if sess is not None and job.get("editingSession") != sess.key:
        who = job.get("editingBy")
        raise HTTPException(409, {"code": "not_editing", "editingBy": who or "",
                                  "message": f"{who} is editing this draft now, so your change wasn't saved. Everything you "
                                             "changed before was saved." if who else "Open this draft for editing first."})


def _draft_days(s: "Services", job: dict | None) -> int:
    """30 days, or 7 if any document is a protected file (design: Drafts, Expiry)."""
    return s.settings.draft_days_for(job)


def _saved(s: "Services", sess: "Session", job_id: str) -> None:
    """A change to a draft was saved: record who saved it and restart its expiry."""
    job = s.storage.get_job(job_id)
    s.storage.mark_saved(job_id, sess.user, sess.key, _draft_days(s, job), fix=bool((job or {}).get("fixFrom")))


def _keep_original(s: "Services", job: dict, row: dict) -> None:
    """While a job is being fixed, keep each row as it was before its first change, so an abandoned fix can
    be reverted (design: State rules, Abandoned fixes). Rows added during the fix are simply removed then."""
    if job.get("fixFrom") and not row.get("addedInFix"):
        s.storage.save_fix_original(job["id"], copy.deepcopy(row))


def _note_include(row: dict, before: bool, user: str) -> None:
    """Record who excluded a row from the job and when; the next run lists it (design: Excluding documents)."""
    if before and not row.get("include"):
        row["disabledBy"], row["disabledAt"] = user, now()
    elif row.get("include"):
        row.pop("disabledBy", None)
        row.pop("disabledAt", None)


def _complete_if_clean(s: "Services", sess: "Session", job_id: str) -> bool:
    """A job that has run becomes Completed, with its 30-day expiry, as soon as every row is done or
    excluded, also when that happens in a draft (design: Job states). With no rows left, it is deleted."""
    job = s.storage.get_job(job_id)
    if not job or job["status"] != "Draft" or not job.get("run"):
        return False
    rows = s.storage.get_rows(job_id)
    if not rows:
        _delete_job(s, sess, job, [])
        return True
    if any(r.get("include") and (r.get("result") or {}).get("state") != "Done" for r in rows):
        return False
    if not s.storage.update_job(job_id, {"status": "Completed", "code": "", "codeDetail": "", "note": "", "fixFrom": None,
                                         "draftExpiresAt": None,
                                         "expiresAt": now() + s.settings.completed_days * 86400}, expect_status="Draft"):
        return False
    s.storage.clear_editing(job_id)
    s.storage.drop_fix_originals(job_id)
    s.storage.audit(sess.tenant, "Completed", sess.user, job_id,
                    f"“{job['name'] or 'Untitled job'}” completed: every document is done or excluded.")
    return True


DELETE_SKIPPED = {
    "created": "It already created records in CollectionSpace, so it can't be deleted; use Exclude instead.",
    "changed": "It changed while deleting it, so it wasn't deleted. Reload and try again.",
    "missing": "It's no longer in the job.",
}


def _delete_rows(s: "Services", sess: "Session", job: dict, rows: list[dict]) -> tuple[list[dict], dict[int, str]]:
    """Delete documents of a draft (design: Deleting a row): each one's staged file, replacement and thumbnail, and
    a "Row deleted" audit entry. Excluded documents can be deleted too; documents that created something in
    CollectionSpace can't. Returns the rows deleted, and for the others why not ({n: "created" | "changed"}). The
    caller records the deletions on the job and rechecks it (_after_rows_deleted).

    Deleting many at once stays quick: one request per document (the row, the job's count and the audit entry in one
    transaction), then the files of all of them together (storage.delete_objects)."""
    job_id, name = job["id"], job["name"] or "Untitled job"
    deleted: list[dict] = []
    problems: dict[int, str] = {}
    for row in rows:
        if is_locked(row):
            problems[row["n"]] = "created"
            continue
        entry = {"tenant": sess.tenant, "type": "Row deleted", "user": sess.user,
                 "detail": f"Deleted document {row['n']} ({row['file']}) from “{name}”; it had created nothing in CollectionSpace."}
        # One conditional write: only if the row is as checked and the job is still this session's draft
        if s.storage.delete_row_if_unchanged(job_id, row, sess.key, audit=entry):
            deleted.append(row)
        else:
            problems[row["n"]] = "changed"
    # Their staged files, replacements and thumbnails
    s.storage.delete_objects(k for row in deleted for k in (row.get("s3Key"), row.get("supersededKey"), row.get("thumbKey")))
    if job.get("fixFrom"):  # deleting is permanent, even if the fix is abandoned (originals exist only during a fix)
        for row in deleted:
            s.storage.drop_fix_original(job_id, row["n"])
    return deleted, problems


def _after_rows_deleted(s: "Services", sess: "Session", job: dict, rows: list[dict]) -> dict:
    """After documents were deleted: a job that has run lists them for its next run; with no documents left the
    job is deleted (run or not); a job that has run may now be Completed; otherwise the other rows are rechecked
    once. Returns {"others": rows whose checks changed, "jobStatus"?: the job's status if it's no longer a Draft}."""
    job_id = job["id"]
    if job.get("run"):  # the next run lists the documents deleted since the last one
        current = s.storage.get_job(job_id) or job
        at = now()
        s.storage.update_job(job_id, {"deletedRows": (current.get("deletedRows") or []) +
                                      [{"n": r["n"], "file": r["file"], "by": sess.user, "at": at} for r in rows]})
    if not s.storage.get_rows(job_id):  # design: deleting the last document deletes the job, run or not
        fresh = s.storage.get_job(job_id)
        if fresh:
            _delete_job(s, sess, fresh, [])
        return {"others": [], "jobStatus": "Deleted"}
    if _complete_if_clean(s, sess, job_id):
        return {"others": [], "jobStatus": (s.storage.get_job(job_id) or {}).get("status", "Deleted")}
    return {"others": _recheck(s, sess, job_id, targets=set())["changed"]}


SIMULATORS = {"localhost", "127.0.0.1", "fakecspace", "fake"}


def real_cspace(url: str) -> bool:
    """Whether the BMU talks to a real CollectionSpace server, not the local simulator (backend/fakecspace)."""
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "") not in SIMULATORS


def _upload_form(s: "Services", key: str, size: int, content_type: str) -> dict:
    """The presigned POST the browser sends a file with (design: Browser uploads). In a demo with a browser upload
    speed set (Demo tools), it goes through the web app instead, which passes it on to S3 at that speed."""
    form = s.storage.presign_upload(key, size, content_type)
    return demo.route_upload(s, form)


def _me(s: "Services", user: str, perms: dict, scheduler: bool) -> dict:
    """What the browser needs about the signed-in user and the app: the tenant's settings, the user's permissions,
    and the per-file size limit, so the page skips files over it before asking to add them (design: Browser uploads)."""
    return {"user": user, "tenant": s.tenant.public_summary(), "perms": perms, "scheduler": scheduler,
            "maxFileBytes": s.settings.max_file_bytes}


def _delete_job(s: "Services", sess: "Session", job: dict, rows: list[dict],
                statuses: tuple[str, ...] = ("Draft", "Queued", *FIXABLE)) -> None:
    """Delete a job and its staged files. Records its runs created stay in CollectionSpace; the audit entry
    lists every one, by row and record type, so they can still be found and finished there.
    First one write marks it Deleting (with who deleted it) and removes its sign-in, so the worker can't start it
    meanwhile; if the job changed since it was read (claimed, or taken over), nothing is deleted. The complete
    audit entry is written next, before anything is deleted, so a deletion that stops part way never loses the
    list of CSIDs; the sweep then only removes what is left (see Worker.sweep_unfinished_deletions)."""
    statuses = list(statuses)
    if job.get("status") not in statuses or not s.storage.begin_delete(job["id"], statuses, sess.key, sess.user):
        raise HTTPException(409, "This job changed while deleting it (it may have started running); nothing was deleted. "
                                 "Reload and try again.")
    created = created_records(rows, job)
    s.storage.audit_job_deleted(sess.tenant, job["id"], sess.user, describe_deletion(job, len(rows), created), created,
                                jobName=job.get("name", ""))
    s.storage.delete_job_and_files(job["id"])


QUEUE_FIELDS = ("runNow", "runAt", "held")  # a scheduler's settings for one queued job (design: Job scheduling)


class QueueView:
    """The plans of a tenant's queued and running jobs, computed once per request from the schedule, the jobs
    and the clock (bmu.schedule.plans, the same order the worker picks jobs in)."""

    def __init__(self, s: "Services", tenant: str, jobs: list[dict] | None = None):
        self.schedule = sched.load(s.storage, tenant)
        self.now = s.clock()
        self.jobs = s.storage.list_jobs(tenant) if jobs is None else jobs
        self.always = s.settings.always_run_time
        self.plans = sched.plans(self.jobs, self.schedule, self.now, self.always)

    def plan(self, job: dict) -> dict:
        """The job's plan; for a job read after the list (it just changed), with it put into the list."""
        if next((j for j in self.jobs if j["id"] == job["id"]), None) != job:
            jobs = [j for j in self.jobs if j["id"] != job["id"]] + [job]
            return sched.plans(jobs, self.schedule, self.now, self.always)[job["id"]]
        return self.plans[job["id"]]


def _public(job: dict, sess: "Session", s: "Services | None" = None, view: QueueView | None = None) -> dict:
    """A job as the API shows it: whether this session is its editor, not the other session's key. A queued or
    running job also shows its scheduling (runNow, runAt, held) and its plan: when it is to start and how many
    jobs go first (design: Job scheduling); pass the services (or a QueueView for many jobs) for that."""
    out = {k: v for k, v in job.items() if k != "editingSession" and k not in QUEUE_FIELDS}
    out["editingByYou"] = bool(job.get("editingSession")) and job.get("editingSession") == sess.key
    if job.get("fixFrom"):  # a fix's expiry is kept in draftExpiresAt; the UI reads every draft's as expiresAt
        out["expiresAt"] = expiry_of(job)
    if job.get("status") in ("Queued", "Running") and (s is not None or view is not None):
        view = view or QueueView(s, job["tenant"])
        out.update(runNow=bool(job.get("runNow")), runAt=job.get("runAt"), held=job.get("held") or None, plan=view.plan(job))
    return out


def _cspace_http(e: CSpaceError) -> HTTPException:
    if e.code == "auth":
        return HTTPException(401, "CollectionSpace didn't accept your sign-in. Please sign in again.")
    if e.code in ("unavailable", "server"):
        return HTTPException(503, "CollectionSpace isn't responding. Try again in a few minutes.")
    return HTTPException(502, f"CollectionSpace request failed ({e.code}).")


# ---- request bodies ----------------------------------------------------------------------
class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class NewJob(BaseModel):
    name: str = Field(default="", max_length=200)


class JobPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    groupOn: bool | None = None  # "Create a group of this job's objects"
    groupTitle: str | None = Field(default=None, max_length=200)


class FileSpec(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1)
    type: str = Field(default="", max_length=200)
    # Read from the image by the browser before the upload (design: Pre-filling rows from filenames and EXIF)
    exifDate: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    orientation: Literal["portrait", "landscape", "square", ""] = ""


class AddFiles(BaseModel):
    files: list[FileSpec] = Field(min_length=1)


class FormRequest(BaseModel):
    size: int = Field(ge=1)  # the size of the file the browser is about to send


class BulkEdit(BaseModel):
    rows: list[int] = Field(min_length=1, max_length=1000)
    changes: dict[str, Any] = Field(min_length=1)


class RowList(BaseModel):
    rows: list[int] = Field(min_length=1, max_length=1000)


class MoveJob(BaseModel):
    toIndex: int = Field(ge=0)  # new place among the queued jobs, 0 = next to run


class OpenDraft(BaseModel):
    takeOverSince: float | None = None  # take over from the editor the user was warned about


class CheckRequest(BaseModel):
    rows: list[int] | None = None  # the rows to look up in CollectionSpace; None: any row whose lookup is stale


class ScheduleBody(BaseModel):
    """The tenant's schedule (design: Job scheduling); validated by bmu.schedule.validate. The time zone is fixed."""
    days: list[int] = Field(max_length=7)
    start: str = Field(max_length=5)
    end: str = Field(default="", max_length=5)


class PauseBody(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class OnOff(BaseModel):
    on: bool


class RunAt(BaseModel):
    at: float | None  # epoch seconds, or None to clear the job's own run time




def _routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/env")
    def environment(s: Services = Depends(svc)):
        """Which environment this is, for the sign-in page and the header (no sign-in needed): its label, and
        whether it talks to a real CollectionSpace (records created there stay), so the page can say so."""
        return {"label": s.settings.env_label, "realCollectionSpace": real_cspace(s.settings.cspace_url)}

    # ---- sign-in (Basic Auth checked against CollectionSpace) ----------------------------
    @app.post("/api/login")
    def login(body: LoginBody, response: Response, s: Services = Depends(svc)):
        client = s.client_factory(body.username, body.password)
        try:
            perms = client.account_permissions()
            try:  # design (Job scheduling): a user whose roles can't be read is not a scheduler; sign-in goes on
                scheduler = _read_scheduler(s, client, body.username)
            except CSpaceError as e:
                log.warning("reading the roles of %s at sign-in failed (%s); not a scheduler", body.username, e)
                scheduler = False
        except CSpaceError as e:
            if e.code in ("auth", "forbidden"):
                raise HTTPException(401, "CollectionSpace didn't accept that username and password.")
            raise _cspace_http(e)
        finally:
            client.close()
        token = secrets.token_urlsafe(32)
        key = _hash(token)
        expires = now() + s.settings.session_hours * 3600
        s.storage.put_session(key, {
            "user": body.username, "tenant": s.tenant.key, "perms": perms.summary, "scheduler": scheduler,
            "expires": int(expires), "lastSeen": now(),
            "password": s.crypto.encrypt("session", body.password, {"user": body.username, "session": key}),
        })
        response.set_cookie(s.settings.cookie_name, token, httponly=True, secure=s.settings.cookie_secure, samesite="strict",
                            max_age=int(s.settings.session_hours * 3600), path="/")
        return _me(s, body.username, perms.summary, scheduler)

    @app.post("/api/logout")
    def logout(response: Response, request: Request, s: Services = Depends(svc)):
        token = request.cookies.get(s.settings.cookie_name)
        if token:
            key = _hash(token)
            item = s.storage.get_session(key)
            # stop editing any draft this session had open, so others can edit it without taking over
            s.storage.end_session(key, item["tenant"] if item else None)
        response.delete_cookie(s.settings.cookie_name, path="/")
        return {"ok": True}

    @app.get("/api/failures")
    def failures(sess: Session = Depends(current_session)):
        """The failure catalog: what the UI says about each failure code (design: Finished jobs and error messages)."""
        return {"failures": catalog()}

    @app.get("/api/me")
    def me(sess: Session = Depends(current_session), s: Services = Depends(svc)):
        return _me(s, sess.user, sess.perms, sess.scheduler)

    # ---- authority autocomplete (existing terms only) ------------------------------------
    @app.get("/api/authorities")
    def authorities(field: str, q: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        if len(q.strip()) < s.tenant.autocomplete["min_length"]:
            return {"terms": []}
        kinds = s.tenant.authority_fields.get(field)
        if not kinds:
            raise HTTPException(400, "Not an authority field")
        # As in the CollectionSpace UI, sources the user can't read are dropped silently.
        readable = {"personauthorities": sess.perms.get("readPersons", True), "orgauthorities": sess.perms.get("readOrgs", True)}
        kinds = [k for k in kinds if k in s.tenant.authorities]  # a source not set up for this tenant is skipped, as in the UI
        if not kinds:
            return {"terms": [], "total": 0}
        kinds = [k for k in kinds if readable.get(s.tenant.authorities[k]["service"], True)]
        if not kinds:
            return {"terms": [], "total": 0, "message": "Your CollectionSpace account can't read the Person or Organization authorities, so it can't search them."}
        client = sess.client(s)
        try:
            terms, total, more = [], 0, False
            for kind in kinds:
                a = s.tenant.authorities[kind]
                found, n = client.search_terms_page(a["service"], a["vocabulary"], q.strip(), AUTOCOMPLETE_PAGE)
                terms += [{**t, "source": kind} for t in found]
                total += n
                more = more or n > len(found)
            return {"terms": terms, "total": total, "more": more}
        except CSpaceError as e:
            raise _cspace_http(e)
        finally:
            client.close()

    # ---- dates: CollectionSpace's own parser, for the preview under the Date field ------------
    @app.get("/api/dates/parse")
    def parse_date(text: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        text = text.strip()
        if not text:
            return {"ok": True, "group": {}}
        client = sess.client(s)
        try:
            group = client.parse_date(text[:200])
        except CSpaceError as e:
            raise _cspace_http(e)
        finally:
            client.close()
        return {"ok": group is not None, "group": group or {}}

    # ---- vocabularies (languages): every term, for the repeating Language picker ---------------
    @app.get("/api/vocabularies/{name}")
    def vocabulary(name: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        if name not in VOCABULARIES:
            raise HTTPException(404, "No such vocabulary")
        client = sess.client(s)
        try:
            return {"terms": vocabulary_terms(sess.tenant, client, name)}
        except CSpaceError as e:
            raise _cspace_http(e)
        finally:
            client.close()

    # ---- jobs --------------------------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs(sess: Session = Depends(current_session), s: Services = Depends(svc)):
        view = QueueView(s, sess.tenant)
        return {"jobs": [_public(j, sess, view=view) for j in view.jobs]}

    @app.post("/api/jobs")
    def create_job(body: NewJob, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        return _public(s.storage.create_job(sess.tenant, sess.user, body.name.strip(), sess.key, s.settings.draft_days), sess)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        rows = s.storage.get_rows(job_id)
        return {"job": _public(job, sess, s), "rows": rows, "runs": s.storage.get_runs(job_id),
                "created": created_records(rows, job)["counts"]}

    # ---- Fix and reschedule (design: Fixing a job after a run; Rescheduling after a run) --------------
    @app.post("/api/jobs/{job_id}/fix")
    def fix(job_id: str, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """Fix and reschedule (or Reschedule): a job that needs attention or failed moves to Drafts, locked to
        you. Its rows keep their results; scheduling it queues a rerun of only what's unfinished. A fix not
        scheduled within 30 days of its last change is reverted."""
        job = _job_or_404(s, sess, job_id)
        t = now()
        if not s.storage.update_job(job_id, {"status": "Draft", "fixFrom": {"status": job["status"], "code": job.get("code", ""),
                                                                            "codeDetail": job.get("codeDetail", ""),
                                                                            "run": job.get("run", 0)},
                                             "note": "", "lastSavedBy": sess.user, "lastSavedAt": t,
                                             **draft_expiry({"fixFrom": True}, t + _draft_days(s, job) * 86400)},
                                    expect_status=list(FIXABLE)):
            now_job = s.storage.get_job(job_id) or {}
            who = now_job.get("editingBy")
            raise HTTPException(409, f"{who} is already fixing this job; it's in Drafts." if who else
                                f"The job is {now_job.get('status')}; only jobs that need attention or failed can be fixed.")
        s.storage.open_draft(job_id, sess.user, sess.key)
        return _public(s.storage.get_job(job_id), sess)

    # ---- the job queue (design: The job queue; State rules) ---------------------------------------
    @app.post("/api/jobs/{job_id}/move")
    def move_job(job_id: str, body: MoveJob, sess: Session = Depends(scheduler_session), s: Services = Depends(svc)):
        """Change a queued job's place in the queue (BMU schedulers only; design: Job scheduling). Running jobs
        stay first and can't be moved."""
        job = _job_or_404(s, sess, job_id)
        s.queue_rows.pop(sess.tenant, None)  # the queue is about to change: read it again (see _queue_rows)
        if job["status"] != "Queued":
            raise HTTPException(409, "Only queued jobs can be moved.")
        queued = sorted((j for j in s.storage.list_jobs(sess.tenant) if j["status"] == "Queued"), key=sched.queue_key)
        order = [j for j in queued if j["id"] != job_id]
        place = min(body.toIndex, len(order))
        order.insert(place, job)
        for i, j in enumerate(order, start=1):  # positions 1..n in the new order
            if j.get("queuePos") != i:
                s.storage.update_job(j["id"], {"queuePos": i}, expect_status="Queued")
        if [j["id"] for j in queued] != [j["id"] for j in order]:
            s.storage.audit(sess.tenant, "Queue reordered", sess.user, job_id,
                            f"Moved “{job.get('name') or 'Untitled job'}” to place {place + 1} of {len(order)} in the queue.")
        view = QueueView(s, sess.tenant)
        by_id = {j["id"]: j for j in view.jobs}
        return {"jobs": [_public(by_id[j["id"]], sess, view=view) for j in order if j["id"] in by_id]}

    @app.post("/api/jobs/{job_id}/edit")
    def edit_queued(job_id: str, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """Edit a queued job: it leaves the queue for Drafts, locked to you, and its saved sign-in is deleted.
        It goes to the end of the queue when it is scheduled again."""
        job = _job_or_404(s, sess, job_id)
        s.queue_rows.pop(sess.tenant, None)  # the queue is about to change: read it again (see _queue_rows)
        if not s.storage.update_job(job_id, {"status": "Draft", "queuePos": None, "note": "", "lastSavedBy": sess.user,
                                             "lastSavedAt": now(), **draft_expiry(job, now() + _draft_days(s, job) * 86400)},
                                    expect_status="Queued"):
            raise HTTPException(409, f"The job is {s.storage.get_job(job_id)['status']}; only queued jobs can be edited this way.")
        s.storage.delete_credential(job_id)
        s.storage.open_draft(job_id, sess.user, sess.key)
        s.storage.audit(sess.tenant, "Moved to Drafts", sess.user, job_id,
                        f"Took “{job['name']}” out of the queue to edit it; its saved sign-in was deleted.")
        return _public(s.storage.get_job(job_id), sess)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_run(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Cancel run: the worker finishes the document in progress, then stops (Needs attention, cancelled).
        Design (Job scheduling): BMU schedulers, or the person who submitted the job."""
        job = _job_or_404(s, sess, job_id)
        if job.get("scheduledBy") != sess.user and not _scheduler_now(s, sess):
            raise HTTPException(403, CANCEL_REFUSED)
        if not s.storage.update_job(job_id, {"cancelRequested": {"by": sess.user, "at": now()}}, expect_status="Running"):
            raise HTTPException(409, "Only a running job can be cancelled.")
        s.storage.audit(sess.tenant, "Run cancelled", sess.user, job_id,
                        f"Cancelled the run of “{job.get('name') or 'Untitled job'}”; it stops after the document in progress.")
        return _public(s.storage.get_job(job_id), sess, s)

    # ---- drafts: open for editing (one editor at a time), take over, close, save -------------
    @app.post("/api/jobs/{job_id}/open")
    def open_draft(job_id: str, body: OpenDraft | None = None, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        if job["status"] != "Draft":
            raise HTTPException(409, f"The job is {job['status']}; only drafts can be edited.")
        take = body.takeOverSince if body else None
        if not s.storage.open_draft(job_id, sess.user, sess.key, take):
            job = s.storage.get_job(job_id)
            raise HTTPException(409, {"code": "locked", "editingBy": job.get("editingBy", ""), "editingSince": job.get("editingSince"),
                                      "message": f"{job.get('editingBy')} is editing this draft."})
        if take is not None:
            s.storage.audit(sess.tenant, "Draft taken over", sess.user, job_id,
                            f"Took over “{job['name']}” from {job.get('editingBy')}.")
        return _public(s.storage.get_job(job_id), sess)

    @app.post("/api/jobs/{job_id}/close")
    def close_draft(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        if job.get("editingSession") == sess.key:
            _complete_if_clean(s, sess, job_id)
        s.storage.close_draft(job_id, sess.key)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/save")
    def save_draft(job_id: str, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """Save draft: every change is already saved; this confirms it and restarts the draft's expiry. A job
        that has run and has every document done or excluded becomes Completed."""
        _editable(_job_or_404(s, sess, job_id), sess)
        _saved(s, sess, job_id)
        _complete_if_clean(s, sess, job_id)
        return _public(s.storage.get_job(job_id), sess)

    @app.patch("/api/jobs/{job_id}")
    def patch_job(job_id: str, body: JobPatch, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """The job header: its name, and the job's group (design: Groups). Turning the group on leaves the Group
        title as it was, empty for a new job: the user types it or fills it with one click (the job name or a
        timestamp, in the editor); it never follows the job name. Once the Group exists in CollectionSpace, it
        can't be turned off or renamed."""
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        fields: dict[str, Any] = {}
        name = job.get("name", "") if body.name is None else body.name.strip()
        if body.name is not None:
            fields["name"] = name
        group_made = (job.get("groupStep") or {}).get("s") == "done"
        if (body.groupOn is not None and body.groupOn != bool(job.get("groupOn"))) or \
           (body.groupTitle is not None and body.groupTitle.strip() != job.get("groupTitle", "")):
            if group_made:
                raise HTTPException(409, "The job's group already exists in CollectionSpace, so it can't be turned off or renamed here.")
        on = bool(job.get("groupOn")) if body.groupOn is None else body.groupOn
        if body.groupOn is not None:
            fields["groupOn"] = on
        if body.groupTitle is not None:
            fields["groupTitle"] = body.groupTitle.strip()
        if fields:
            s.storage.update_job(job_id, fields, expect_status="Draft")
        _saved(s, sess, job_id)
        rc = _recheck(s, sess, job_id, targets=set()) if "groupOn" in fields else None
        return {**_public(s.storage.get_job(job_id), sess), **({"rows": rc["changed"]} if rc else {})}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """Design: Deleting a job. Drafts, queued jobs and jobs that need attention or failed; not a running
        job (cancel it first) or a draft someone else is editing. Allowed even if its runs created records:
        they stay in CollectionSpace (the BMU never deletes them) and the audit entry lists them."""
        job = _job_or_404(s, sess, job_id)
        s.queue_rows.pop(sess.tenant, None)  # the queue is about to change: read it again (see _queue_rows)
        if job["status"] == "Running":
            raise HTTPException(409, "This job is running. Cancel the run first.")
        if job["status"] == "Completed":
            raise HTTPException(409, "Completed jobs are removed on their own 30 days after they finish.")
        if job["status"] not in ("Draft", "Queued", *FIXABLE):
            raise HTTPException(409, f"The job is {job['status']} and can't be deleted now.")
        if job.get("editingSession") and job["editingSession"] != sess.key:
            raise HTTPException(409, f"{job.get('editingBy')} is editing this draft, so it can't be deleted.")
        _delete_job(s, sess, job, s.storage.get_rows(job_id))
        return {"ok": True}

    # ---- files: presigned direct upload to S3 -------------------------------------------------
    @app.post("/api/jobs/{job_id}/files")
    def add_files(job_id: str, body: AddFiles, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        _saved(s, sess, job_id)
        if job["rowCount"] + len(body.files) > s.settings.max_rows:
            raise HTTPException(413, f"A job holds at most {s.settings.max_rows} documents.")
        too_big = [f.name for f in body.files if f.size > s.settings.max_file_bytes]
        if too_big:
            raise HTTPException(413, f"Too large: {', '.join(too_big[:5])}")
        # Design (Supported file types): the browser skips other files; the server refuses them too, before signing
        refused = unsupported([f.name for f in body.files])
        if refused:
            raise HTTPException(422, refused)
        try:  # design: filenames are cleaned once, on the server, when the browser first reports them
            names = [clean_filename(f.name) for f in body.files]
        except ValueError as e:
            raise HTTPException(422, str(e))
        new = []
        for f, name in zip(body.files, names):
            row = new_row(s.tenant, name, f.size, content_type(name) or f.type, date=f.exifDate, orientation=f.orientation)
            if job.get("fixFrom"):
                row["addedInFix"] = True  # an abandoned fix removes it again
            new.append(row)
        rows = s.storage.add_rows(job_id, new)
        return {"rows": [{**r, "uploadForm": _upload_form(s, r["s3Key"], f.size, r["contentType"])}
                         for r, f in zip(rows, body.files)]}

    @app.post("/api/jobs/{job_id}/rows/{n}/upload-form")
    def upload_form(job_id: str, n: int, body: FormRequest, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """A new presigned POST for a document whose file hasn't been sent yet (design: Browser uploads, "Sign"). Each
        form expires after about 15 minutes, so the page asks for a fresh one just before sending a file whose form
        got old while it waited its turn. Same staged key, size and type; the row isn't changed."""
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        row = s.storage.get_row(job_id, n) or _404()
        if (row.get("upload") or {}).get("s") == "done":
            raise HTTPException(409, "This document's file is already uploaded.")
        if not row.get("s3Key"):
            raise HTTPException(409, "This document has no file waiting to be uploaded.")
        if body.size != row["size"]:
            raise HTTPException(422, f"This isn't the file this document was added with ({row.get('fileOriginal') or row['file']}): "
                                     "the size is different. Use Retry to choose it again.")
        return {"uploadForm": _upload_form(s, row["s3Key"], row["size"], row["contentType"])}

    @app.post("/api/jobs/{job_id}/rows/{n}/uploaded")
    def uploaded(job_id: str, n: int, background: BackgroundTasks, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        _editable(_job_or_404(s, sess, job_id))
        row = s.storage.get_row(job_id, n) or _404()
        head = s.storage.head_object(row["s3Key"])
        if head and head["ContentLength"] == row["size"]:
            row["upload"] = {"s": "done", "version": head.get("VersionId") or ""}
        else:
            row["upload"] = {"s": "failed", "reason": "missing" if not head else "size mismatch"}
        s.storage.put_row(job_id, row)
        result = _recheck_after_change(s, sess, job_id, n)
        if row["upload"]["s"] == "done" and row["file"].rsplit(".", 1)[-1].lower() in TIFF_EXTENSIONS:
            background.add_task(tiff_thumbnail_step, s.storage, job_id, n)  # the thumbnail step (a Lambda in AWS)
        return result

    # ---- thumbnails (design: User interface, Thumbnails) -------------------------------------------
    @app.post("/api/jobs/{job_id}/rows/{n}/thumbnail")
    async def put_thumbnail(job_id: str, n: int, request: Request, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """The thumbnail the browser made from the local file (JPEG and PNG). It is decoded and written again
        here, so nothing but pixels is kept; none is stored for a protected file."""
        _editable(_job_or_404(s, sess, job_id))
        row = s.storage.get_row(job_id, n) or _404()
        body = await request.body()
        if len(body) > MAX_BROWSER_BYTES:
            raise HTTPException(413, "The thumbnail is too large.")
        if row.get("protected"):
            return {"stored": False}
        try:
            jpeg = make_thumbnail(body)
        except NotAnImage:
            raise HTTPException(422, "Not an image.")
        return {"stored": s.storage.store_thumbnail(job_id, n, jpeg)}

    @app.get("/api/jobs/{job_id}/rows/{n}/thumbnail")
    def get_thumbnail(job_id: str, n: int, size: str = "small", sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """A document's thumbnail, after checking the session and tenant: CollectionSpace's own derivative once
        the file is there (fetched with your credentials, so CollectionSpace's permissions apply, protected or
        not), otherwise the staged thumbnail. The browser never gets an S3 URL."""
        _job_or_404(s, sess, job_id)
        row = s.storage.get_row(job_id, n) or _404()
        upload = ((row.get("result") or {}).get("steps") or {}).get("upload") or {}
        headers = {"Cache-Control": "private, max-age=300"}
        if upload.get("s") == "done" and upload.get("csid"):
            client = sess.client(s)
            try:
                data, ctype = client.derivative(upload["csid"], "Medium" if size == "large" else "Thumbnail")
            except CSpaceError as e:
                raise HTTPException(404 if e.status in (403, 404) else 502, "No thumbnail from CollectionSpace.")
            finally:
                client.close()
            return Response(content=data, media_type=ctype, headers=headers)
        if row.get("protected") or not row.get("thumbKey"):
            raise HTTPException(404, "No thumbnail.")
        data = s.storage.get_bytes(row["thumbKey"])
        if data is None:
            raise HTTPException(404, "No thumbnail.")
        return Response(content=data, media_type="image/jpeg", headers=headers)

    @app.post("/api/jobs/{job_id}/rows/{n}/replace-file")
    def replace_file(job_id: str, n: int, body: FileSpec, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """A replacement file for a document whose file didn't reach CollectionSpace: rejected or lost after its Media
        record was created (the rerun uploads it to that Media record), or found gone or of the wrong type by the
        document's check, before anything was created. The browser uploads it like any file."""
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        row = s.storage.get_row(job_id, n) or _404()
        if not can_replace_file(row):
            raise HTTPException(409, "Only a document whose file didn't reach CollectionSpace in the last run takes a "
                                     "replacement file.")
        if body.size > s.settings.max_file_bytes:
            raise HTTPException(413, f"Too large: {body.name}")
        if (refused := unsupported([body.name])):
            raise HTTPException(422, refused)
        try:
            name = clean_filename(body.name)
        except ValueError as e:
            raise HTTPException(422, str(e))
        _saved(s, sess, job_id)
        _keep_original(s, job, row)
        if job.get("fixFrom") and "supersededKey" not in row:
            row["supersededKey"] = row.get("s3Key")  # kept until the rerun starts, in case the fix is abandoned
        elif row.get("s3Key"):
            s.storage.delete_object(row["s3Key"])  # an earlier replacement, never used
        if row.get("thumbKey"):
            s.storage.delete_object(row["thumbKey"])
            row["thumbKey"] = None
        row.update(file=name, fileOriginal=name, size=body.size, contentType=content_type(name) or body.type, upload={"s": "pending"},
                   s3Key=s.storage.staging_key(job_id, n), replacedFor=(row.get("result") or {}).get("run"))
        s.storage.put_row(job_id, row)
        return {"row": row, "uploadForm": _upload_form(s, row["s3Key"], body.size, row["contentType"])}

    @app.post("/api/jobs/{job_id}/rows/{n}/retry-upload")
    def retry_upload(job_id: str, n: int, body: FileSpec, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """Retry a document's upload that failed or never finished (design: Browser uploads, "Upload failed" with
        Retry and Remove). The same file is sent again to a new staged key; its row keeps every field."""
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        row = s.storage.get_row(job_id, n) or _404()
        if (row.get("upload") or {}).get("s") == "done":
            raise HTTPException(409, "This document's file is already uploaded.")
        if media_created(row):
            raise HTTPException(409, "This document's Media record exists; use Replace file instead.")
        try:
            name = clean_filename(body.name)
        except ValueError as e:
            raise HTTPException(422, str(e))
        if name.lower() != (row.get("fileOriginal") or row["file"]).lower():
            raise HTTPException(422, f"Choose the same file, {row.get('fileOriginal') or row['file']}. To add a different file, add it as a new document.")
        if body.size > s.settings.max_file_bytes:
            raise HTTPException(413, f"Too large: {body.name}")
        _saved(s, sess, job_id)
        for key in {row.get("s3Key"), row.get("thumbKey")} - {None, ""}:
            s.storage.delete_object(key)  # whatever part of the failed upload arrived, and its old thumbnail
        row["thumbKey"] = None
        row.update(size=body.size, contentType=content_type(name) or body.type or row.get("contentType", ""), upload={"s": "pending"},
                   s3Key=s.storage.staging_key(job_id, n))
        s.storage.put_row(job_id, row)
        return {"row": row, "uploadForm": _upload_form(s, row["s3Key"], body.size, row["contentType"])}

    @app.post("/api/jobs/{job_id}/rows/{n}/upload-failed")
    def upload_failed(job_id: str, n: int, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        _editable(_job_or_404(s, sess, job_id))
        row = s.storage.get_row(job_id, n) or _404()
        row["upload"] = {"s": "failed", "reason": "browser"}
        s.storage.put_row(job_id, row)
        return _recheck_after_change(s, sess, job_id, n)

    # ---- rows -----------------------------------------------------------------------------------
    @app.patch("/api/jobs/{job_id}/rows/{n}")
    def edit_row(job_id: str, n: int, changes: dict[str, Any], sess: Session = Depends(editor_session),
                 s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        _saved(s, sess, job_id)
        row = s.storage.get_row(job_id, n) or _404()
        others = [r["file"] for r in s.storage.get_rows(job_id) if r["n"] != n] if "file" in changes else []
        before = copy.deepcopy(row)
        try:
            apply_edit(s.tenant, row, changes, others)
        except ValueError as e:
            raise HTTPException(422, str(e))
        _note_include(row, bool(before.get("include")), sess.user)
        _keep_original(s, job, before)
        s.storage.put_row(job_id, row)
        return _recheck_after_change(s, sess, job_id, n)

    @app.post("/api/jobs/{job_id}/rows/bulk")
    def bulk_edit(job_id: str, body: BulkEdit, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """The bulk-change panel: the same changes to many rows. Never applied partially: if any target row
        can't take a change it would actually change, nothing is saved."""
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        _saved(s, sess, job_id)
        if "file" in body.changes:
            raise HTTPException(422, "Documents are renamed one at a time.")
        by_n = {r["n"]: r for r in s.storage.get_rows(job_id)}
        missing = [n for n in body.rows if n not in by_n]
        if missing:
            raise HTTPException(404, f"No such documents: {', '.join(map(str, missing[:10]))}")
        targets = [by_n[n] for n in dict.fromkeys(body.rows)]
        problems = {r["n"]: p for r in targets if (p := edit_problem(r, body.changes))}
        if problems:
            n, p = next(iter(problems.items()))
            raise HTTPException(409, {"message": f"{len(problems)} of the {len(targets)} documents can't take this change "
                                                 f"(document {n}: {PROBLEM_TEXT[p]}) Nothing was changed.",
                                      "rows": list(problems)})
        originals = copy.deepcopy(targets)
        edited = []
        for r in targets:
            try:
                apply_edit(s.tenant, r, body.changes)
            except ValueError as e:
                raise HTTPException(422, f"{e} Nothing was changed.")
            _note_include(r, bool(originals[len(edited)].get("include")), sess.user)
            edited.append(r)
        for o in originals:
            _keep_original(s, job, o)
        s.storage.put_rows_all_or_none(job_id, edited, originals)
        rc = _recheck(s, sess, job_id, targets={r["n"] for r in edited})
        changed = {r["n"] for r in edited} | {r["n"] for r in rc["changed"]}
        return {"rows": [r for r in rc["rows"] if r["n"] in changed]}

    @app.delete("/api/jobs/{job_id}/rows/{n}")
    def delete_row(job_id: str, n: int, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        _saved(s, sess, job_id)
        row = s.storage.get_row(job_id, n) or _404()
        problem = _delete_rows(s, sess, job, [row])[1].get(n)
        if problem == "created":
            raise HTTPException(409, "This document already created records in CollectionSpace, so it can't be deleted. "
                                     "Check Exclude to have the BMU ignore it.")
        if problem == "changed":
            raise HTTPException(409, "This document or job changed while deleting it; nothing was deleted. Reload and try again.")
        return {"ok": True, **_after_rows_deleted(s, sess, job, [row])}

    @app.post("/api/jobs/{job_id}/rows/delete")
    def delete_rows(job_id: str, body: RowList, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        """Delete selected documents: every listed document that may be deleted, with the same rules as deleting
        one (design: Deleting a row). Documents that created something in CollectionSpace, that changed meanwhile
        or that are gone already are skipped, each with its reason; the others are deleted."""
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        _saved(s, sess, job_id)
        by_n = {r["n"]: r for r in s.storage.get_rows(job_id)}
        asked = list(dict.fromkeys(body.rows))
        deleted, problems = _delete_rows(s, sess, job, [by_n[n] for n in asked if n in by_n])
        problems.update({n: "missing" for n in asked if n not in by_n})
        skipped = [{"n": n, "file": by_n[n]["file"] if n in by_n else "", "code": problems[n], "reason": DELETE_SKIPPED[problems[n]]}
                   for n in asked if n in problems]
        out = _after_rows_deleted(s, sess, job, deleted) if deleted else {"others": []}
        return {"deleted": [r["n"] for r in deleted], "skipped": skipped, **out}

    # ---- checks and scheduling --------------------------------------------------------------------
    @app.post("/api/jobs/{job_id}/check")
    def check(job_id: str, body: CheckRequest | None = None, sess: Session = Depends(current_session),
              s: Services = Depends(svc)):
        """The editor's checks: after files are added (a batch of rows), and when a job is opened (stale rows).
        Every row is re-evaluated; only the given rows (or rows with stale lookups) query CollectionSpace."""
        _job_or_404(s, sess, job_id)
        targets = set(body.rows) if body and body.rows is not None else None
        r = _recheck(s, sess, job_id, targets=targets)
        return {"rows": r["rows"], "counts": r["counts"]}

    @app.post("/api/jobs/{job_id}/schedule")
    def schedule(job_id: str, sess: Session = Depends(editor_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        s.queue_rows.pop(sess.tenant, None)  # the queue is about to change: read it again (see _queue_rows)
        if job["status"] not in RESCHEDULABLE:
            raise HTTPException(409, f"The job is {job['status']} and can't be submitted.")
        if job["status"] == "Draft":
            _editable(job, sess)  # only the draft's editor schedules it
        if job.get("groupOn") and not (job.get("groupTitle") or "").strip():
            raise HTTPException(409, "Enter a group title, or turn off the job's group.")
        # Roles can change during a session: fetch the permissions again, then check the whole job afresh.
        sess = _refresh_permissions(s, sess)
        if not can_edit(sess.perms):
            raise HTTPException(403, EDIT_REFUSED)
        result = _recheck(s, sess, job_id, targets=None, refresh=True)
        work = [r for r in result["rows"] if r.get("include") and (r.get("result") or {}).get("state") != "Done"]
        if not work:
            raise HTTPException(409, "Nothing to run: every document is done or excluded.")
        blocked = [r["n"] for r in work if worst(r) == "block"]
        if blocked:
            raise HTTPException(409, {"message": f"{len(blocked)} documents need fixing first.", "rows": blocked})
        # Hand the job its own copy of the password, encrypted with the job key; the worker deletes it after the run.
        pw = s.crypto.decrypt("session", sess.password_token, {"user": sess.user, "session": sess.key})
        expires = now() + s.settings.credential_hours * 3600
        t = now()
        # One write: the job's sign-in is stored and the job queued together, or neither (design: State rules)
        if not s.storage.queue_with_credential(
                job_id, sess.user, s.crypto.encrypt("job", pw, {"user": sess.user, "job": job_id}), expires,
                {"status": "Queued", "queuedAt": t, "queuePos": t, "scheduledBy": sess.user, "note": "",
                 "runNow": False, "runAt": None, "held": None,  # a scheduler's settings from an earlier time in the queue
                 "credentialExpires": int(expires), "checksAtSchedule": result["counts"],
                 "progress": {"total": len(work), "done": 0, "failed": 0}},
                list(RESCHEDULABLE), sess.key):
            raise HTTPException(409, "The job changed while submitting it; reload and try again.")
        s.storage.close_draft(job_id, sess.key)  # it leaves Drafts
        s.queue_rows.pop(sess.tenant, None)  # the queue has a new job: read it again (see _queue_rows)
        s.storage.audit(sess.tenant, "Submitted", sess.user, job_id, f"Submitted “{job['name']}” with {len(work)} documents.")
        return _public(s.storage.get_job(job_id), sess, s)  # with its plan: when it runs (design: Job scheduling)

    # ---- the schedule and the scheduler's queue actions (design: Job scheduling) ----------------------------
    def _schedule_view(s: Services, tenant: str) -> dict:
        return sched.view(sched.load(s.storage, tenant), s.clock(), s.settings.always_run_time)

    @app.get("/api/schedule")
    def get_schedule(sess: Session = Depends(current_session), s: Services = Depends(svc)):
        return _schedule_view(s, sess.tenant)

    @app.put("/api/schedule")
    def put_schedule(body: ScheduleBody, sess: Session = Depends(scheduler_session), s: Services = Depends(svc)):
        try:
            fields = sched.validate(body.days, body.start, body.end)
        except sched.ScheduleError as e:
            raise HTTPException(422, str(e))
        old = sched.load(s.storage, sess.tenant)
        s.storage.save_schedule(sess.tenant, fields, sess.user)
        new = sched.load(s.storage, sess.tenant)
        if sched.describe(old) != sched.describe(new):
            s.storage.audit(sess.tenant, "Schedule changed", sess.user, "",
                            f"Jobs run {sched.describe(old)} → {sched.describe(new)}.")
        return _schedule_view(s, sess.tenant)

    @app.post("/api/schedule/pause")
    def pause_queue(body: PauseBody, sess: Session = Depends(scheduler_session), s: Services = Depends(svc)):
        """Pause the queue: no job starts until a scheduler resumes it; a running job runs on."""
        reason = body.reason.strip()
        if not reason:
            raise HTTPException(422, "Give a reason for pausing the queue.")
        if not s.storage.pause_queue(sess.tenant, sess.user, reason):
            raise HTTPException(409, "The queue is already paused.")
        s.storage.audit(sess.tenant, "Queue paused", sess.user, "", f"Paused the job queue: {reason}")
        return _schedule_view(s, sess.tenant)

    @app.post("/api/schedule/resume")
    def resume_queue(sess: Session = Depends(scheduler_session), s: Services = Depends(svc)):
        was = s.storage.resume_queue(sess.tenant)
        if was:  # resuming a queue that isn't paused changes nothing
            s.storage.audit(sess.tenant, "Queue resumed", sess.user, "",
                            f"Resumed the job queue (paused by {was.get('by')}: {was.get('reason')}).")
        return _schedule_view(s, sess.tenant)

    def _queue_action(s: Services, sess: Session, job_id: str, fields: dict, audit_type: str, detail: str) -> dict:
        """Set a scheduler's setting on a queued job, only if it is still Queued (one conditional write)."""
        s.queue_rows.pop(sess.tenant, None)  # the order may change: read the queue again (see _queue_rows)
        job = _job_or_404(s, sess, job_id)
        if job["status"] != "Queued" or not s.storage.update_job(job_id, fields, expect_status="Queued"):
            now_status = (s.storage.get_job(job_id) or {}).get("status", "gone")
            raise HTTPException(409, f"The job is {now_status}; only queued jobs can be changed this way.")
        s.storage.audit(sess.tenant, audit_type, sess.user, job_id, detail.format(name=job.get("name") or "Untitled job"))
        return {"job": _public(s.storage.get_job(job_id), sess, s)}

    @app.post("/api/jobs/{job_id}/run-now")
    def run_now(job_id: str, body: OnOff, sess: Session = Depends(scheduler_session), s: Services = Depends(svc)):
        """Run now: the job goes first, as soon as no job is running, whatever the run times (not while paused)."""
        if body.on:
            return _queue_action(s, sess, job_id, {"runNow": True}, "Run now", "“{name}” runs next, as soon as no job is running.")
        return _queue_action(s, sess, job_id, {"runNow": False}, "Run now undone", "“{name}” runs at its run time again.")

    @app.post("/api/jobs/{job_id}/run-at")
    def run_at(job_id: str, body: RunAt, sess: Session = Depends(scheduler_session), s: Services = Depends(svc)):
        """The job's own run time, instead of the schedule's; from now until its saved sign-in expires."""
        if body.at is None:
            return _queue_action(s, sess, job_id, {"runAt": None}, "Run time cleared", "“{name}” runs at the next scheduled run time again.")
        job = _job_or_404(s, sess, job_id)
        t = s.clock()
        # a minute's grace: the browser's date-time field has minutes only, so "now" is already past
        if body.at < t - RUN_AT_GRACE_SECONDS:
            raise HTTPException(422, "The run time is in the past; choose a time from now on.")
        if job.get("credentialExpires") and body.at > float(job["credentialExpires"]):
            raise HTTPException(422, "The run time is after the job's saved sign-in expires; choose an earlier time, or "
                                     "have the job submitted again.")
        when = datetime.fromtimestamp(body.at, sched.TZ).strftime("%a %b %-d, %-I:%M %p")
        return _queue_action(s, sess, job_id, {"runAt": body.at}, "Run time set", f"“{{name}}” runs at {when} (Pacific time).")

    @app.post("/api/jobs/{job_id}/hold")
    def hold(job_id: str, body: OnOff, sess: Session = Depends(scheduler_session), s: Services = Depends(svc)):
        """Hold: the job keeps its place but doesn't start until it is released."""
        if body.on:
            return _queue_action(s, sess, job_id, {"held": {"by": sess.user, "at": now()}}, "Job held",
                                 "Held “{name}”: it doesn't start until it is released.")
        return _queue_action(s, sess, job_id, {"held": None}, "Job released", "Released “{name}”.")


def _refresh_permissions(s: Services, sess: Session) -> Session:
    client = sess.client(s)
    try:
        perms = client.account_permissions().summary
    except CSpaceError as e:
        raise _cspace_http(e)
    finally:
        client.close()
    if perms != sess.perms:
        s.storage.update_session_perms(sess.key, perms)
    return sess.model_copy(update={"perms": perms})


def _recheck(s: Services, sess: Session, job_id: str, targets: set[int] | None, refresh: bool = False) -> dict:
    """Re-run the checks on every row (see check_rows) and save the rows whose checks or lookups changed.

    Only a draft's rows are saved (design: the web app writes rows only while a job is editable). For a queued,
    running or finished job the checks are shown but nothing is written, so a job never changes after it was
    scheduled; a document that became protected meanwhile is reported, and the user edits the job to act on it.
    The one exception is protective: the stored thumbnail of a newly protected file is deleted at once."""
    rows = s.storage.get_rows(job_id)
    job = s.storage.get_job(job_id) or {}
    group_on = bool(job.get("groupOn"))
    group_exists = (job.get("groupStep") or {}).get("s") == "done"
    editable = job.get("status") == "Draft"
    # A user who may only view jobs sees a draft's checks, computed with their permissions, but never saves them
    writable = editable and can_edit(sess.perms)
    # a real copy: check_rows updates each row's lookups in place
    auto = ("checks", "lookups", "protected", "softSignals", "restricted", "restrictedAuto", "thumbKey",
            "creator", "contributor", "rightsHolder", "language")  # a renamed term's current refName (see rows.value_findings)
    before = {r["n"]: copy.deepcopy(tuple(r.get(k) for k in auto)) for r in rows}
    client = sess.client(s)
    try:
        partial = check_rows(s.tenant, rows, client, sess.perms, targets=targets, refresh=refresh, group_on=group_on,
                             set_publish=editable, group_exists=group_exists,
                             languages=lambda: vocabulary_terms(sess.tenant, client, "languages", fresh=refresh))
    except CSpaceError as e:
        raise _cspace_http(e)
    finally:
        client.close()
    # Design (Jobs that collide in the queue): what the jobs that run before this one will have changed by then
    collisions = _collisions(s, sess.tenant, job, rows, fresh=refresh)
    for r in rows:
        if r["n"] in collisions:
            r["checks"] = (r.get("checks") or []) + collisions[r["n"]]
    changed = []
    for r in rows:
        if r["n"] in partial:  # checked without its lookups: keep what it had
            for k, v in zip(auto, before[r["n"]]):
                r[k] = v
            continue
        # Saved only if the row is unchanged since it was read; if not, whoever changed it re-checks it.
        if r.get("protected") and r.get("thumbKey"):
            # Design: if a row becomes protected after its thumbnail was stored, the thumbnail is deleted at once.
            s.storage.delete_object(r["thumbKey"])
            r["thumbKey"] = None
            if not writable:
                s.storage.clear_thumbnail(job_id, r["n"])
        if editable and not writable:
            continue
        if not editable:
            was_protected = before[r["n"]][auto.index("protected")]
            if r.get("protected") and not was_protected and r.get("include"):
                r["checks"].append({"level": "warn", "text": f"Object {r.get('obj')} became protected after this job was "
                                    "submitted, and this document's publish setting wasn't changed. To change it, "
                                    "edit the job."})
            continue
        if before[r["n"]] != tuple(r.get(k) for k in auto) and s.storage.save_checks(job_id, r):
            changed.append(r)
    if writable:
        _note_protected(s, job_id, rows)
    counts = {"block": 0, "warn": 0}
    for r in rows:
        w = worst(r)
        if w in counts and r.get("include"):
            counts[w] += 1
    return {"rows": rows, "changed": changed, "counts": counts}


QUEUE_ROWS_SECONDS = 5  # how long _queue_rows keeps a tenant's queued jobs' rows


def _queue_rows(s: Services, tenant: str, fresh: bool = False) -> list[tuple[dict, list[dict]]]:
    """The tenant's Queued and Running jobs, each with its rows. Kept for a few seconds per web process: the editor
    re-checks a draft on every change, and the Job queue page checks every queued job at once. fresh (Submit)
    reads them again, so a submission is always judged by the queue as it is."""
    kept = s.queue_rows.get(tenant)
    if kept and not fresh and time.monotonic() - kept[0] < QUEUE_ROWS_SECONDS:
        return kept[1]
    jobs = [j for j in s.storage.list_jobs(tenant) if j.get("status") in ("Queued", "Running")]
    out = [(j, s.storage.get_rows(j["id"])) for j in jobs]
    s.queue_rows[tenant] = (time.monotonic(), out)
    return out


def _collisions(s: Services, tenant: str, job: dict, rows: list[dict], fresh: bool = False) -> dict[int, list[dict]]:
    """The checks a job's documents get from the jobs that run before it (rows.collision_checks). A draft is
    judged against every queued and running job; a queued job against the ones the worker picks first."""
    if job.get("status") not in ("Draft", "Queued"):
        return {}
    queue = _queue_rows(s, tenant, fresh)
    if not queue:
        return {}
    ids = {j["id"] for j in sched.ahead_of([j for j, _ in queue], job, sched.load(s.storage, tenant), s.clock(),
                                           s.settings.always_run_time)}
    return collision_checks(s.tenant, rows, [(j, rs) for j, rs in queue if j["id"] in ids])


def _note_protected(s: Services, job_id: str, rows: list[dict]) -> None:
    """Keep the job's count of protected files, and a draft's expiry: 7 days after the last save when it has
    protected files, 30 otherwise (design: Drafts, Expiry)."""
    job = s.storage.get_job(job_id) or {}
    count = sum(1 for r in rows if r.get("protected"))  # excluded documents' files are still held by the BMU
    if count == int(job.get("protectedCount") or 0):
        return
    fields: dict[str, Any] = {"protectedCount": count}
    if job.get("status") == "Draft" and job.get("lastSavedAt"):
        days = s.settings.protected_draft_days if count else s.settings.draft_days
        fields.update(draft_expiry(job, job["lastSavedAt"] + days * 86400))
    s.storage.update_job(job_id, fields)


def _recheck_after_change(s: Services, sess: Session, job_id: str, n: int) -> dict:
    """After one row changed: that row, rechecked, plus any other rows whose checks changed as a result."""
    r = _recheck(s, sess, job_id, targets={n})
    row = next(x for x in r["rows"] if x["n"] == n)
    return {"row": row, "others": [x for x in r["changed"] if x["n"] != n]}


def _404():
    raise HTTPException(404, "No such document")


app = None  # created by bmu.main
