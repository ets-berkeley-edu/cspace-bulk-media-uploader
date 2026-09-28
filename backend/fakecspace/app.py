"""A small simulated CollectionSpace services API for development and tests.

It implements only what the BMU calls: accountperms, object/media/relation search, authority term
search, creating Media, Objects and Relations, and attaching a file with PUT media/{csid}/blob. State is in memory. It is not CollectionSpace:
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
RESOURCES = ["media", "relations", "collectionobjects", "personauthorities", "orgauthorities", "vocabularies"]


def _perms_for(user: str) -> dict[str, str]:
    base = USERS[user][1]
    p = {r: base for r in RESOURCES}
    if user == "limited":
        p["collectionobjects"] = "RL"
    p.update(store.perm_overrides.get(user, {}))
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
        self.fail_next: dict[str, int] = {}  # e.g. {"media": 503} or {"media_blob": 500}: fail the next call once
        self.perm_overrides: dict[str, dict[str, str]] = {}  # e.g. {"admin": {"collectionobjects": "RL"}}: roles changed
        self.searches: list[tuple[str, str | None]] = []  # (service, searched value), to test lookup caching
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
    store.searches.append((service, value))
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


# A few terms of the languages vocabulary (the real one is much longer).
LANGUAGES = {"eng": "English", "spa": "Spanish", "fre": "French", "ger": "German", "chi": "Chinese", "jpn": "Japanese",
             "haw": "Hawaiian", "nav": "Navajo"}


def _language_ref(code: str) -> str:
    return f"urn:cspace:{DOMAIN}:vocabularies:name(languages):item:name({code})'{LANGUAGES[code]}'"


@app.get("/cspace-services/{service}/urn:cspace:name({vocab})/items")
def search_terms(service: str, vocab: str, request: Request):
    if service == "vocabularies" and vocab == "languages":
        if (d := _check(request, "vocabularies", "R")):
            return d
        items = "".join(f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, c)}</csid><shortIdentifier>{c}</shortIdentifier>"
                        f"<displayName>{escape(n)}</displayName><refName>{escape(_language_ref(c))}</refName></list-item>"
                        for c, n in LANGUAGES.items())
        return _xml(f'<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb">{items}</ns2:abstract-common-list>')
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


@app.post("/cspace-services/media")
async def create_media(request: Request):
    if (d := _check(request, "media", "C")):
        return d
    body = await request.body()
    csid = str(uuid.uuid4())
    if _field(body, "blobCsid"):
        return Response(status_code=400)  # the BMU must not send blobCsid; the file is attached with PUT .../blob
    store.media[csid] = {"identificationNumber": _field(body, "identificationNumber"), "blobCsid": "", "xml": body.decode()}
    return _created(request, "media", csid)


@app.put("/cspace-services/media/{csid}/blob")
async def media_blob(csid: str, request: Request, file: UploadFile):
    """Attach a file to a Media record: creates the Blob record and sets the Media record's blobCsid."""
    if (d := _check(request, "media", "U")):
        return d
    if (fail := store.fail_next.pop("media_blob", None)):
        return Response(status_code=fail)
    if csid not in store.media:
        return Response(status_code=404)
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
    blob = str(uuid.uuid4())
    store.blobs[blob] = {"name": file.filename, "size": size, "type": file.content_type, "media": csid}
    store.media[csid]["blobCsid"] = blob
    return _created(request, "blobs", blob)


@app.get("/cspace-services/media/{csid}")
def get_media(csid: str, request: Request):
    if (d := _check(request, "media", "R")):
        return d
    m = store.media.get(csid)
    if not m:
        return Response(status_code=404)
    if m.get("xml"):  # the record as saved, with the blobCsid CollectionSpace set, like the real server
        body = re.sub(r"<\?xml[^>]*\?>", "", m["xml"])
        body = re.sub(r"(</[\w:]*media_common>)", f"<blobCsid>{m.get('blobCsid', '')}</blobCsid>\\1", body, count=1)
        return _xml(body)
    return _xml(f'<document name="media"><ns2:media_common xmlns:ns2="http://collectionspace.org/services/media">'
                f"<identificationNumber>{escape(m.get('identificationNumber', ''))}</identificationNumber>"
                f"<blobCsid>{m.get('blobCsid', '')}</blobCsid></ns2:media_common></document>")


@app.get("/cspace-services/relations")
def find_relations(request: Request):
    if (d := _check(request, "relations", "R")):
        return d
    q = request.query_params
    # Real CollectionSpace names relation results <relation-list-item>, unlike other lists' <list-item>.
    items = "".join(f"<relation-list-item><csid>{c}</csid></relation-list-item>" for c, r in store.relations.items()
                    if r["subjectCsid"] == q.get("sbj") and r["objectCsid"] == q.get("obj"))
    return _xml(f'<ns2:relations-common-list xmlns:ns2="http://collectionspace.org/services/relation">{items}</ns2:relations-common-list>')


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
    # "relations_lost": the relation is saved but the response is lost (e.g. a gateway timeout)
    if (fail := store.fail_next.pop("relations_lost", None)):
        return Response(status_code=fail)
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
