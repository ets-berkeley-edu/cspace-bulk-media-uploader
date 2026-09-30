#!/usr/bin/env python3
"""Check the BMU's CollectionSpace calls against a real server (e.g. the Lyrasis QA tenant).

Read-only by default. With --create it runs one real document through the worker's steps, in the
design's order (Media record, then the file with PUT media/{csid}/blob, a skeletal Object and both
Relations) using a tiny generated image; those records stay.

  export CSPACE_URL=https://pahma.qa.collectionspace.org CSPACE_USER=... CSPACE_PASSWORD=...
  python scripts/check_cspace.py --object 1-2345 --term smith [--create]
  python scripts/check_cspace.py --vocabularies   # only list the Person and Organization vocabularies
  python scripts/check_cspace.py --roles          # only show the account's roles and whether it is a BMU scheduler
  python scripts/check_cspace.py --terms person:7475 "urn:cspace:...:item:name(abc)'Name'"
                                                  # only read authority terms one by one, as the BMU's term check does

Run from the backend directory's environment (pip install -e backend).
"""
import argparse
import io
import os
import sys
import time

from bmu.cspace import CSpaceClient, CSpaceError
from defusedxml import ElementTree as SafeET

from bmu.sensitivity import evaluate as evaluate_sensitivity
from bmu.cspace.payloads import group_xml, media_xml, object_xml, relation_xml
from bmu.rows import new_row
from bmu.tenant import AUTHORITY_REF, load_tenant

# 1x1 transparent PNG
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def step(label, fn):
    t = time.time()
    try:
        out = fn()
        print(f"OK   {label} ({time.time() - t:.2f}s): {out}")
        return out
    except CSpaceError as e:
        print(f"FAIL {label}: {e.code} {e.detail}")
        return None


def _repeating(c: CSpaceClient, media: str) -> dict:
    """The Media record's media types and languages as saved."""
    from defusedxml import ElementTree as ET
    root = ET.fromstring(c._request("GET", f"media/{media}").content)
    vals = lambda tag: [e.text for e in root.iter() if e.tag.rsplit("}", 1)[-1] == tag]
    date = {e.tag.rsplit("}", 1)[-1]: e.text for g in root.iter() if g.tag.rsplit("}", 1)[-1] == "dateGroup" for e in g if e.text}
    return {"type": vals("type"), "language": vals("language"), "date": date}


