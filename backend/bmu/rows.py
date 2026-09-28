"""Row model: defaults from the filename, editable fields, and checks against CollectionSpace."""
from __future__ import annotations

import re
import time
from typing import Any, Callable

from .cspace import CSpaceClient, CSpaceError
from .tenant import Tenant, parse_filename

EDITABLE = {"handling", "obj", "idnum", "date", "restricted", "type", "language", "creator", "contributor",
            "rightsHolder", "description", "copyright", "include", "file"}
# Repeating fields (design: Media record fields): media type values from the tenant's option list, and
# language refNames from the languages vocabulary.
REPEATING = {"type", "language"}
_LANGUAGE_REF = re.compile(r"^urn:cspace:[^:]+:vocabularies:name\(languages\):item:name\([^)]+\)'[^']*'$")
AUTHORITY_FIELDS = {"creator", "contributor", "rightsHolder"}

ROW_STATES = ("Not started", "In progress", "Done", "Partial", "Failed")


# ---- filenames (design: Media record fields, Filenames; User interface, Editable numbers and names) ------
MAX_FILENAME = 100
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _split(name: str) -> tuple[str, str]:
    k = name.rfind(".")
    return (name[:k], name[k + 1:]) if k > 0 else (name, "")


def clean_filename(name: str) -> str:
    """The name a file is known by everywhere (title, Blob name, filename rules), cleaned once on the server
    when the browser first reports it: any path stripped, control characters removed, length capped with the
    extension kept. Raises ValueError for names that can't be made safe."""
    base = _CONTROL.sub("", re.split(r"[\\/]", name)[-1]).strip()
    if not base or base in (".", "..") or ".." in base or base.startswith("."):
        raise ValueError(f"The filename “{name}” can't be used. Rename the file and add it again.")
    if len(base) > MAX_FILENAME:
        stem, ext = _split(base)
        base = stem[:MAX_FILENAME - len(ext) - 1] + "." + ext if ext else base[:MAX_FILENAME]
    return base


def filename_problems(tenant: Tenant, name: str, original: str, other_names: list[str]) -> list[str]:
    """Why a new name for a document can't be used (as in the UI mockup); empty when it can."""
    errs: list[str] = []
    orig_ext = _split(original)[1].lower()
    if not name:
        return ["Enter a filename."]
    if len(name) > MAX_FILENAME:
        errs.append(f"Use {MAX_FILENAME} characters or fewer.")
    if "/" in name or "\\" in name:
        errs.append("Remove slashes; a filename can't include a folder.")
    if ".." in name:
        errs.append("Remove the double dot (..).")
    if name.startswith("."):
        errs.append("A filename can't start with a dot.")
    if re.search(r"\s", name):
        errs.append("Remove spaces; use _ or - instead.")
    if not _SAFE_NAME.match(re.sub(r"[\s/\\]", "", name) or "x"):
        errs.append("Use only letters, numbers, dots, hyphens and underscores.")
    stem, ext = _split(name)
    if not ext:
        errs.append(f"Keep the file extension (.{orig_ext}).")
    elif ext.lower() != orig_ext:
        errs.append(f"Keep the extension .{orig_ext}; renaming can't change the file type.")
    if any(o.lower() == name.lower() for o in other_names):
        errs.append("Another document in this job already has this name.")
    if not errs and not tenant.filename_pattern.match(stem):
        errs.append(f"Doesn't match {tenant.name}'s filename pattern: {tenant.filename_hint}.")
    return errs


def new_row(tenant: Tenant, filename: str, size: int, content_type: str) -> dict[str, Any]:
    p = parse_filename(tenant, filename)
    row: dict[str, Any] = {
        "file": filename, "fileOriginal": filename, "size": size, "contentType": content_type or "",
        "handling": tenant.handling[0].id, "objParsed": p["obj"], "obj": p["obj"], "img": p["img"], "parseOk": p["ok"],
        "idnum": "", "date": "", "restricted": bool(tenant.publish.get("default", False)),
        "type": [], "language": [tenant.language_default], "creator": "", "contributor": "", "rightsHolder": "", "description": "", "copyright": "",
        "include": True, "upload": {"s": "pending"}, "checks": [], "result": None, "touched": [],
    }
    row["idnum"] = default_idnum(tenant, row)
    return row


def default_idnum(tenant: Tenant, row: dict) -> str:
    h = tenant.handling_by_id(row["handling"])
    return row["img"] if h and h.id_rule == "image" else row["obj"]


