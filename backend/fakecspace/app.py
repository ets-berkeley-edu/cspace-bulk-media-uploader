"""A small simulated CollectionSpace services API for development and tests.

It implements only what the BMU calls: accountperms, object/media search, authority term search,
and creating blobs, media, objects and relations. State is in memory. It is not CollectionSpace:
behavior against the real server must be confirmed on the Lyrasis QA tenant.

Run: uvicorn fakecspace.app:app --port 8180
Users: admin/admin (all permissions), limited/limited (can't create objects), reader/reader (read only).
"""
from __future__ import annotations

import base64
import re
import threading
import uuid
from xml.sax.saxutils import escape

from defusedxml import ElementTree as SafeET
from fastapi import FastAPI, Request, Response, UploadFile

DOMAIN = "pahma.cspace.berkeley.edu"

USERS = {
    "admin": ("admin", "CRUDL"),
    "limited": ("limited", "CRUDL"),
    "reader": ("reader", "RL"),
}
RESOURCES = ["media", "blobs", "relations", "collectionobjects", "personauthorities", "orgauthorities", "vocabularies"]


def _perms_for(user: str) -> dict[str, str]:
    base = USERS[user][1]
    p = {r: base for r in RESOURCES}
    if user == "limited":
        p["collectionobjects"] = "RL"
    return p


PEOPLE = ["Madeleine W. Fang", "Leslie Freund", "Natasha Johnson", "Michael T. Black", "Linda Waterfield", "Zachary Williams"]
ORGS = ["Phoebe A. Hearst Museum of Anthropology", "University of California at Berkeley Regents"]


def _ref(service: str, vocab: str, name: str) -> str:
    short = re.sub(r"[^A-Za-z0-9]", "", name) + "1400000000000"
    return f"urn:cspace:{DOMAIN}:{service}:name({vocab}):item:name({short})'{name}'"


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.objects: dict[str, dict] = {}
        self.media: dict[str, dict] = {}
        self.blobs: dict[str, dict] = {}
        self.relations: dict[str, dict] = {}
        self.fail_next: dict[str, int] = {}  # e.g. {"media": 503} to simulate a server error once
        for num in ["15-1234", "12-5678", "15-1240", "1-2345"]:
            self.objects[str(uuid.uuid4())] = {"objectNumber": num, "deleted": False}
        # two objects share a number, to exercise "matches several objects"
        dup = "9-9999"
        self.objects[str(uuid.uuid4())] = {"objectNumber": dup, "deleted": False}
        self.objects[str(uuid.uuid4())] = {"objectNumber": dup, "deleted": False}
        self.media[str(uuid.uuid4())] = {"identificationNumber": "15-1234", "deleted": False}


store = Store()
app = FastAPI(title="Fake CollectionSpace (development only)")


def _user(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("basic "):
        return None
    try:
        u, _, p = base64.b64decode(h[6:]).decode().partition(":")
    except Exception:
        return None
    return u if u in USERS and USERS[u][0] == p else None


def _deny() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="org.collectionspace.services"'})


def _check(request: Request, resource: str, action: str) -> Response | None:
    u = _user(request)
    if not u:
        return _deny()
    if action not in _perms_for(u)[resource]:
        return Response(status_code=403)
    fail = store.fail_next.pop(resource, None)
    if fail:
        return Response(status_code=fail)
    return None


def _created(request: Request, service: str, csid: str) -> Response:
    base = str(request.base_url).rstrip("/")
    return Response(status_code=201, headers={"Location": f"{base}/cspace-services/{service}/{csid}"})


def _xml(body: str) -> Response:
    return Response(content='<?xml version="1.0" encoding="UTF-8"?>\n' + body, media_type="application/xml")


def _field(xml: bytes, name: str) -> str:
    root = SafeET.fromstring(xml)
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1].split(":")[-1] == name:
            return (el.text or "").strip()
    return ""


_AS = re.compile(r'^\s*\w+:(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"\s*$')


