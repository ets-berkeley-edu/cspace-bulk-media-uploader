"""BMU web API (FastAPI). The Vue app calls these endpoints; the worker runs scheduled jobs."""
from __future__ import annotations

import copy
import hashlib
import re
import secrets
import uuid
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .crypto import Crypto, make_crypto
from .cspace import CSpaceClient, CSpaceError
from .failures import catalog
from .filetypes import content_type, unsupported
from .rows import (PROBLEM_TEXT, apply_edit, can_replace_file, check_rows, clean_filename, created_records, edit_problem,
                   is_locked, media_created, new_row, worst)
from .storage import RowChanged, Storage, now
from .thumbnails import MAX_BROWSER_BYTES, TIFF_EXTENSIONS, NotAnImage, make_thumbnail, tiff_thumbnail_step
from .tenant import Tenant, load_tenant

COOKIE = "bmu_session"
CSRF_HEADER = "x-bmu"
# Only drafts are scheduled. A job that needs attention or failed goes to Drafts first (Fix and reschedule).
RESCHEDULABLE = ("Draft",)
FIXABLE = ("NeedsAttention", "Failed")

ClientFactory = Callable[[str, str], CSpaceClient]

AUTOCOMPLETE_PAGE = 20  # the first page of each source, as the CollectionSpace UI fetches

# Vocabularies the BMU offers whole (their terms change rarely, so they are cached for an hour).
VOCABULARIES = ("languages",)
VOCAB_CACHE_SECONDS = 3600
_VOCAB_CACHE: dict[tuple[str, str], tuple[float, list[dict]]] = {}


class Services:
    """Everything a request needs; replaced in tests."""

    def __init__(self, settings: Settings, storage: Storage, crypto: Crypto, client_factory: ClientFactory):
        self.settings = settings
        self.storage = storage
        self.crypto = crypto
        self.client_factory = client_factory
        self.tenant: Tenant = load_tenant(settings.tenant)