def edit_problem(row: dict, changes: dict[str, Any]) -> str | None:
    """Why this row can't take these changes, or None. Changes that match the row's current values are no
    change, so they never count against it (design: bulk-change panel)."""
    real = {k: v for k, v in changes.items() if row.get(k) != v}
    if not real:
        return None
    if (row.get("result") or {}).get("state") == "Done":
        return "done"
    if set(real) == {"include"}:
        return None  # any row with work left can be disabled or enabled, a Partial one too
    if not row.get("include", True):
        return "disabled"
    if is_locked(row):
        return "created"
    if "handling" in real and object_step_ran(row):
        return "handling"
    return None


PROBLEM_TEXT = {
    "done": "This document is done; there is nothing left to change.",
    "disabled": "This document is disabled. Enable it first.",
    "created": "This document already created records in CollectionSpace and can't be changed.",
    "handling": "The last run already found or created this document's object, so its handling can't change.",
}


def apply_edit(tenant: Tenant, row: dict, changes: dict[str, Any], other_names: list[str] | None = None) -> dict:
    """Apply user edits to a row that hasn't created anything in CollectionSpace yet.

    A new filename must pass the filename rules (other_names: the job's other documents' names). The object
    number and identification number follow what they're derived from (the filename, the handling, the
    object number) for as long as they still hold their derived values; once edited, they keep the edit."""
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    problem = edit_problem(row, changes)
    if problem:
        raise ValueError(PROBLEM_TEXT[problem])
    changes = {k: v for k, v in changes.items() if row.get(k) != v}
    if "file" in changes:
        errs = filename_problems(tenant, str(changes["file"]).strip(), row.get("fileOriginal") or row["file"], other_names or [])
        if errs:
            raise ValueError(" ".join(errs))
    old_obj_parsed, old_id_default = row.get("objParsed", ""), default_idnum(tenant, row)
    touched = set(row.get("touched", []))
    for k, v in changes.items():
        if k == "handling":
            if not tenant.handling_by_id(v):
                raise ValueError(f"Unknown handling option {v!r}")
        elif k in ("restricted", "include"):
            v = bool(v)
        elif k in REPEATING:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise ValueError(f"{k} must be a list of values")
            v = list(dict.fromkeys(x for x in v if x))  # no blanks, no repeats, order kept
            if k == "type":
                bad = [x for x in v if x not in tenant.media_type_values]
                if bad:
                    raise ValueError(f"Unknown media type {bad[0]!r}")
            elif any(not _LANGUAGE_REF.match(x) for x in v):
                raise ValueError("language must be refNames chosen from the languages vocabulary")
        elif k in AUTHORITY_FIELDS:
            if v and not v.startswith("urn:cspace:"):
                raise ValueError(f"{k} must be a refName chosen from the authority")
        elif isinstance(v, str):
            v = v.strip()
        row[k] = v
        touched.add(k)
    if "file" in changes:  # re-parse the new name; the object number follows it unless it was edited
        p = parse_filename(tenant, row["file"])
        row.update(objParsed=p["obj"], img=p["img"], parseOk=p["ok"])
        if "obj" not in changes and row.get("obj") == old_obj_parsed:
            row["obj"] = p["obj"]
    if "idnum" not in changes and row.get("idnum") == old_id_default:
        row["idnum"] = default_idnum(tenant, row)  # it still held its derived value, so it follows
    row["touched"] = sorted(touched)
    return row


def object_step_ran(row: dict) -> bool:
    """A Failed row whose object step already ran keeps its object, so its handling can't change."""
    steps = (row.get("result") or {}).get("steps") or {}
    return any((steps.get(k) or {}).get("s") == "done" for k in ("findObject", "createObject"))


def is_locked(row: dict) -> bool:
    """True once the row has created anything in CollectionSpace (finding an existing object doesn't count)."""
    res = row.get("result") or {}
    return any(st.get("csid") for name, st in (res.get("steps") or {}).items() if name != "findObject")




# The design's supported file types, the same for every tenant: images, audio, video and 3D models.
SUPPORTED_EXTENSIONS = {"jpg", "jpeg", "tif", "tiff", "png", "wav", "mp3", "aac", "mp4", "x3d"}
SUPPORTED_HINT = "JPEG, TIFF, PNG, WAV, MP3, AAC, MP4 or X3D"

# How long a row's CollectionSpace lookup (object or Media search) is reused while editing. Scheduling always
# looks everything up again.
LOOKUP_TTL_SECONDS = 600


