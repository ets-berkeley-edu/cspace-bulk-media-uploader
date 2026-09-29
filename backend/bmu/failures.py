"""The failure catalog (failures.yaml) and how the worker turns a failed call into a catalog code.

Design: Finished jobs and error messages. The worker records a code, the technical detail (HTTP status and
step) and nothing else; the UI shows the catalog's title, explanation and what to do. An unrecognized
failure is recorded as "unknown", which shows the HTTP status and step.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .cspace import CSpaceError

# Failures that stop the whole job at once (a wrong password retried on every row could lock the account).
JOB_LEVEL = {"auth", "account_inactive"}


@lru_cache
def catalog() -> dict[str, dict]:
    data = yaml.safe_load((Path(__file__).parent / "failures.yaml").read_text())
    for code, e in data.items():
        missing = {"title", "level", "explain", "fix", "needs_fix"} - set(e)
        if missing:
            raise ValueError(f"failures.yaml: {code} lacks {', '.join(sorted(missing))}")
    return data


def needs_fix(code: str | None) -> bool:
    """True when something must change before a rerun can succeed (the button reads Fix and reschedule)."""
    return bool(code) and bool(catalog().get(code, {}).get("needs_fix"))


def known(code: str) -> str:
    return code if code in catalog() else "unknown"


def classify(step: str, e: CSpaceError) -> tuple[str, str]:
    """(catalog code, technical detail) for a failed CollectionSpace call made by a row step."""
    status = e.status
    detail = e.detail
    if status == 401:
        return "auth", detail
    if status == 409:
        return "account_inactive", detail
    if status == 403:
        return "no_permission", detail
    if step == "upload" and status == 413:
        return "upload_too_large", detail
    if step == "upload" and status == 415:
        return "file_type_rejected", detail
    if step == "media" and status == 400:
        return "media_rejected", detail
    if step in ("createObject", "findOrCreateObject") and status == 400:
        return "object_rejected", detail
    if step == "group":
        return "group_failed", detail  # any other failure creating the job's Group
    if e.code == "unavailable" or (status is not None and status >= 500):
        return "server_error", detail  # one 5xx or timeout; five in a row stop the job as "unavailable"
    return "unknown", f"{detail} (step {step})"
