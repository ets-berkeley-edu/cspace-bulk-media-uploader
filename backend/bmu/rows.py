"""Row model: defaults from the filename, editable fields, and checks against CollectionSpace."""
from __future__ import annotations

import re
from typing import Any

from .cspace import CSpaceClient, CSpaceError
from .tenant import Tenant, parse_filename

EDITABLE = {"handling", "obj", "idnum", "date", "restricted", "type", "creator", "contributor", "rightsHolder",
            "description", "copyright", "include", "file"}
AUTHORITY_FIELDS = {"creator", "contributor", "rightsHolder"}

ROW_STATES = ("Not started", "In progress", "Done", "Partial", "Failed")


def new_row(tenant: Tenant, filename: str, size: int, content_type: str) -> dict[str, Any]:
    p = parse_filename(tenant, filename)
    row: dict[str, Any] = {
        "file": filename, "fileOriginal": filename, "size": size, "contentType": content_type or "",
        "handling": tenant.handling[0].id, "objParsed": p["obj"], "obj": p["obj"], "img": p["img"], "parseOk": p["ok"],
        "idnum": "", "date": "", "restricted": bool(tenant.publish.get("default", False)),
        "type": "", "creator": "", "contributor": "", "rightsHolder": "", "description": "", "copyright": "",
        "include": True, "upload": {"s": "pending"}, "checks": [], "result": None, "touched": [],
    }
    row["idnum"] = default_idnum(tenant, row)
    return row


def default_idnum(tenant: Tenant, row: dict) -> str:
    h = tenant.handling_by_id(row["handling"])
    return row["img"] if h and h.id_rule == "image" else row["obj"]


def apply_edit(tenant: Tenant, row: dict, changes: dict[str, Any]) -> dict:
    """Apply user edits to a row that hasn't created anything in CollectionSpace yet."""
    if is_locked(row):
        raise ValueError("This document already created records in CollectionSpace and can't be changed.")
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    touched = set(row.get("touched", []))
    for k, v in changes.items():
        if k == "handling":
            if not tenant.handling_by_id(v):
                raise ValueError(f"Unknown handling option {v!r}")
        elif k in ("restricted", "include"):
            v = bool(v)
        elif k == "type":
            if v and v not in tenant.media_types:
                raise ValueError(f"Unknown media type {v!r}")
        elif k in AUTHORITY_FIELDS:
            if v and not v.startswith("urn:cspace:"):
                raise ValueError(f"{k} must be a refName chosen from the authority")
        elif isinstance(v, str):
            v = v.strip()
        row[k] = v
        touched.add(k)
    if "file" in changes:
        p = parse_filename(tenant, row["file"])
        row.update(objParsed=p["obj"], img=p["img"], parseOk=p["ok"])
        if "obj" not in touched:
            row["obj"] = p["obj"]
    if "idnum" not in touched and ("handling" in changes or "file" in changes or "obj" in changes):
        row["idnum"] = default_idnum(tenant, row)
    row["touched"] = sorted(touched)
    return row


def is_locked(row: dict) -> bool:
    """True once the row has created anything in CollectionSpace (finding an existing object doesn't count)."""
    res = row.get("result") or {}
    return any(st.get("csid") for name, st in (res.get("steps") or {}).items() if name != "findObject")


_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def check_rows(tenant: Tenant, rows: list[dict], client: CSpaceClient, perms: dict[str, bool]) -> None:
    """Set each row's checks: [{level: block|warn|info, text}]. "block" rows must be fixed before scheduling."""
    obj_cache: dict[str, list[str]] = {}
    media_cache: dict[str, list[str]] = {}
    seen_ids: dict[str, int] = {}
    for r in rows:
        if r.get("include") and not is_locked(r) and r.get("idnum"):
            seen_ids[r["idnum"]] = seen_ids.get(r["idnum"], 0) + 1

    def objects(num: str) -> list[str]:
        if num not in obj_cache:
            obj_cache[num] = client.find_objects(num)
        return obj_cache[num]

    for r in rows:
        out: list[dict[str, str]] = []
        if not r.get("include"):
            r["checks"] = [{"level": "info", "text": "Disabled: the BMU ignores this document."}]
            continue
        if (r.get("result") or {}).get("state") == "Done":
            r["checks"] = []
            continue
        h = tenant.handling_by_id(r["handling"])
        up = (r.get("upload") or {}).get("s")
        if up != "done":
            out.append({"level": "block", "text": "The file hasn't finished uploading." if up != "failed"
                        else "The upload failed. Remove the document or add the file again."})
        if not perms.get("media"):
            out.append({"level": "block", "text": "Your CollectionSpace account can't create Media records."})
        if h.object != "none" and not perms.get("relations"):
            out.append({"level": "block", "text": "Your account can't create relations, so it can't link to objects. Choose a media-only handling."})
        if h.object == "create" and not perms.get("objects"):
            out.append({"level": "block", "text": "Your account can't create Object records. Choose another handling."})
        if h.object != "none":
            num = (r.get("obj") or "").strip()
            if not num:
                out.append({"level": "block", "text": "No object number. The filename doesn't follow the rule: " + tenant.filename_hint + "."})
            else:
                try:
                    found = objects(num)
                except CSpaceError as e:
                    found = None
                    out.append({"level": "warn", "text": f"Couldn't check object {num} in CollectionSpace ({e.code})."})
                if found is not None:
                    if h.object == "existing" and not found:
                        out.append({"level": "block", "text": f"No object {num} in CollectionSpace. Correct the object number, or choose “Create new object + link” or media only."})
                    elif h.object == "existing" and len(found) > 1:
                        out.append({"level": "block", "text": f"Object number {num} matches {len(found)} objects in CollectionSpace. Correct the object number so it identifies one object."})
                    elif h.object == "create" and found:
                        out.append({"level": "block", "text": f"Object {num} already exists. Choose “Link to existing object” instead."})
        idn = r.get("idnum") or ""
        if not idn:
            out.append({"level": "block", "text": "The Media record needs an identification number."})
        else:
            if seen_ids.get(idn, 0) > 1:
                out.append({"level": "warn", "text": f"Another document in this job also has ID {idn}."})
            try:
                if idn not in media_cache:
                    media_cache[idn] = client.find_media(idn)
                if media_cache[idn]:
                    out.append({"level": "warn", "text": f"A Media record with ID {idn} already exists in CollectionSpace."})
            except CSpaceError:
                pass
        if r.get("date") and not _DATE.match(r["date"]):
            out.append({"level": "warn", "text": f"CollectionSpace can't interpret the date “{r['date']}”; it will be saved as text only."})
        r["checks"] = out


def worst(row: dict) -> str:
    levels = {c["level"] for c in row.get("checks", [])}
    return "block" if "block" in levels else ("warn" if "warn" in levels else "ok")