def check_rows(tenant: Tenant, rows: list[dict], client: CSpaceClient, perms: dict[str, bool],
               targets: set[int] | None = None, refresh: bool = False) -> set[int]:
    """Set each row's checks: [{level: block|warn|info, text}]. "block" rows must be fixed before scheduling.

    The editor calls this for the rows that just changed (targets) and re-evaluates every row, because some
    checks depend on other rows (duplicate identification numbers in the job). CollectionSpace lookups are
    kept on the row under "lookups" and reused while the searched value is unchanged: only target rows
    whose lookup is missing, for a different value or older than LOOKUP_TTL_SECONDS query CollectionSpace.
    targets=None means every row may query; refresh=True ignores stored lookups (used at scheduling).
    Returns the rows whose lookups weren't known, so their checks are partial and must not be saved.
    """
    now = time.time()
    batch: dict[tuple[str, str], list[str]] = {}  # one search per value per call
    incomplete: set[int] = set()  # rows whose lookups weren't known: their checks here are partial
    seen_ids: dict[str, int] = {}
    for r in rows:
        if r.get("include") and not is_locked(r) and r.get("idnum"):
            seen_ids[r["idnum"]] = seen_ids.get(r["idnum"], 0) + 1

    def parsed_date(r: dict, text: str) -> dict | None:
        """{"ok": bool, "group": {...}} from CollectionSpace's date parser, kept like a lookup; None if not
        known yet (not a target row)."""
        stored = (r.get("lookups") or {}).get("date")
        if stored is not None and stored.get("value") == text and not refresh:
            return stored
        if not (targets is None or r["n"] in targets):
            incomplete.add(r["n"])
            return None
        group = client.parse_date(text)
        entry = {"value": text, "ok": group is not None, "group": group or {}, "at": int(now)}
        r.setdefault("lookups", {})["date"] = entry
        return entry

    def lookup(r: dict, kind: str, value: str, search: Callable[[str], list[str]]) -> list[str] | None:
        """CSIDs found for value, from the row's stored lookup or a new search; None when not known yet."""
        stored = (r.get("lookups") or {}).get(kind)
        same = stored is not None and stored.get("value") == value
        may_query = targets is None or r["n"] in targets
        if same and not refresh and (not may_query or now - stored["at"] < LOOKUP_TTL_SECONDS):
            return list(stored["csids"])
        if not may_query:
            incomplete.add(r["n"])
            return None
        if (kind, value) not in batch:
            batch[(kind, value)] = search(value)
        r.setdefault("lookups", {})[kind] = {"value": value, "csids": batch[(kind, value)], "at": int(now)}
        return list(batch[(kind, value)])

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
        if up == "failed":
            out.append({"level": "block", "text": "The upload failed. Remove the document or add the file again."})
        elif up != "done":
            out.append({"level": "block", "text": "The file hasn't finished uploading."})
        ext = r["file"].rsplit(".", 1)[-1].lower() if "." in r["file"] else ""
        if ext not in SUPPORTED_EXTENSIONS:
            out.append({"level": "block", "text": f"The BMU doesn't accept .{ext or '(no extension)'} files. "
                                                  f"Supported types: {SUPPORTED_HINT}."})
        if not perms.get("media"):
            out.append({"level": "block", "text": "Your CollectionSpace account can't create Media records."})
        if h.object != "none" and not perms.get("relations"):
            out.append({"level": "block", "text": "Your account can't create relations, so it can't link to objects. Choose a media-only handling."})
        if h.object == "create" and not perms.get("objects"):
            out.append({"level": "block", "text": "Your account can't create Object records. Choose another handling."})
        if h.object != "none":
            num = (r.get("obj") or "").strip()
            if not num:
                media_only = any(x.object == "none" for x in tenant.handling)
                out.append({"level": "block", "text": f"No object number: the filename doesn't match {tenant.name}'s filename pattern "
                            f"({tenant.filename_hint}). Rename the file, enter the object number"
                            + (", or choose a media-only handling." if media_only else ".")})
            else:
                try:
                    found = lookup(r, "object", num, client.find_objects)
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
                existing = lookup(r, "media", idn, client.find_media)
            except CSpaceError:
                existing = None
            if existing:
                out.append({"level": "warn", "text": f"A Media record with ID {idn} already exists in CollectionSpace "
                                                     f"(CSID {', '.join(existing[:5])}{' …' if len(existing) > 5 else ''})."})
        if r.get("date"):
            # Design (Structured dates): parsed by CollectionSpace's own parser; a date it can't interpret
            # blocks, which is stricter than its own UI.
            try:
                pd = parsed_date(r, r["date"])
            except CSpaceError as e:
                pd = None
                out.append({"level": "block", "text": f"Couldn't check the date with CollectionSpace ({e.code}). It is checked again when you schedule."})
            if pd is not None and not pd["ok"]:
                out.append({"level": "block", "text": f"CollectionSpace can't interpret the date “{r['date']}”. Correct it or clear it."})
        elif (r.get("lookups") or {}).get("date"):
            r["lookups"].pop("date")
        r["checks"] = out
    return incomplete


def worst(row: dict) -> str:
    levels = {c["level"] for c in row.get("checks", [])}
    return "block" if "block" in levels else ("warn" if "warn" in levels else "ok")
