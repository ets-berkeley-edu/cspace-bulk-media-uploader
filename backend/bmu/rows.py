"""Row model: defaults from the filename, editable fields, and checks against CollectionSpace."""
from __future__ import annotations

import re
import time
from typing import Any, Callable

from .cspace import CSpaceClient, CSpaceError
from .sensitivity import evaluate as evaluate_sensitivity
from .tenant import OBJECT_STEPS, Tenant, parse_filename

EDITABLE = {"handling", "obj", "idnum", "date", "restricted", "type", "language", "creator", "contributor",
            "rightsHolder", "description", "copyright", "include", "file", "skipLink", "group"}
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


def new_row(tenant: Tenant, filename: str, size: int, content_type: str, date: str = "", orientation: str = "") -> dict[str, Any]:
    """A new document. date and orientation: what the browser read from the image's EXIF before the upload; the
    date pre-fills the Date field (the user can change or clear it)."""
    p = parse_filename(tenant, filename)
    row: dict[str, Any] = {
        "file": filename, "fileOriginal": filename, "size": size, "contentType": content_type or "",
        "handling": tenant.handling[0].id, "objParsed": p["obj"], "obj": p["obj"], "img": p["img"], "parseOk": p["ok"],
        "idnum": "", "date": date, "orientation": orientation, "restricted": bool(tenant.publish.get("default", False)),
        "type": [], "language": [tenant.language_default], "creator": "", "contributor": "", "rightsHolder": "", "description": "", "copyright": "",
        "include": True, "group": True, "upload": {"s": "pending"}, "checks": [], "result": None, "touched": [],
    }
    row["idnum"] = default_idnum(tenant, row)
    return row


def default_idnum(tenant: Tenant, row: dict) -> str:
    h = tenant.handling_by_id(row["handling"])
    return row["img"] if h and h.id_rule == "image" else row["obj"]


def edit_problem(row: dict, changes: dict[str, Any]) -> str | None:
    """Why this row can't take these changes, or None. Changes that match the row's current values are no
    change, so they never count against it (design: bulk-change panel).

    After a run (design: Fixing a job after a run) what can change depends on the row's result: nothing on a
    Done row; on a row whose Media record exists (Partial), only what the rerun still needs (fix_fields); on a
    Failed row whose object step ran, everything except its handling and object number."""
    real = {k: v for k, v in changes.items() if row.get(k) != v}
    if not real:
        return None
    if (row.get("result") or {}).get("state") == "Done":
        return "done"
    if set(real) == {"include"}:
        return None  # any row with work left can be excluded or included again, a Partial one too
    if not row.get("include", True):
        return "excluded"
    if "group" in real and _group_done(row):
        return "grouped"
    if media_created(row):
        return None if set(real) <= fix_fields(row) | {"group"} else "created"
    if "skipLink" in real:
        return "created"  # only for a row whose Media record exists
    if ("handling" in real or "obj" in real) and object_step_ran(row):
        return "handling"
    return None


def _group_done(row: dict) -> bool:
    return (_steps(row).get("addToGroup") or {}).get("s") == "done"


PROBLEM_TEXT = {
    "done": "This document is done; there is nothing left to change.",
    "excluded": "This document is excluded from the job. Include it first.",
    "created": "This document's Media record already exists in CollectionSpace, so only what the rerun still needs can "
               "change here. To change the Media record's fields, edit it in CollectionSpace.",
    "handling": "The last run already found or created this document's object, so its handling and object number can't change.",
    "relink": "This document's Media record already exists. Its handling can change only after the last run found that "
              "its object already existed, and only to a handling that links to that object.",
    "grouped": "This document's object is already in the job's group in CollectionSpace.",
}

FINISHED = ("done", "not needed")
OBJ_STEPS = OBJECT_STEPS
REL_STEPS = ("relMediaObject", "relObjectMedia")


def _steps(row: dict) -> dict:
    return (row.get("result") or {}).get("steps") or {}


