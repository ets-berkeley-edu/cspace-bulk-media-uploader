"""BMU web API (FastAPI). The Vue app calls these endpoints; the worker runs scheduled jobs."""
from __future__ import annotations

import copy
import hashlib
import re
import secrets
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .crypto import Crypto, make_crypto
from .cspace import CSpaceClient, CSpaceError
from .rows import PROBLEM_TEXT, apply_edit, check_rows, clean_filename, edit_problem, is_locked, new_row, worst
from .storage import RowChanged, Storage, now
from .tenant import Tenant, load_tenant

COOKIE = "bmu_session"
CSRF_HEADER = "x-bmu"
# Draft: a new job. NeedsAttention/Failed: "Reschedule" reruns only the unfinished steps.
RESCHEDULABLE = ("Draft", "NeedsAttention", "Failed")

ClientFactory = Callable[[str, str], CSpaceClient]

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
    token = request.cookies.get(COOKIE)
    item = s.storage.get_session(_hash(token)) if token else None
    if not item:
        raise HTTPException(401, "Please sign in with your CollectionSpace account.")
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


def _saved(s: "Services", sess: "Session", job_id: str) -> None:
    """A change to a draft was saved: record who saved it and restart its expiry."""
    s.storage.mark_saved(job_id, sess.user, sess.key, s.settings.draft_days)


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
    name: str = Field(max_length=200)


class FileSpec(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1)
    type: str = Field(default="", max_length=200)


class AddFiles(BaseModel):
    files: list[FileSpec] = Field(min_length=1)