def check_term(c: CSpaceClient, t, term: str) -> None:
    """Read one authority term the way the BMU's term check does (GET <authority>/urn:cspace:name(<vocabulary>)/
    items/urn:cspace:name(<shortId>)) and print the raw answer and the BMU's verdict. Read-only."""
    m = AUTHORITY_REF.match(term)
    if m:
        service, vocab, short, shown = m["service"], m["vocab"], m["short"], m["display"]
    else:
        kind, _, short = term.partition(":")
        cfg = t.authorities.get(kind) or next((v for k, v in t.authorities.items() if k.startswith(kind)), None)
        if not cfg or not short:
            print(f"SKIP {term}: expected a refName or <authority>:<short identifier>, "
                  f"with <authority> one of {', '.join(t.authorities)}")
            return
        service, vocab, shown = cfg["service"], cfg["vocabulary"], None
    path = f"{service}/urn:cspace:name({vocab})/items/urn:cspace:name({short})"
    print(f"--   {term}")
    try:
        r = c._request("GET", path)
    except CSpaceError as e:
        print(f"     GET {path} -> {e.status or e.code} {e.detail}")
        verdict = "missing (404)" if e.status == 404 else "couldn't check: the row would get a warning, not a block"
        print(f"     the BMU concludes: {verdict}")
        return
    print(f"     GET {path} -> {r.status_code}")
    fields: list[tuple[str, str]] = []
    for el in SafeET.fromstring(r.content).iter():
        if len(el) == 0 and (el.text or "").strip():
            fields.append((el.tag.rsplit("}", 1)[-1], el.text.strip()))
    get = lambda name: next((v for k, v in fields if k == name), "")
    print(f"     workflowState: {get('workflowState') or '(none)'}")
    print(f"     refName: {get('refName') or '(none)'}")
    print("     every field (element: value); look for one that names a replacement term:")
    for k, v in fields:
        print(f"       {k}: {v[:100]}")
    current = c.authority_term(service, vocab, short)
    if current is None:
        verdict = "missing (deleted): the row is blocked"
    elif shown is not None and current != term:
        verdict = f"exists, renamed: a draft's row would take {current}"
    else:
        verdict = "exists"
    print(f"     the BMU concludes: {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--object", default="1-2345", help="an object number that exists on the server")
    ap.add_argument("--term", default="smi", help="text to search the Person and Organization authorities for")
    ap.add_argument("--create", action="store_true", help="create real test records (they are not deleted)")
    ap.add_argument("--show-object", action="store_true",
                    help="print the Object record's fields and what the tenant's sensitivity rules make of it")
    ap.add_argument("--tenant", default="pahma")
    ap.add_argument("--vocabularies", action="store_true",
                    help="only list the server's Person and Organization vocabularies (is there a 'shared' one?)")
    ap.add_argument("--roles", action="store_true",
                    help="only show the account's tenant id and roles (accounts/0/accountroles) and whether it is a "
                         "BMU scheduler for the tenant (design: Job scheduling)")
    ap.add_argument("--terms", nargs="+", metavar="TERM",
                    help="only read these authority terms one by one, as the BMU's term check does, and show what "
                         "CollectionSpace returns (workflow state, refName, every field) and what the BMU concludes. "
                         "A TERM is a full refName, or <authority>:<short identifier> with <authority> one of the "
                         "tenant's (e.g. person:7475). Use it to see how a deleted, merged or renamed term reads "
                         "(design: Authority term fields)")
    a = ap.parse_args()
    url, user, pw = os.environ.get("CSPACE_URL"), os.environ.get("CSPACE_USER"), os.environ.get("CSPACE_PASSWORD")
    if not (url and user and pw):
        sys.exit("Set CSPACE_URL, CSPACE_USER and CSPACE_PASSWORD")
    t = load_tenant(a.tenant)
    c = CSpaceClient(url, user, pw)
    if a.terms:
        for term in a.terms:
            check_term(c, t, term)
        return
    if a.roles:
        roles = step("accountroles", lambda: c.account_roles())
        if roles is not None:
            print(f"     tenantId: {roles.tenant_id or '(none)'}")
            print(f"     roles: {', '.join(roles.role_names) or '(none)'}")
            wanted = t.scheduler_role_names(roles.tenant_id)
            print(f"     BMU scheduler for {t.key}: {'yes' if t.is_scheduler(roles.tenant_id, roles.role_names) else 'no'}"
                  f" (scheduler roles: {', '.join(wanted) or 'none configured'})")
        return
    if a.vocabularies:
        configured = {cfg["service"]: cfg["vocabulary"] for cfg in t.authorities.values()}
        for service in ("personauthorities", "orgauthorities"):
            vocabs = step(f"{service} vocabularies", lambda s=service: [v["shortIdentifier"] for v in c.authority_vocabularies(s)])
            if vocabs is not None:
                extra = [v for v in vocabs if v != configured.get(service)]
                print(f"     the BMU searches: {configured.get(service)}; also on the server: {extra or 'nothing'}"
                      + ("  <- 'shared' exists: consider adding it to the tenant's authorities" if "shared" in vocabs else ""))
        return
    perms = step("accountperms", lambda: c.account_permissions())
    if perms:
        print("     summary:", perms.summary)
        print("     resources:", {k: "".join(sorted(v)) for k, v in sorted(perms.resources.items()) if k in (
            "media", "relations", "collectionobjects", "groups", "personauthorities", "orgauthorities")})
    found = step(f"find object {a.object}", lambda: c.find_objects(a.object))
    if a.show_object and found:
        xml = c.get_object(found[0])
        print("     fields (element: value), to confirm the sensitivity rules' element names:")
        for el in SafeET.fromstring(xml).iter():
            if len(el) == 0 and (el.text or "").strip():
                print(f"       {el.tag.rsplit('}', 1)[-1]}: {el.text.strip()[:80]}")
        step("sensitivity by the tenant's rules", lambda: evaluate_sensitivity(t.sensitivity, xml))
    step(f"find media id {a.object}", lambda: c.find_media(a.object))
    for kind, cfg in t.authorities.items():
        step(f"search {kind} '{a.term}'", lambda: [x["displayName"] for x in c.search_terms(cfg["service"], cfg["vocabulary"], a.term)][:5])
    langs = step("languages vocabulary (count, first 5)", lambda: (lambda ts: (len(ts), [x["displayName"] for x in ts[:5]]))(c.vocabulary_items("languages")))
    step("tenant's default language is in it", lambda: t.language_default in {x["refName"] for x in c.vocabulary_items("languages")}
         or f"NOT FOUND: {t.language_default}")
    for d in ("circa 1850", "1920s", "March 3, 1911"):
        step(f"parse date '{d}' (structureddates)", lambda d=d: c.parse_date(d))
    step("parse date 'the twenties' (expect None)", lambda: c.parse_date("the twenties"))
    if not a.create:
        print("Read-only checks done. Add --create to test creating records.")
        return
    num = f"BMU-TEST-{int(time.time())}"
    row = new_row(t, f"{num}.png", len(PNG), "image/png")
    row["restricted"] = True
    # repeating fields: two media types and two languages (design: Media type, Language)
    row["type"] = [o.value for o in t.media_types[:2]]
    others = [x["refName"] for x in c.vocabulary_items("languages") if x["refName"] != t.language_default][:1]
    row["language"] = [t.language_default] + others
    # a structured date, parsed by CollectionSpace (design: Structured dates)
    row["date"] = "circa 1850"
    row["lookups"] = {"date": {"value": row["date"], "ok": True, "group": c.parse_date(row["date"]) or {}}}
    # Same order as the worker (design): Media first, then the file with PUT media/{csid}/blob.
    media = step("create Media (no blobCsid)", lambda: c.create_media(media_xml(t, row)))
    if media:
        blob = step("attach file (PUT media/{csid}/blob)", lambda: c.upload_file(media, row["file"], io.BytesIO(PNG), "image/png"))
        blob_csid = step("read back the Media record's blobCsid", lambda: c.media_blob_csid(media))
        if blob_csid:  # the thumbnails the BMU shows once a file is in CollectionSpace (design: Thumbnails)
            step("fetch its Thumbnail derivative (GET blobs/{csid}/derivatives/Thumbnail/content)",
                 lambda: (lambda d: f"{len(d[0])} bytes, {d[1]}")(c.derivative(blob_csid, "Thumbnail")))
        step(f"read back types {row['type']}, {len(row['language'])} languages and the date", lambda: _repeating(c, media))
    obj = step(f"create Object {num}", lambda: c.create_object(object_xml(num)))
    if media and obj:
        step("existing relations Media -> Object (expect none)", lambda: c.find_relations(media, obj))
        step("relate Media -> Object", lambda: c.create_relation(relation_xml(media, "Media", obj, "CollectionObject")))
        step("relate Object -> Media", lambda: c.create_relation(relation_xml(obj, "CollectionObject", media, "Media")))
        step("existing relations Media -> Object (expect one)", lambda: c.find_relations(media, obj))
        step(f"find object {num} again", lambda: c.find_objects(num))
        # the job's Group (design: Groups): a new Group, related to the Object both ways
        group = step(f"create Group bmu-{num.lower()}", lambda: c.create_group(group_xml(f"bmu-{num.lower()}")))
        if group:
            step("relate Group -> Object", lambda: c.create_relation(relation_xml(group, "Group", obj, "CollectionObject")))
            step("relate Object -> Group", lambda: c.create_relation(relation_xml(obj, "CollectionObject", group, "Group")))
            step("existing relations Group -> Object (expect one)", lambda: c.find_relations(group, obj))
    print(f"Created test records for {num}; they stay in CollectionSpace.")


if __name__ == "__main__":
    main()