def open_steps(row: dict, names: tuple[str, ...]) -> list[str]:
    """Which of these steps the row has and hasn't finished."""
    st = _steps(row)
    return [n for n in names if n in st and st[n].get("s") not in FINISHED]


def media_created(row: dict) -> bool:
    return (_steps(row).get("media") or {}).get("s") == "done"


def fix_fields(row: dict) -> set[str]:
    """What a user may change on a row whose Media record already exists: only what the rerun still needs.
    A corrected object number when the object step failed on its number; stopping the link when the object
    wasn't found (or matched several, or already existed) or relations weren't allowed; Exclude. When "Create new
    object + link" found that its object already existed (object_exists), also the handling, to one that links
    to the existing object (design: Fixing a job after a run)."""
    st = _steps(row)
    allowed = {"include"}
    obj_codes = {st[n].get("code") for n in OBJ_STEPS if n in st and st[n].get("s") == "failed"}
    rel_codes = {st[n].get("code") for n in REL_STEPS if n in st and st[n].get("s") == "failed"}
    if obj_codes & {"object_gone", "object_ambiguous", "object_rejected", "object_exists"} and not row.get("skipLink"):
        allowed.add("obj")
    if "object_exists" in obj_codes and not row.get("skipLink"):
        allowed.add("handling")
    if open_steps(row, REL_STEPS) and (obj_codes & {"object_gone", "object_ambiguous", "object_exists"} or "no_permission" in rel_codes):
        allowed.add("skipLink")
    return allowed


RELINK_OBJECT = ("existing", "either")  # what a row whose Media record exists may switch to after object_exists


def can_replace_file(row: dict) -> bool:
    """A replacement file is for a row whose Media record exists and whose upload hasn't succeeded (for
    example rejected as too large, or the staged file was lost). The rerun uploads it to that Media record."""
    return media_created(row) and bool(open_steps(row, ("upload",))) and row.get("include", True)


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
    if "handling" in changes and changes["handling"] != row.get("handling") and media_created(row):
        target = tenant.handling_by_id(changes["handling"])
        if not target or target.object not in RELINK_OBJECT:
            raise ValueError(PROBLEM_TEXT["relink"])
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
        elif k in ("restricted", "include", "skipLink", "group"):
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
        if k == "restricted":
            row["restrictedAuto"] = False  # the user's choice now stands, protected or not
    if "file" in changes:  # re-parse the new name; the object number follows it unless it was edited
        p = parse_filename(tenant, row["file"])
        row.update(objParsed=p["obj"], img=p["img"], parseOk=p["ok"])
        if "obj" not in changes and row.get("obj") == old_obj_parsed:
            row["obj"] = p["obj"]
    if "idnum" not in changes and row.get("idnum") == old_id_default and not media_created(row):
        row["idnum"] = default_idnum(tenant, row)  # it still held its derived value, so it follows
    row["touched"] = sorted(touched)
    return row


def object_step_ran(row: dict) -> bool:
    """A Failed row whose object step already ran keeps its object, so its handling can't change."""
    return any((_steps(row).get(k) or {}).get("s") == "done" for k in OBJ_STEPS)


def is_locked(row: dict) -> bool:
    """True once the row has created anything in CollectionSpace (finding an existing object doesn't count),
    so it can't be deleted (design: Deleting a row). A row the worker was on when it stopped counts too: a
    create may have reached CollectionSpace before it was recorded."""
    res = row.get("result") or {}
    if res.get("state") == "In progress":
        return True
    return any(st.get("csid") and not st.get("found") and not st.get("sameAs")
               for name, st in (res.get("steps") or {}).items() if name != "findObject")