def create_app(services: Services | None = None) -> FastAPI:
    app = FastAPI(title="New BMU (prototype)", docs_url="/api/docs", openapi_url="/api/openapi.json")
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
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(RowChanged)
    async def row_changed(request: Request, exc: RowChanged):
        return JSONResponse({"detail": f"Document {exc.n} changed while you were working on it (for example its upload "
                                       "finished). Nothing was saved; try again."}, status_code=409)

    _routes(app)

    static = services.settings.static_dir
    if static and Path(static).is_dir():
        app.mount("/assets", StaticFiles(directory=Path(static) / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = Path(static) / path
            return FileResponse(f if path and f.is_file() else Path(static) / "index.html")

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

    def client(self, s: Services) -> CSpaceClient:
        pw = s.crypto.decrypt("session", self.password_token, {"user": self.user, "session": self.key})
        return s.client_factory(self.user, pw)


def current_session(request: Request, s: Services = Depends(svc)) -> Session:
    """The signed-in session. Design (Login and session): an idle timeout (30 minutes) and an absolute one
    (8 hours) bound how long a password sits in the session store. Background refreshes (X-BMU-Poll) don't count
    as activity, so an open tab left alone still signs out."""
    token = request.cookies.get(COOKIE)
    item = s.storage.get_session(_hash(token)) if token else None
    if not item:
        raise HTTPException(401, "Please sign in with your CollectionSpace account.")
    t = now()
    last = float(item.get("lastSeen") or item.get("expires", t) - s.settings.session_hours * 3600)
    if t - last > s.settings.session_idle_minutes * 60:
        s.storage.delete_session(item["PK"])
        raise HTTPException(401, f"You were signed out after {s.settings.session_idle_minutes} minutes without activity. "
                                 "Please sign in again; everything you changed was saved.")
    if request.headers.get("x-bmu-poll") != "1" and t - last > 60:
        s.storage.touch_session(item["PK"], t)
    return Session(key=item["PK"], user=item["user"], tenant=item["tenant"], perms=item["perms"],
                   password_token=item["password"])


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
    s.storage.mark_saved(job_id, sess.user, sess.key, _draft_days(s, s.storage.get_job(job_id)))


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
    if not s.storage.update_job(job_id, {"status": "Completed", "code": "", "note": "", "fixFrom": None,
                                         "expiresAt": now() + s.settings.completed_days * 86400}, expect_status="Draft"):
        return False
    s.storage.clear_editing(job_id)
    s.storage.drop_fix_originals(job_id)
    s.storage.audit(sess.tenant, "Completed", sess.user, job_id,
                    f"“{job['name'] or 'Untitled job'}” completed: every document is done or excluded.")
    return True


def _delete_job(s: "Services", sess: "Session", job: dict, rows: list[dict]) -> None:
    """Delete a job and its staged files. Records its runs created stay in CollectionSpace; the audit entry
    lists every one, by row and record type, so they can still be found and finished there.
    First one write marks it Deleting and removes its sign-in, so the worker can't start it meanwhile; if the job
    changed since it was read (claimed, or taken over), nothing is deleted."""
    statuses = ["Draft", "Queued", *FIXABLE]
    if job.get("status") not in statuses or not s.storage.begin_delete(job["id"], statuses, sess.key):
        raise HTTPException(409, "This job changed while deleting it (it may have started running); nothing was deleted. "
                                 "Reload and try again.")
    created = created_records(rows, job)
    s.storage.delete_job_and_files(job["id"])
    c = created["counts"]
    what = (f"; its runs created {c['media']} Media records ({c['files']} with files), {c['objects']} Objects, "
            + ("the Group, " if c["groups"] else "") +
            f"and {c['relations']} Relations, which stay in CollectionSpace" + (f", {c['unfinished']} unfinished" if c["unfinished"] else "")
            if created["csids"] else "; it had created nothing in CollectionSpace")
    big = len(created["csids"]) > 500  # a 1,000-row job's CSIDs go in S3, the entry points to them
    s.storage.audit(sess.tenant, "Job deleted", sess.user, job["id"],
                    f"Deleted “{job['name'] or 'Untitled job'}” ({len(rows)} documents){what}.", [] if big else created["csids"],
                    jobName=job.get("name", ""), counts=c,
                    **({"detailKey": s.storage.put_audit_detail(sess.tenant, job["id"], 0, created["csids"])} if big else {}))


def _public(job: dict, sess: "Session") -> dict:
    """A job as the API shows it: whether this session is its editor, not the other session's key."""
    out = {k: v for k, v in job.items() if k != "editingSession"}
    out["editingByYou"] = bool(job.get("editingSession")) and job.get("editingSession") == sess.key
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
    groupOn: bool | None = None  # "Create a group for this job"
    groupTitle: str | None = Field(default=None, max_length=200)


def default_group_title(name: str) -> str:
    """Design: prefilled with bmu-<job name> (the legacy =job convention)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "untitled job").lower()).strip("-")
    return f"bmu-{slug or 'untitled-job'}"


class FileSpec(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1)
    type: str = Field(default="", max_length=200)
    # Read from the image by the browser before the upload (design: Pre-filling rows from filenames and EXIF)
    exifDate: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    orientation: Literal["portrait", "landscape", "square", ""] = ""


class AddFiles(BaseModel):
    files: list[FileSpec] = Field(min_length=1)


class BulkEdit(BaseModel):
    rows: list[int] = Field(min_length=1, max_length=1000)
    changes: dict[str, Any] = Field(min_length=1)


class MoveJob(BaseModel):
    toIndex: int = Field(ge=0)  # new place among the queued jobs, 0 = next to run


class OpenDraft(BaseModel):
    takeOverSince: float | None = None  # take over from the editor the user was warned about


class CheckRequest(BaseModel):
    rows: list[int] | None = None  # the rows to look up in CollectionSpace; None: any row whose lookup is stale




def _routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health():
        return {"ok": True}

    # ---- sign-in (Basic Auth checked against CollectionSpace) ----------------------------
    @app.post("/api/login")
    def login(body: LoginBody, response: Response, s: Services = Depends(svc)):
        client = s.client_factory(body.username, body.password)
        try:
            perms = client.account_permissions()
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
            "user": body.username, "tenant": s.tenant.key, "perms": perms.summary, "expires": int(expires), "lastSeen": now(),
            "password": s.crypto.encrypt("session", body.password, {"user": body.username, "session": key}),
        })
        response.set_cookie(COOKIE, token, httponly=True, secure=s.settings.cookie_secure, samesite="strict",
                            max_age=int(s.settings.session_hours * 3600), path="/")
        return {"user": body.username, "tenant": s.tenant.public_summary(), "perms": perms.summary}

    @app.post("/api/logout")
    def logout(response: Response, request: Request, s: Services = Depends(svc)):
        token = request.cookies.get(COOKIE)
        if token:
            key = _hash(token)
            item = s.storage.get_session(key)
            if item:  # stop editing any draft this session had open, so others can edit it without taking over
                for j in s.storage.list_jobs(item["tenant"]):
                    if j.get("editingSession") == key:
                        s.storage.close_draft(j["id"], key)
            s.storage.delete_session(key)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/failures")
    def failures(sess: Session = Depends(current_session)):
        """The failure catalog: what the UI says about each failure code (design: Finished jobs and error messages)."""
        return {"failures": catalog()}

    @app.get("/api/me")
    def me(sess: Session = Depends(current_session), s: Services = Depends(svc)):
        return {"user": sess.user, "tenant": s.tenant.public_summary(), "perms": sess.perms}

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
        key = (sess.tenant, name)
        hit = _VOCAB_CACHE.get(key)
        if hit and now() - hit[0] < VOCAB_CACHE_SECONDS:
            return {"terms": hit[1]}
        client = sess.client(s)
        try:
            terms = sorted(client.vocabulary_items(name), key=lambda t: t["displayName"].lower())
        except CSpaceError as e:
            raise _cspace_http(e)
        finally:
            client.close()
        _VOCAB_CACHE[key] = (now(), terms)
        return {"terms": terms}

    # ---- jobs --------------------------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs(sess: Session = Depends(current_session), s: Services = Depends(svc)):
        return {"jobs": [_public(j, sess) for j in s.storage.list_jobs(sess.tenant)]}

    @app.post("/api/jobs")
    def create_job(body: NewJob, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        return _public(s.storage.create_job(sess.tenant, sess.user, body.name.strip(), sess.key, s.settings.draft_days), sess)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        rows = s.storage.get_rows(job_id)
        return {"job": _public(job, sess), "rows": rows, "runs": s.storage.get_runs(job_id),
                "created": created_records(rows, job)["counts"]}

    # ---- Fix and reschedule (design: Fixing a job after a run; Rescheduling after a run) --------------
    @app.post("/api/jobs/{job_id}/fix")
    def fix(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Fix and reschedule (or Reschedule): a job that needs attention or failed moves to Drafts, locked to
        you. Its rows keep their results; scheduling it queues a rerun of only what's unfinished. A fix not
        scheduled within 30 days of its last change is reverted."""
        job = _job_or_404(s, sess, job_id)
        t = now()
        if not s.storage.update_job(job_id, {"status": "Draft", "fixFrom": {"status": job["status"], "code": job.get("code", ""),
                                                                            "run": job.get("run", 0)},
                                             "note": "", "lastSavedBy": sess.user, "lastSavedAt": t,
                                             "expiresAt": t + _draft_days(s, job) * 86400}, expect_status=list(FIXABLE)):
            now_job = s.storage.get_job(job_id) or {}
            who = now_job.get("editingBy")
            raise HTTPException(409, f"{who} is already fixing this job; it's in Drafts." if who else
                                f"The job is {now_job.get('status')}; only jobs that need attention or failed can be fixed.")
        s.storage.open_draft(job_id, sess.user, sess.key)
        return _public(s.storage.get_job(job_id), sess)

    # ---- the job queue (design: The job queue; State rules) ---------------------------------------
    @app.post("/api/jobs/{job_id}/move")
    def move_job(job_id: str, body: MoveJob, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Change a queued job's place in the queue. Running jobs stay first and can't be moved."""
        job = _job_or_404(s, sess, job_id)
        if job["status"] != "Queued":
            raise HTTPException(409, "Only queued jobs can be moved.")
        queued = sorted((j for j in s.storage.list_jobs(sess.tenant) if j["status"] == "Queued"),
                        key=lambda j: (j.get("queuePos", 0), j.get("queuedAt", 0)))
        order = [j for j in queued if j["id"] != job_id]
        order.insert(min(body.toIndex, len(order)), job)
        for i, j in enumerate(order, start=1):  # positions 1..n in the new order
            if j.get("queuePos") != i:
                s.storage.update_job(j["id"], {"queuePos": i}, expect_status="Queued")
        return {"jobs": [_public(s.storage.get_job(j["id"]), sess) for j in order]}

    @app.post("/api/jobs/{job_id}/edit")
    def edit_queued(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Edit a queued job: it leaves the queue for Drafts, locked to you, and its saved sign-in is deleted.
        It goes to the end of the queue when it is scheduled again."""
        job = _job_or_404(s, sess, job_id)
        if not s.storage.update_job(job_id, {"status": "Draft", "queuePos": None, "note": "", "lastSavedBy": sess.user,
                                             "lastSavedAt": now(), "expiresAt": now() + _draft_days(s, job) * 86400},
                                    expect_status="Queued"):
            raise HTTPException(409, f"The job is {s.storage.get_job(job_id)['status']}; only queued jobs can be edited this way.")
        s.storage.delete_credential(job_id)
        s.storage.open_draft(job_id, sess.user, sess.key)
        s.storage.audit(sess.tenant, "Moved to Drafts", sess.user, job_id,
                        f"Took “{job['name']}” out of the queue to edit it; its saved sign-in was deleted.")
        return _public(s.storage.get_job(job_id), sess)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_run(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Cancel run: the worker finishes the document in progress, then stops (Needs attention, cancelled)."""
        _job_or_404(s, sess, job_id)
        if not s.storage.update_job(job_id, {"cancelRequested": {"by": sess.user, "at": now()}}, expect_status="Running"):
            raise HTTPException(409, "Only a running job can be cancelled.")
        return _public(s.storage.get_job(job_id), sess)

    # ---- drafts: open for editing (one editor at a time), take over, close, save -------------
    @app.post("/api/jobs/{job_id}/open")
    def open_draft(job_id: str, body: OpenDraft | None = None, sess: Session = Depends(current_session), s: Services = Depends(svc)):
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
    def save_draft(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Save draft: every change is already saved; this confirms it and restarts the draft's expiry. A job
        that has run and has every document done or excluded becomes Completed."""
        _editable(_job_or_404(s, sess, job_id), sess)
        _saved(s, sess, job_id)
        _complete_if_clean(s, sess, job_id)
        return _public(s.storage.get_job(job_id), sess)

    @app.patch("/api/jobs/{job_id}")
    def patch_job(job_id: str, body: JobPatch, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """The job header: its name, and the job's group (design: Groups). The Group title follows the job name
        until the user edits it. Once the Group exists in CollectionSpace, it can't be turned off or renamed."""
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
            if on and not job.get("groupTitle"):
                fields.update(groupTitle=default_group_title(name), groupTitleAuto=True)
        if body.groupTitle is not None:
            title = body.groupTitle.strip()
            fields.update(groupTitle=title, groupTitleAuto=title == default_group_title(name))
        elif body.name is not None and job.get("groupTitleAuto") and not group_made:
            fields["groupTitle"] = default_group_title(name)  # still the prefilled title: it follows the name
        if fields:
            s.storage.update_job(job_id, fields, expect_status="Draft")
        _saved(s, sess, job_id)
        rc = _recheck(s, sess, job_id, targets=set()) if "groupOn" in fields else None
        return {**_public(s.storage.get_job(job_id), sess), **({"rows": rc["changed"]} if rc else {})}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Design: Deleting a job. Drafts, queued jobs and jobs that need attention or failed; not a running
        job (cancel it first) or a draft someone else is editing. Allowed even if its runs created records:
        they stay in CollectionSpace (the BMU never deletes them) and the audit entry lists them."""
        job = _job_or_404(s, sess, job_id)
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
    def add_files(job_id: str, body: AddFiles, sess: Session = Depends(current_session), s: Services = Depends(svc)):
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
        return {"rows": [{**r, "uploadForm": s.storage.presign_upload(r["s3Key"], f.size, r["contentType"])}
                         for r, f in zip(rows, body.files)]}

    @app.post("/api/jobs/{job_id}/rows/{n}/uploaded")
    def uploaded(job_id: str, n: int, background: BackgroundTasks, sess: Session = Depends(current_session), s: Services = Depends(svc)):
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
    async def put_thumbnail(job_id: str, n: int, request: Request, sess: Session = Depends(current_session), s: Services = Depends(svc)):
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
    def replace_file(job_id: str, n: int, body: FileSpec, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """A replacement file for a document whose Media record exists but whose file didn't reach CollectionSpace
        (rejected, or lost). The browser uploads it like any file; the rerun uploads it to the existing Media record."""
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        row = s.storage.get_row(job_id, n) or _404()
        if not can_replace_file(row):
            raise HTTPException(409, "Only a document whose Media record exists and whose file didn't reach CollectionSpace "
                                     "takes a replacement file.")
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
        return {"row": row, "uploadForm": s.storage.presign_upload(row["s3Key"], body.size, row["contentType"])}

    @app.post("/api/jobs/{job_id}/rows/{n}/retry-upload")
    def retry_upload(job_id: str, n: int, body: FileSpec, sess: Session = Depends(current_session), s: Services = Depends(svc)):
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
        return {"row": row, "uploadForm": s.storage.presign_upload(row["s3Key"], body.size, row["contentType"])}

    @app.post("/api/jobs/{job_id}/rows/{n}/upload-failed")
    def upload_failed(job_id: str, n: int, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        _editable(_job_or_404(s, sess, job_id))
        row = s.storage.get_row(job_id, n) or _404()
        row["upload"] = {"s": "failed", "reason": "browser"}
        s.storage.put_row(job_id, row)
        return _recheck_after_change(s, sess, job_id, n)

    # ---- rows -----------------------------------------------------------------------------------
    @app.patch("/api/jobs/{job_id}/rows/{n}")
    def edit_row(job_id: str, n: int, changes: dict[str, Any], sess: Session = Depends(current_session),
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
    def bulk_edit(job_id: str, body: BulkEdit, sess: Session = Depends(current_session), s: Services = Depends(svc)):
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
    def delete_row(job_id: str, n: int, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        _editable(job, sess)
        _saved(s, sess, job_id)
        row = s.storage.get_row(job_id, n) or _404()
        if is_locked(row):
            raise HTTPException(409, "This document already created records in CollectionSpace, so it can't be deleted. "
                                     "Check Exclude to have the BMU ignore it.")
        # One conditional write: only if the row is as checked and the job is still this session's draft
        if not s.storage.delete_row_if_unchanged(job_id, row, sess.key):
            raise HTTPException(409, "This document or job changed while deleting it; nothing was deleted. Reload and try again.")
        for key in {row.get("s3Key"), row.get("supersededKey"), row.get("thumbKey")} - {None, ""}:
            s.storage.delete_object(key)  # its staged file, a replacement, and its thumbnail
        s.storage.drop_fix_original(job_id, n)  # deleting is permanent, even if the fix is abandoned
        if job.get("run"):  # the next run lists the documents deleted since the last one
            s.storage.update_job(job_id, {"deletedRows": (job.get("deletedRows") or []) +
                                          [{"n": n, "file": row["file"], "by": sess.user, "at": now()}]})
        s.storage.audit(sess.tenant, "Row deleted", sess.user, job_id,
                        f"Deleted document {n} ({row['file']}) from “{job['name'] or 'Untitled job'}”; it had created nothing in CollectionSpace.")
        if not s.storage.get_rows(job_id):  # design: deleting the last document deletes the job, run or not
            fresh = s.storage.get_job(job_id)
            if fresh:
                _delete_job(s, sess, fresh, [])
            return {"ok": True, "others": [], "jobStatus": "Deleted"}
        if _complete_if_clean(s, sess, job_id):
            return {"ok": True, "others": [], "jobStatus": (s.storage.get_job(job_id) or {}).get("status", "Deleted")}
        return {"ok": True, "others": _recheck(s, sess, job_id, targets=set())["changed"]}

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
    def schedule(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        if job["status"] not in RESCHEDULABLE:
            raise HTTPException(409, f"The job is {job['status']} and can't be scheduled.")
        if job["status"] == "Draft":
            _editable(job, sess)  # only the draft's editor schedules it
        if job.get("groupOn") and not (job.get("groupTitle") or "").strip():
            raise HTTPException(409, "Enter a group title, or turn off the job's group.")
        # Roles can change during a session: fetch the permissions again, then check the whole job afresh.
        sess = _refresh_permissions(s, sess)
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
                 "credentialExpires": int(expires), "checksAtSchedule": result["counts"],
                 "progress": {"total": len(work), "done": 0, "failed": 0}},
                list(RESCHEDULABLE), sess.key):
            raise HTTPException(409, "The job changed while scheduling; reload and try again.")
        s.storage.close_draft(job_id, sess.key)  # it leaves Drafts
        s.storage.audit(sess.tenant, "Scheduled", sess.user, job_id, f"Scheduled “{job['name']}” with {len(work)} documents.")
        return _public(s.storage.get_job(job_id), sess)


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
    editable = job.get("status") == "Draft"
    # a real copy: check_rows updates each row's lookups in place
    auto = ("checks", "lookups", "protected", "softSignals", "restricted", "restrictedAuto", "thumbKey")
    before = {r["n"]: copy.deepcopy(tuple(r.get(k) for k in auto)) for r in rows}
    client = sess.client(s)
    try:
        partial = check_rows(s.tenant, rows, client, sess.perms, targets=targets, refresh=refresh, group_on=group_on,
                             set_publish=editable)
    except CSpaceError as e:
        raise _cspace_http(e)
    finally:
        client.close()
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
            if not editable:
                s.storage.clear_thumbnail(job_id, r["n"])
        if not editable:
            was_protected = before[r["n"]][auto.index("protected")]
            if r.get("protected") and not was_protected and r.get("include"):
                r["checks"].append({"level": "warn", "text": f"Object {r.get('obj')} became protected after this job was "
                                    "scheduled, and this document's publish setting wasn't changed. To change it, "
                                    "edit the job."})
            continue
        if before[r["n"]] != tuple(r.get(k) for k in auto) and s.storage.save_checks(job_id, r):
            changed.append(r)
    if editable:
        _note_protected(s, job_id, rows)
    counts = {"block": 0, "warn": 0}
    for r in rows:
        w = worst(r)
        if w in counts and r.get("include"):
            counts[w] += 1
    return {"rows": rows, "changed": changed, "counts": counts}


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
        fields["expiresAt"] = job["lastSavedAt"] + days * 86400
    s.storage.update_job(job_id, fields)


def _recheck_after_change(s: Services, sess: Session, job_id: str, n: int) -> dict:
    """After one row changed: that row, rechecked, plus any other rows whose checks changed as a result."""
    r = _recheck(s, sess, job_id, targets={n})
    row = next(x for x in r["rows"] if x["n"] == n)
    return {"row": row, "others": [x for x in r["changed"] if x["n"] != n]}


def _404():
    raise HTTPException(404, "No such document")


app = None  # created by bmu.main
