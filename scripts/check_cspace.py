#!/usr/bin/env python3
"""Check the BMU's CollectionSpace calls against a real server (e.g. the Lyrasis QA tenant).

Read-only by default. With --create it runs one real document through the worker's steps
(blob, Media, skeletal Object, two Relations) using a tiny generated image; those records stay.

  export CSPACE_URL=https://pahma.qa.collectionspace.org CSPACE_USER=... CSPACE_PASSWORD=...
  python scripts/check_cspace.py --object 1-2345 --term smith [--create]

Run from the backend directory's environment (pip install -e backend).
"""
import argparse
import io
import os
import sys
import time

from bmu.cspace import CSpaceClient, CSpaceError
from bmu.cspace.payloads import media_xml, object_xml, relation_xml
from bmu.rows import new_row
from bmu.tenant import load_tenant

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--object", default="1-2345", help="an object number that exists on the server")
    ap.add_argument("--term", default="smi", help="text to search the Person and Organization authorities for")
    ap.add_argument("--create", action="store_true", help="create real test records (they are not deleted)")
    ap.add_argument("--tenant", default="pahma")
    a = ap.parse_args()
    url, user, pw = os.environ.get("CSPACE_URL"), os.environ.get("CSPACE_USER"), os.environ.get("CSPACE_PASSWORD")
    if not (url and user and pw):
        sys.exit("Set CSPACE_URL, CSPACE_USER and CSPACE_PASSWORD")
    t = load_tenant(a.tenant)
    c = CSpaceClient(url, user, pw)
    perms = step("accountperms", lambda: c.account_permissions())
    if perms:
        print("     summary:", perms.summary)
        print("     resources:", {k: "".join(sorted(v)) for k, v in sorted(perms.resources.items()) if k in (
            "media", "blobs", "relations", "collectionobjects", "personauthorities", "orgauthorities")})
    step(f"find object {a.object}", lambda: c.find_objects(a.object))
    step(f"find media id {a.object}", lambda: c.find_media(a.object))
    for kind, cfg in t.authorities.items():
        step(f"search {kind} '{a.term}'", lambda: [x["displayName"] for x in c.search_terms(cfg["service"], cfg["vocabulary"], a.term)][:5])
    if not a.create:
        print("Read-only checks done. Add --create to test creating records.")
        return
    num = f"BMU-TEST-{int(time.time())}"
    row = new_row(t, f"{num}.png", len(PNG), "image/png")
    row["restricted"] = True
    blob = step("create blob (POST /blobs)", lambda: c.create_blob(row["file"], io.BytesIO(PNG), "image/png"))
    media = blob and step("create Media", lambda: c.create_media(media_xml(t, row, blob)))
    obj = media and step(f"create Object {num}", lambda: c.create_object(object_xml(num)))
    if obj:
        step("relate Media -> Object", lambda: c.create_relation(relation_xml(media, "Media", obj, "CollectionObject")))
        step("relate Object -> Media", lambda: c.create_relation(relation_xml(obj, "CollectionObject", media, "Media")))
        step(f"find object {num} again", lambda: c.find_objects(num))
    print(f"Created test records for {num}; they stay in CollectionSpace.")


if __name__ == "__main__":
    main()