def created_records(rows: list[dict], job: dict | None = None) -> dict:
    """What a job's runs created in CollectionSpace, by record type, and how many documents are unfinished
    (a Media record without its file or its links). For the job-deletion warning and audit entry."""
    c = {"media": 0, "files": 0, "objects": 0, "relations": 0, "groups": 0, "unfinished": 0}
    csids: list[dict] = []
    g = (job or {}).get("groupStep") or {}
    if g.get("s") == "done":
        c["groups"] = 1
        csids.append({"row": 0, "file": "", "step": "group", "csid": g["csid"]})
    kind = {"media": "media", "upload": "files", "createObject": "objects", "findOrCreateObject": "objects", "relMediaObject": "relations",
            "relObjectMedia": "relations", "addToGroup": "relations"}
    for r in rows:
        st = _steps(r)
        for name, x in st.items():
            if x.get("s") == "done" and x.get("csid") and not x.get("found") and not x.get("sameAs") and name in kind:
                for key in ("csid", "csid2"):
                    if x.get(key):
                        c[kind[name]] += 1
                        csids.append({"row": r["n"], "file": r["file"], "step": name, "csid": x[key]})
        if media_created(r) and any(x.get("s") not in FINISHED for x in st.values()):
            c["unfinished"] += 1
    return {"counts": c, "csids": csids}


# The design's supported file types, the same for every tenant: images, audio, video and 3D models.
SUPPORTED_EXTENSIONS = {"jpg", "jpeg", "tif", "tiff", "png", "wav", "mp3", "aac", "mp4", "x3d"}
SUPPORTED_HINT = "JPEG, TIFF, PNG, WAV, MP3, AAC, MP4 or X3D"

# How long a row's CollectionSpace lookup (object or Media search) is reused while editing. Scheduling always
# looks everything up again.
LOOKUP_TTL_SECONDS = 600