@app.get("/cspace-services/accounts/0/accountperms")
def accountperms(request: Request):
    u = _user(request)
    if not u:
        return _deny()
    perms = "".join(
        f"<permission><resourceName>{r}</resourceName><actionGroup>{a}</actionGroup></permission>"
        for r, a in _perms_for(u).items()
    )
    return _xml(f'<ns2:account_permission xmlns:ns2="http://collectionspace.org/services/authorization/perms">'
                f"<account><userId>{u}</userId></account>{perms}</ns2:account_permission>")


def _search(request: Request, table: dict, field: str, service: str):
    if (d := _check(request, service, "R")):
        return d
    m = _AS.match(request.query_params.get("as", ""))
    value = m.group(2).replace('\\"', '"') if m and m.group(1) == field else None
    items = "".join(
        f"<list-item><csid>{c}</csid><{field}>{escape(rec[field])}</{field}></list-item>"
        for c, rec in table.items() if not rec.get("deleted") and (value is None or rec.get(field) == value)
    )
    return _xml(f'<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb">{items}</ns2:abstract-common-list>')


@app.get("/cspace-services/collectionobjects")
def search_objects(request: Request):
    return _search(request, store.objects, "objectNumber", "collectionobjects")


@app.get("/cspace-services/media")
def search_media(request: Request):
    return _search(request, store.media, "identificationNumber", "media")


@app.get("/cspace-services/{service}/urn:cspace:name({vocab})/items")
def search_terms(service: str, vocab: str, request: Request):
    if service not in ("personauthorities", "orgauthorities"):
        return Response(status_code=404)
    if (d := _check(request, service, "R")):
        return d
    q = request.query_params.get("pt", "").lower()
    names = PEOPLE if service == "personauthorities" else ORGS
    items = "".join(
        f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, n)}</csid><termDisplayName>{escape(n)}</termDisplayName>"
        f"<refName>{escape(_ref(service, vocab, n))}</refName></list-item>"
        for n in names if q in n.lower()
    )
    return _xml(f'<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb">{items}</ns2:abstract-common-list>')


@app.post("/cspace-services/blobs")
async def create_blob(request: Request, file: UploadFile):
    if (d := _check(request, "blobs", "C")):
        return d
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
    csid = str(uuid.uuid4())
    store.blobs[csid] = {"name": file.filename, "size": size, "type": file.content_type}
    return _created(request, "blobs", csid)


@app.post("/cspace-services/media")
async def create_media(request: Request):
    if (d := _check(request, "media", "C")):
        return d
    body = await request.body()
    csid = str(uuid.uuid4())
    store.media[csid] = {"identificationNumber": _field(body, "identificationNumber"),
                         "blobCsid": _field(body, "blobCsid"), "xml": body.decode()}
    return _created(request, "media", csid)


@app.post("/cspace-services/collectionobjects")
async def create_object(request: Request):
    if (d := _check(request, "collectionobjects", "C")):
        return d
    body = await request.body()
    csid = str(uuid.uuid4())
    store.objects[csid] = {"objectNumber": _field(body, "objectNumber"), "deleted": False}
    return _created(request, "collectionobjects", csid)


@app.post("/cspace-services/relations")
async def create_relation(request: Request):
    if (d := _check(request, "relations", "C")):
        return d
    body = await request.body()
    csid = str(uuid.uuid4())
    store.relations[csid] = {k: _field(body, k) for k in ("subjectCsid", "subjectDocumentType", "objectCsid", "objectDocumentType")}
    return _created(request, "relations", csid)


# ---- development helpers (not part of CollectionSpace) ----------------------------------
@app.get("/_fake/state")
def state():
    return {"objects": store.objects, "media": {k: {x: y for x, y in v.items() if x != "xml"} for k, v in store.media.items()},
            "blobs": store.blobs, "relations": store.relations}


@app.post("/_fake/reset")
def reset():
    store.reset()
    return {"ok": True}