class BulkEdit(BaseModel):
    rows: list[int] = Field(min_length=1, max_length=1000)
    changes: dict[str, Any] = Field(min_length=1)


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
            "user": body.username, "tenant": s.tenant.key, "perms": perms.summary, "expires": int(expires),
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

    @app.get("/api/me")
    def me(sess: Session = Depends(current_session), s: Services = Depends(svc)):
        return {"user": sess.user, "tenant": s.tenant.public_summary(), "perms": sess.perms}

    # ---- authority autocomplete (existing terms only) ------------------------------------
    @app.get("/api/authorities")
    def authorities(field: str, q: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        if len(q.strip()) < 3:
            return {"terms": []}
        kinds = s.tenant.authority_fields.get(field)
        if not kinds:
            raise HTTPException(400, "Not an authority field")
        client = sess.client(s)
        try:
            terms = []
            for kind in kinds:
                a = s.tenant.authorities[kind]
                for t in client.search_terms(a["service"], a["vocabulary"], q.strip()):
                    terms.append({**t, "source": kind})
            return {"terms": terms}
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
        return {"job": _public(job, sess), "rows": s.storage.get_rows(job_id)}

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
        _job_or_404(s, sess, job_id)
        s.storage.close_draft(job_id, sess.key)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/save")
    def save_draft(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """Save draft: every change is already saved; this confirms it and restarts the draft's expiry."""
        _editable(_job_or_404(s, sess, job_id), sess)
        _saved(s, sess, job_id)
        return _public(s.storage.get_job(job_id), sess)

    @app.patch("/api/jobs/{job_id}")
    def rename_job(job_id: str, body: JobPatch, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        _editable(_job_or_404(s, sess, job_id), sess)
        s.storage.update_job(job_id, {"name": body.name.strip()}, expect_status="Draft")
        _saved(s, sess, job_id)
        return _public(s.storage.get_job(job_id), sess)

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        job = _job_or_404(s, sess, job_id)
        rows = s.storage.get_rows(job_id)
        if job["status"] == "Running" or any(is_locked(r) for r in rows):
            raise HTTPException(409, "This job created records in CollectionSpace or is running, so it can't be deleted.")
        if job.get("editingSession") and job["editingSession"] != sess.key:
            raise HTTPException(409, f"{job.get('editingBy')} is editing this draft, so it can't be deleted.")
        s.storage.delete_job_and_files(job_id)
        s.storage.audit(sess.tenant, "Job deleted", sess.user, job_id, f"Deleted “{job['name']}” ({len(rows)} documents); it had created nothing in CollectionSpace.")
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
        try:  # design: filenames are cleaned once, on the server, when the browser first reports them
            names = [clean_filename(f.name) for f in body.files]
        except ValueError as e:
            raise HTTPException(422, str(e))
        new = []
        for f, name in zip(body.files, names):
            row = new_row(s.tenant, name, f.size, f.type)
            row["s3Key"] = f"jobs/{job_id}/{uuid.uuid4().hex}"  # design: staged files keep random keys, no names
            new.append(row)
        rows = s.storage.add_rows(job_id, new)
        return {"rows": [{**r, "uploadForm": s.storage.presign_upload(r["s3Key"], f.size)}
                         for r, f in zip(rows, body.files)]}

    @app.post("/api/jobs/{job_id}/rows/{n}/uploaded")
    def uploaded(job_id: str, n: int, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        _editable(_job_or_404(s, sess, job_id))
        row = s.storage.get_row(job_id, n) or _404()
        head = s.storage.head_object(row["s3Key"])
        if head and head["ContentLength"] == row["size"]:
            row["upload"] = {"s": "done", "version": head.get("VersionId") or ""}
        else:
            row["upload"] = {"s": "failed", "reason": "missing" if not head else "size mismatch"}
        s.storage.put_row(job_id, row)
        return _recheck_after_change(s, sess, job_id, n)

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
        _editable(_job_or_404(s, sess, job_id), sess)
        _saved(s, sess, job_id)
        row = s.storage.get_row(job_id, n) or _404()
        others = [r["file"] for r in s.storage.get_rows(job_id) if r["n"] != n] if "file" in changes else []
        try:
            apply_edit(s.tenant, row, changes, others)
        except ValueError as e:
            raise HTTPException(422, str(e))
        s.storage.put_row(job_id, row)
        return _recheck_after_change(s, sess, job_id, n)

    @app.post("/api/jobs/{job_id}/rows/bulk")
    def bulk_edit(job_id: str, body: BulkEdit, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        """The bulk-change panel: the same changes to many rows. Never applied partially: if any target row
        can't take a change it would actually change, nothing is saved."""
        _editable(_job_or_404(s, sess, job_id), sess)
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
            edited.append(r)
        s.storage.put_rows_all_or_none(job_id, edited, originals)
        rc = _recheck(s, sess, job_id, targets={r["n"] for r in edited})
        changed = {r["n"] for r in edited} | {r["n"] for r in rc["changed"]}
        return {"rows": [r for r in rc["rows"] if r["n"] in changed]}

    @app.delete("/api/jobs/{job_id}/rows/{n}")
    def delete_row(job_id: str, n: int, sess: Session = Depends(current_session), s: Services = Depends(svc)):
        _editable(_job_or_404(s, sess, job_id), sess)
        _saved(s, sess, job_id)
        row = s.storage.get_row(job_id, n) or _404()
        if is_locked(row):
            raise HTTPException(409, "This document already created records in CollectionSpace, so it can't be deleted.")
        if row.get("s3Key"):
            s.storage.delete_object(row["s3Key"])
        s.storage.delete_row(job_id, n)
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
        # Roles can change during a session: fetch the permissions again, then check the whole job afresh.
        sess = _refresh_permissions(s, sess)
        result = _recheck(s, sess, job_id, targets=None, refresh=True)
        work = [r for r in result["rows"] if r.get("include") and (r.get("result") or {}).get("state") != "Done"]
        if not work:
            raise HTTPException(409, "Nothing to run: every document is done or disabled.")
        blocked = [r["n"] for r in work if worst(r) == "block"]
        if blocked:
            raise HTTPException(409, {"message": f"{len(blocked)} documents need fixing first.", "rows": blocked})
        # Hand the job its own copy of the password, encrypted with the job key; the worker deletes it after the run.
        pw = s.crypto.decrypt("session", sess.password_token, {"user": sess.user, "session": sess.key})
        expires = now() + s.settings.credential_hours * 3600
        s.storage.put_credential(job_id, sess.user,
                                 s.crypto.encrypt("job", pw, {"user": sess.user, "job": job_id}), expires)
        if not s.storage.update_job(job_id, {"status": "Queued", "queuedAt": now(), "scheduledBy": sess.user,
                                             "credentialExpires": int(expires), "progress": {"total": len(work), "done": 0, "failed": 0}},
                                    expect_status=list(RESCHEDULABLE)):
            s.storage.delete_credential(job_id)
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
    """Re-run the checks on every row (see check_rows) and save the rows whose checks or lookups changed."""
    rows = s.storage.get_rows(job_id)
    # a real copy: check_rows updates each row's lookups in place
    before = {r["n"]: copy.deepcopy((r.get("checks"), r.get("lookups"))) for r in rows}
    client = sess.client(s)
    try:
        partial = check_rows(s.tenant, rows, client, sess.perms, targets=targets, refresh=refresh)
    except CSpaceError as e:
        raise _cspace_http(e)
    finally:
        client.close()
    changed = []
    for r in rows:
        if r["n"] in partial:  # checked without its lookups: keep what it had
            r["checks"], r["lookups"] = before[r["n"]]
            continue
        # Saved only if the row is unchanged since it was read; if not, whoever changed it re-checks it.
        if before[r["n"]] != (r.get("checks"), r.get("lookups")) and s.storage.save_checks(job_id, r):
            changed.append(r)
    counts = {"block": 0, "warn": 0}
    for r in rows:
        w = worst(r)
        if w in counts and r.get("include"):
            counts[w] += 1
    return {"rows": rows, "changed": changed, "counts": counts}


def _recheck_after_change(s: Services, sess: Session, job_id: str, n: int) -> dict:
    """After one row changed: that row, rechecked, plus any other rows whose checks changed as a result."""
    r = _recheck(s, sess, job_id, targets={n})
    row = next(x for x in r["rows"] if x["n"] == n)
    return {"row": row, "others": [x for x in r["changed"] if x["n"] != n]}


def _404():
    raise HTTPException(404, "No such document")


app = None  # created by bmu.main