def check_rows(tenant: Tenant, rows: list[dict], client: CSpaceClient, perms: dict[str, bool],
               targets: set[int] | None = None, refresh: bool = False, group_on: bool = False) -> set[int]:
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
        if r.get("include") and not media_created(r) and r.get("idnum"):
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

    def sensitivity(r: dict, csid: str) -> dict | None:
        """The linked Object's sensitivity (design: Protected files), kept like a lookup; None if not known yet."""
        if not csid:
            return {"protect": [], "warn": [], "hides": False}
        stored = (r.get("lookups") or {}).get("objectSensitivity")
        may_query = targets is None or r["n"] in targets
        if stored is not None and stored.get("value") == csid and not refresh and (not may_query or now - stored["at"] < LOOKUP_TTL_SECONDS):
            return stored
        if not may_query:
            incomplete.add(r["n"])
            return None
        if ("objectSensitivity", csid) not in batch:
            batch[("objectSensitivity", csid)] = evaluate_sensitivity(tenant.sensitivity, client.get_object(csid))  # type: ignore[assignment]
        entry = {"value": csid, **batch[("objectSensitivity", csid)], "at": int(now)}  # type: ignore[dict-item]
        r.setdefault("lookups", {})["objectSensitivity"] = entry
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
            r["checks"] = [{"level": "info", "text": "Excluded from the job: the BMU ignores this document."}]
            continue
        if (r.get("result") or {}).get("state") == "Done":
            r["checks"] = []
            continue
        h = tenant.handling_by_id(r["handling"])
        if media_created(r):
            r["checks"] = _rerun_checks(tenant, r, perms, lookup, client, group_on)
            continue
        up = (r.get("upload") or {}).get("s")
        if up == "failed" and (r.get("upload") or {}).get("reason") == "removed":
            out.append({"level": "block", "text": "The BMU removed this protected file's upload after the job stopped, as it does for "
                                                  "protected files. Add it again (Retry), or remove the document."})
        elif up == "failed":
            out.append({"level": "block", "text": "The upload failed. Retry it, or remove the document."})
        elif up != "done":
            out.append({"level": "block", "text": "The file hasn't finished uploading. If it isn't uploading in your browser now "
                                                  "(for example the page was closed), Retry it, or remove the document."})
        ext = r["file"].rsplit(".", 1)[-1].lower() if "." in r["file"] else ""
        if ext not in SUPPORTED_EXTENSIONS:
            out.append({"level": "block", "text": f"The BMU doesn't accept .{ext or '(no extension)'} files. "
                                                  f"Supported types: {SUPPORTED_HINT}."})
        if not perms.get("media"):
            out.append({"level": "block", "text": "Your CollectionSpace account can't create Media records."})
        elif not perms.get("mediaUpdate", True):
            out.append({"level": "block", "text": "Your account can't update Media records, which attaching the file needs "
                                                  "(update on media). Ask a CollectionSpace administrator for the permission."})
        if h.object != "none" and not perms.get("readObjects", True):
            out.append({"level": "block", "text": "Your account can't read Object records, so the BMU can't find this document's "
                                                  "object. Choose a media-only handling, or ask for read on objects."})
        if h.object != "none" and not perms.get("relations"):
            out.append({"level": "block", "text": "Your account can't create relations, so it can't link to objects. Choose a media-only handling."})
        if h.object == "create" and not perms.get("objects"):
            out.append({"level": "block", "text": "Your account can't create Object records. Choose another handling."})
        # "either" needs create on objects only when its object doesn't exist yet: checked after the lookup below
        if group_on and r.get("group", True) and h.object != "none" and not perms.get("groups"):
            out.append({"level": "block", "text": "Your account can't create groups. Turn off the job's group, or untick this document's Group."})
        obj_csid: str | None = ""  # the linked Object: "" none, None not known yet
        if h.object != "none" and object_step_ran(r):
            obj_csid = next(_steps(r)[k]["csid"] for k in OBJ_STEPS if (_steps(r).get(k) or {}).get("s") == "done")
        if h.object != "none" and not object_step_ran(r):  # a found or created object is reused by the rerun
            obj_csid = None
            num = (r.get("obj") or "").strip()
            if not num:
                obj_csid = ""
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
                    obj_csid = found[0] if len(found) == 1 and h.object != "create" else ""
                    out += object_checks(tenant, h.object, num, found, perms)
        if obj_csid is not None:
            try:
                sens = sensitivity(r, obj_csid)
            except CSpaceError as e:
                sens = None
                out.append({"level": "warn", "text": f"Couldn't read object {r.get('obj')}'s sensitivity in CollectionSpace ({e.code})."})
            if sens is not None:
                apply_sensitivity(tenant, r, sens)
        out += sensitivity_checks(tenant, r)
        idn = r.get("idnum") or ""
        if not idn:
            out.append({"level": "block", "text": "The Media record needs an identification number."})
        else:
            if seen_ids.get(idn, 0) > 1:
                out.append({"level": "warn", "text": f"Another document in this job also has ID {idn}."})
            try:
                existing = lookup(r, "media", idn, client.find_media) if perms.get("readMedia", True) else None
            except CSpaceError:
                existing = None
            if not perms.get("readMedia", True):
                out.append({"level": "warn", "text": "Your account can't read Media records, so the BMU can't check whether "
                                                     f"a Media record with ID {idn} already exists."})
            if existing:
                out.append({"level": "warn", "text": f"A Media record with ID {idn} already exists in CollectionSpace "
                                                     f"(CSID {', '.join(existing[:5])}{' …' if len(existing) > 5 else ''})."})
        if r.get("date") and not perms.get("readDates", True):
            out.append({"level": "block", "text": "Your account can't use CollectionSpace's date parser (read on structureddates), "
                                                  "so the date can't be checked. Clear the date, or ask for the permission."})
        elif r.get("date"):
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
        if r.get("orientation"):  # design: Image orientation, information only (read by the browser from the image)
            out.append({"level": "info", "text": f"Orientation: {r['orientation']}."})
        r["checks"] = out
    return incomplete


def _labels(tenant: Tenant, behaviors: tuple[str, ...]) -> str:
    """The tenant's handling labels with these object behaviors, quoted and joined with "or"."""
    names = [f"“{h.label}”" for h in tenant.handling if h.object in behaviors]
    return " or ".join(names)


