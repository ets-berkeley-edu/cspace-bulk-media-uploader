"""Demo tools (demo builds only): the endpoints behind the web app's Demo tools pane.

Off unless BMU_DEMO=true: every endpoint answers 404, and uploads go straight to S3 as designed. With it on, a
signed-in user can
  - slow the browser's uploads: the presigned POST is sent to the web app, which passes it on to S3 at a set speed;
  - control the simulated CollectionSpace (backend/fakecspace): slow its creates and file uploads, make steps fail,
    delete or rename sample terms and languages, reset it; these only pass requests on to its /_fake endpoints;
  - delete every job in the tenant except running ones (drafts open in an editor too), to start a demo afresh.
    Records in CollectionSpace are never touched (the BMU is create-only); the usual "Job deleted" audit entries
    are written.

None of this is part of the BMU's design; it exists so a demo can show uploads, runs and failures at a watchable pace.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .app import Services, Session
    from .config import Settings

log = logging.getLogger(__name__)

UPLOAD_PATH = "/api/_demo/s3upload"
CHUNK = 64 * 1024

# Simulator controls the pane may use: action -> (method, /_fake path). Anything else is refused.
SIM_ACTIONS: dict[str, tuple[str, str]] = {
    "slow": ("POST", "/_fake/slow"),
    "fail": ("POST", "/_fake/fail"),
    "clear-failures": ("DELETE", "/_fake/fail"),
    "delete-term": ("POST", "/_fake/delete-term"),
    "rename-term": ("POST", "/_fake/rename-term"),
    "delete-language": ("POST", "/_fake/delete-language"),
    "rename-language": ("POST", "/_fake/rename-language"),
    "reset": ("POST", "/_fake/reset"),
}

# Sends the browser's upload on to S3: (url, headers, body) -> (status, content type, body).
Forward = Callable[[str, dict[str, str], AsyncIterator[bytes]], Awaitable[tuple[int, str, bytes]]]


class DemoState:
    """The Demo tools' settings, in this web app process's memory (a demo runs one web app process)."""

    def __init__(self, settings: "Settings"):
        self.settings = settings
        self.browser_upload_mbps = 0.0  # 0 = uploads go straight to S3
        self.sim: httpx.Client | None = None  # the simulator's HTTP client (tests pass one in)
        self.forward: Forward = _forward_to_s3
        self.sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def sim_client(self) -> httpx.Client:
        if self.sim is None:
            self.sim = httpx.Client(base_url=self.settings.cspace_url.rstrip("/"), timeout=10.0)
        return self.sim

    def s3_post_url(self) -> str:
        """Where a presigned POST goes: the bucket on the S3 endpoint the web app itself uses."""
        s = self.settings
        if s.s3_endpoint:
            return f"{s.s3_endpoint.rstrip('/')}/{s.s3_bucket}"
        return f"https://{s.s3_bucket}.s3.{s.aws_region}.amazonaws.com/"


def route_upload(s: "Services", form: dict) -> dict:
    """A presigned POST, sent to the web app instead of S3 while a demo browser upload speed is set."""
    if s.settings.demo and s.demo.browser_upload_mbps > 0:
        return {**form, "url": UPLOAD_PATH}
    return form


async def _forward_to_s3(url: str, headers: dict[str, str], body: AsyncIterator[bytes]) -> tuple[int, str, bytes]:
    async with httpx.AsyncClient(timeout=None) as c:
        r = await c.post(url, headers=headers, content=body)
        return r.status_code, r.headers.get("content-type", ""), r.content


class SimAction(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class UploadSpeed(BaseModel):
    mbps: float = Field(ge=0, le=1000)


def register(app: FastAPI) -> None:
    from .app import FIXABLE, Services, Session, _delete_job, current_session, svc

    def demo_on(s: Services = Depends(svc)) -> Services:
        if not s.settings.demo:
            raise HTTPException(404, "Not Found")
        return s

    def sim_call(s: Services, method: str, path: str, params: dict | None = None) -> Any:
        try:
            r = s.demo.sim_client().request(method, path, params=params or {})
        except httpx.HTTPError as e:
            raise HTTPException(502, f"The simulated CollectionSpace at {s.settings.cspace_url} didn't answer ({e.__class__.__name__}). "
                                     "Is it running? Demo tools only work with the simulator, not a real server.")
        if r.status_code == 404:
            raise HTTPException(502, f"{s.settings.cspace_url} has no simulator controls: Demo tools only work with the "
                                     "simulated CollectionSpace (backend/fakecspace), not a real server.")
        if r.status_code >= 400:
            raise HTTPException(400, r.text or f"The simulator refused this ({r.status_code}).")
        return r.json()

    @app.get("/api/_demo/status")
    def status(sess: Session = Depends(current_session), s: Services = Depends(demo_on)):
        """What the Demo tools pane shows: the browser upload speed, and the simulator's settings and samples."""
        try:
            sim, sim_error = sim_call(s, "GET", "/_fake/settings"), ""
        except HTTPException as e:
            sim, sim_error = None, e.detail
        return {"browserUploadMbps": s.demo.browser_upload_mbps, "cspaceUrl": s.settings.cspace_url,
                "alwaysRunTime": s.settings.always_run_time, "sim": sim, "simError": sim_error}

    @app.post("/api/_demo/browser-upload")
    def browser_upload(body: UploadSpeed, sess: Session = Depends(current_session), s: Services = Depends(demo_on)):
        """The browser's uploads go through the web app at about this many MB/s (0: straight to S3 again). Applies to
        uploads that start from now on."""
        s.demo.browser_upload_mbps = body.mbps
        return {"browserUploadMbps": body.mbps}

    @app.post("/api/_demo/sim/{action}")
    def sim_action(action: str, body: SimAction, sess: Session = Depends(current_session), s: Services = Depends(demo_on)):
        """Pass one control on to the simulated CollectionSpace (see SIM_ACTIONS and backend/fakecspace/app.py)."""
        if action not in SIM_ACTIONS:
            raise HTTPException(404, "Not Found")
        method, path = SIM_ACTIONS[action]
        params = {k: v for k, v in body.params.items() if v is not None and v != ""}
        sim_call(s, method, path, params)
        return sim_call(s, "GET", "/_fake/settings")

    @app.get("/api/_demo/sim/objects")
    def sim_objects(sess: Session = Depends(current_session), s: Services = Depends(demo_on)):
        """The simulator's sample Object records: which object numbers exist, and which are sensitive."""
        return {"objects": sim_call(s, "GET", "/_fake/objects")}

    @app.post("/api/_demo/delete-all-jobs")
    def delete_all_jobs(sess: Session = Depends(current_session), s: Services = Depends(demo_on)):
        """Delete every job in the tenant except running ones, with the usual "Job deleted" audit entries. Drafts open
        in someone's editor are closed first (a demo reset, unlike Delete). Nothing in CollectionSpace is touched."""
        deleted, skipped = 0, []
        for job in s.storage.list_jobs(sess.tenant):
            if job.get("editingSession"):
                s.storage.close_draft(job["id"], job["editingSession"])
                job = {k: v for k, v in job.items() if k not in ("editingSession", "editingBy", "editingSince")}
            try:
                _delete_job(s, sess, job, s.storage.get_rows(job["id"]), statuses=("Draft", "Queued", "Completed", *FIXABLE))
                deleted += 1
            except HTTPException:
                skipped.append(job.get("name") or "Untitled job")
        log.info("demo: %s deleted %d jobs (%d skipped)", sess.user, deleted, len(skipped))
        return {"deleted": deleted, "skipped": skipped}

    @app.post(UPLOAD_PATH)
    async def s3_upload(request: Request, sess: Session = Depends(current_session), s: Services = Depends(demo_on)):
        """A browser upload (the presigned POST form, unchanged) passed on to S3 at the demo upload speed."""
        rate = s.demo.browser_upload_mbps * 1024 * 1024

        async def body() -> AsyncIterator[bytes]:
            started, sent = time.monotonic(), 0
            async for chunk in request.stream():
                for i in range(0, len(chunk), CHUNK):
                    piece = chunk[i:i + CHUNK]
                    sent += len(piece)
                    if rate > 0:  # hold each piece back until the set speed allows it
                        wait = sent / rate - (time.monotonic() - started)
                        if wait > 0:
                            await s.demo.sleep(wait)
                    yield piece

        headers = {k: v for k, v in request.headers.items() if k.lower() in ("content-type", "content-length")}
        status_code, ctype, content = await s.demo.forward(s.demo.s3_post_url(), headers, body())
        return Response(content=content, status_code=status_code, media_type=ctype or None)