def object_checks(tenant: Tenant, behavior: str, num: str, found: list[str], perms: dict[str, bool],
                  rerun: bool = False) -> list[dict]:
    """Design (Validation while editing): what the object lookup means for each handling's object behavior.
    Find (existing): exactly one object. Create: none may exist yet. Find or create (either): at most one, and
    creating it needs create on objects. rerun: the row's Media record exists (Partial), so its handling is
    fixed, except after object_exists, and "stop linking" is the other way out."""
    stop = ", or stop linking this document" if rerun else ""
    if behavior == "create" and found:
        return [{"level": "block", "text": f"Object {num} already exists in CollectionSpace, and “Create new object + link” "
                                           f"only creates a new object. To link to it, choose {_labels(tenant, RELINK_OBJECT)}; "
                                           f"otherwise correct the object number{stop}."}]
    if behavior != "create" and len(found) > 1:
        return [{"level": "block", "text": f"Object number {num} matches {len(found)} objects in CollectionSpace. Correct the "
                                           f"object number so it identifies one object{stop}."}]
    if behavior == "existing" and not found:
        media_only = any(h.object == "none" for h in tenant.handling)
        choices = " or ".join(c for c in (_labels(tenant, ("either", "create")), "media only" if media_only else "") if c)
        tail = stop if rerun else (f", or choose {choices}" if choices else "")
        return [{"level": "block", "text": f"No object {num} in CollectionSpace. Correct the object number{tail}."}]
    # (while editing, "create" without the permission is blocked before the lookup, whatever it finds)
    if (behavior == "either" or (rerun and behavior == "create")) and not found and not perms.get("objects"):
        tail = stop if rerun else ", or choose another handling"
        return [{"level": "block", "text": f"No object {num} in CollectionSpace, and your account can't create Object "
                                           f"records. Correct the object number{tail}."}]
    return []


def apply_sensitivity(tenant: Tenant, r: dict, sens: dict) -> None:
    """Set the row's automatic protected-file flag from its Object (design: Setting the flag): users never
    set or clear it. A protected file defaults to not published (Restricted), unless the user chose."""
    was = r.get("protected")
    r["protected"] = {"reason": "; ".join(sens["protect"]), "hides": bool(sens["hides"])} if sens["protect"] else None
    r["softSignals"] = list(sens.get("warn") or [])
    user_chose = "restricted" in (r.get("touched") or [])
    if r["protected"] and not user_chose and not r.get("restricted") and tenant.publish.get("invert"):
        r["restricted"], r["restrictedAuto"] = True, True
    elif not r["protected"] and was and r.get("restrictedAuto") and not user_chose:
        r["restricted"], r["restrictedAuto"] = bool(tenant.publish.get("default", False)), False


def sensitivity_checks(tenant: Tenant, r: dict) -> list[dict]:
    out: list[dict[str, str]] = []
    p = r.get("protected")
    header = tenant.publish.get("header", "Restricted")
    if p:
        out.append({"level": "info", "text": f"Protected file: {p['reason']}. Others in the BMU see a locked preview instead of a "
                                             f"thumbnail, {header} is on by default, and a draft with protected files expires 7 days "
                                             "after it was last saved."})
        if not r.get("restricted") and not p.get("hides"):
            out.append({"level": "warn", "text": f"This protected file would appear on the public portal: {header} is off. Check "
                                                 f"{header} unless the image is meant to be public."})
    elif r.get("softSignals") and not r.get("restricted"):
        out.append({"level": "warn", "text": f"Object {r.get('obj')} has {', '.join(r['softSignals'])}. Consider checking {header}; "
                                             "nothing is set automatically."})
    return out


def _rerun_checks(tenant: Tenant, r: dict, perms: dict[str, bool], lookup, client: CSpaceClient,
                  group_on: bool = False) -> list[dict]:
    """Checks for a row whose Media record already exists (Partial): only what the rerun still has to do.
    Its fields, identification number and date went to CollectionSpace already and aren't checked again."""
    out: list[dict[str, str]] = []
    if r.get("protected"):
        out.append({"level": "info", "text": f"Protected file: {r['protected']['reason']}."})
    st = _steps(r)
    skip = bool(r.get("skipLink"))
    h = tenant.handling_by_id(r["handling"])
    obj_step = h.object_step if h else None
    # An object step of an earlier handling (before a change after object_exists) is no longer planned
    names = [n for n in st if not (n in OBJ_STEPS and n != obj_step)]
    if obj_step and obj_step not in st and not object_step_ran(r):
        names.insert(1, obj_step)
    todo = list(dict.fromkeys(STEP_TEXT.get(n, n) for n in names
                              if (st.get(n) or {}).get("s") not in FINISHED and not (skip and n in OBJ_STEPS + REL_STEPS + ("addToGroup",))))
    out.append({"level": "info", "text": ("The rerun will only " + " and ".join(todo) + "." if todo
                                          else "Nothing is left to do for this document; the rerun skips it.")
                + (" Its remaining object steps are skipped: you stopped linking it to an object." if skip else "")})
    if open_steps(r, ("upload",)):
        code = st["upload"].get("code")
        up = (r.get("upload") or {}).get("s")
        replaced = r.get("replacedFor") == (r.get("result") or {}).get("run")
        if up == "failed" and (r.get("upload") or {}).get("reason") == "removed":
            out.append({"level": "block", "text": "The BMU removed this protected file's upload after the job stopped. Choose Replace "
                                                  "file to add it again."})
        elif up == "failed":
            out.append({"level": "block", "text": "The replacement file didn't upload. Choose Replace file again."})
        elif up != "done":
            out.append({"level": "block", "text": "The replacement file hasn't finished uploading."})
        elif code == "file_missing" and not replaced:
            out.append({"level": "block", "text": "The file the BMU was holding is gone. Choose Replace file to add it again."})
        elif code in ("upload_too_large", "file_type_rejected") and not replaced:
            out.append({"level": "warn", "text": "CollectionSpace rejected this file in the last run. Replace the file, or the upload "
                                                 "will most likely fail again."})
        if replaced:
            ext = r["file"].rsplit(".", 1)[-1].lower() if "." in r["file"] else ""
            if ext not in SUPPORTED_EXTENSIONS:
                out.append({"level": "block", "text": f"The BMU doesn't accept .{ext or '(no extension)'} files. Supported types: {SUPPORTED_HINT}."})
    if skip:
        return out
    if group_on and r.get("group", True) and not _group_done(r) and not perms.get("groups"):
        out.append({"level": "block", "text": "Your account can't create groups. Turn off the job's group, or untick this document's Group."})
    if open_steps(r, REL_STEPS) and not perms.get("relations"):
        out.append({"level": "block", "text": "Your account can't create relations, so this Media record can't be linked to its "
                                              "object. Stop linking it, or have someone who can reschedule the job."})
    # The handling's object step, if it hasn't found or created the object yet (after the handling changed from
    # "Create new object + link", the new step hasn't run at all)
    if obj_step and (st.get(obj_step) or {}).get("s") not in FINISHED and not object_step_ran(r):
        num = (r.get("obj") or "").strip()
        if not num:
            out.append({"level": "block", "text": "Enter the object number, or stop linking this document."})
            return out
        try:
            found = lookup(r, "object", num, client.find_objects)
        except CSpaceError as e:
            found = None
            out.append({"level": "warn", "text": f"Couldn't check object {num} in CollectionSpace ({e.code})."})
        if found is not None:
            out += object_checks(tenant, h.object, num, found, perms, rerun=True)
    return out


STEP_TEXT = {"media": "create the Media record", "findObject": "find the object", "createObject": "create the object",
             "findOrCreateObject": "find or create the object",
             "upload": "upload the file", "relMediaObject": "link it to its object", "relObjectMedia": "link it to its object",
             "addToGroup": "add its object to the job's group"}


def worst(row: dict) -> str:
    levels = {c["level"] for c in row.get("checks", [])}
    return "block" if "block" in levels else ("warn" if "warn" in levels else "ok")
