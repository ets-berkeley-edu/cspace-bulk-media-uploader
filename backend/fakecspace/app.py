"""A small simulated CollectionSpace services API for development and tests.

It implements only what the BMU calls: accountperms, object/media/relation search, authority term
search, creating Media, Objects and Relations, and attaching a file with PUT media/{csid}/blob. State is in memory. It is not CollectionSpace:
behavior against the real server must be confirmed on the Lyrasis QA tenant.

Run: uvicorn fakecspace.app:app --port 8180
Users: admin/admin (all permissions; a BMU scheduler), limited/limited (can't create objects or groups), reader/reader
(read only). Roles (accounts/0/accountroles): admin has ROLE_15_TENANT_ADMINISTRATOR and ROLE_15_BMU_SCHEDULER, the
others ROLE_15_TENANT_READER.
Development hooks: /_fake/state, /_fake/reset, /_fake/slow, /_fake/fail (failures on demand).
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
RESOURCES = ["media", "relations", "collectionobjects", "groups", "personauthorities", "orgauthorities", "vocabularies",
             "structureddates"]


def _perms_for(user: str) -> dict[str, str]:
    base = USERS[user][1]
    p = {r: base for r in RESOURCES}
    if user == "limited":
        p["collectionobjects"] = "RL"
        p["groups"] = "RL"
    p.update(store.perm_overrides.get(user, {}))
    return p


TENANT_ID = "15"  # PAHMA's tenant id
ROLES = {
    "admin": ["ROLE_15_TENANT_ADMINISTRATOR", "ROLE_15_BMU_SCHEDULER"],
    "limited": ["ROLE_15_TENANT_READER"],
    "reader": ["ROLE_15_TENANT_READER"],
}


def _roles_for(user: str) -> list[str]:
    return list(store.role_overrides.get(user, ROLES[user]))


PEOPLE = ["Madeleine W. Fang", "Leslie Freund", "Natasha Johnson", "Michael T. Black", "Linda Waterfield", "Zachary Williams"]
ORGS = ["Phoebe A. Hearst Museum of Anthropology", "University of California at Berkeley Regents"]


def _ref(service: str, vocab: str, name: str) -> str:
    short = re.sub(r"[^A-Za-z0-9]", "", name) + "1400000000000"
    return f"urn:cspace:{DOMAIN}:{service}:name({vocab}):item:name({short})'{name}'"


# Sample Object records. Most are ordinary; 9-9999 is on two objects, to exercise "matches several objects".
SAMPLE_OBJECTS = [
    ("15-1234", "Ordinary; a Media record with ID 15-1234 already exists"),
    ("12-5678", "Ordinary"),
    ("15-1240", "Ordinary"),
    ("1-2345", "Ordinary"),
    ("9-9999", "Shares its number with another object"),
    ("9-9999", "Shares its number with another object"),
    ("3-1001", "Ordinary"),
    ("3-1002", "Ordinary"),
    ("3-1003.1", "Ordinary; a part number with a dot (filename 3-1003.1_a.jpg)"),
    ("16-4711", "Ordinary"),
]

# Objects PAHMA treats as sensitive, or nearly so (design: Protected files, Per-tenant signals). GET
# collectionobjects/{csid} returns these fields with the element names in bmu/tenants/pahma.yaml's sensitivity
# rules; both are the prototype's reading of PAHMA's profile, to be confirmed on the QA tenant.
SENSITIVE_OBJECTS = [
    ("12-2001", "Sensitive: culturally sensitive, Human Remains department (the public portal hides its images)",
     {"objectStatus": ["culturally sensitive"], "department": "Human Remains"}),
    ("12-2002", "Sensitive: NAGPRA status and a display restriction at the restriction level",
     {"nagpraStatus": "under NAGPRA review", "accessRestrictions": [{"type": "display/visual", "level": "restriction"}]}),
    ("12-2003", "Soft signal only: a display restriction at the preference level (a warning, not protected)",
     {"accessRestrictions": [{"type": "display/visual", "level": "preference"}]}),
]


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.objects: dict[str, dict] = {}
        self.media: dict[str, dict] = {}
        self.blobs: dict[str, dict] = {}
        self.relations: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}
        self.content: dict[str, bytes] = {}  # blob CSID -> file bytes (small files only)
        self.fail_next: dict[str, int] = {}  # e.g. {"media": 503} or {"media_blob": 500}: fail the next call once
        self.perm_overrides: dict[str, dict[str, str]] = {}  # e.g. {"admin": {"collectionobjects": "RL"}}: roles changed
        self.role_overrides: dict[str, list[str]] = {}  # e.g. {"admin": ["ROLE_15_TENANT_READER"]}: the user's role names
        self.searches: list[tuple[str, str | None]] = []  # (service, searched value), to test lookup caching
        self.delay = 0.0  # seconds added to every create or upload, to watch the queue in a browser (/_fake/slow)
        self.rules: list[dict] = []  # failures on demand (/_fake/fail)
        for num, note in SAMPLE_OBJECTS:
            self.objects[str(uuid.uuid4())] = {"objectNumber": num, "deleted": False, "note": note}
        for num, note, sens in SENSITIVE_OBJECTS:
            self.objects[str(uuid.uuid4())] = {"objectNumber": num, "deleted": False, "note": note, "sensitivity": sens}
        # soft-deleted in CollectionSpace: searches (wf_deleted=false) don't find it
        self.objects[str(uuid.uuid4())] = {"objectNumber": "3-1004", "deleted": True, "note": "Deleted: searches don't find it"}
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


# ---- failures on demand (development only; see /_fake/fail) ----------------------------------------
STEPS = {"media", "upload", "objectSearch", "objectCreate", "relation", "mediaSearch", "group"}


def _rule(request: Request, step: str, names: list[str]) -> dict | None:
    """The /_fake/fail rule that applies to this request, if any (counted as used). A rule applies to one step, to requests
    whose names (identification number, filename, object number) contain its match text, and by default
    only to the BMU worker's requests (User-Agent bmu-worker), so the editor's checks aren't affected."""
    agent = request.headers.get("user-agent", "")
    for rule in list(store.rules):
        if rule["step"] != step or (rule["client"] == "worker" and not agent.startswith("bmu-worker")):
            continue
        if rule["match"] and not any(rule["match"].lower() in (n or "").lower() for n in names):
            continue
        if rule["count"]:
            rule["left"] -= 1
            if rule["left"] <= 0:
                store.rules.remove(rule)
        rule["hits"] = rule.get("hits", 0) + 1
        return rule
    return None


def _fail(request: Request, step: str, names: list[str]) -> Response | None:
    """The error response a matching /_fake/fail rule asks for, if any."""
    rule = _rule(request, step, names)
    return Response(status_code=rule["status"]) if rule else None


def _media_names(csid: str) -> list[str]:
    m = store.media.get(csid) or {}
    blob = next((b for b in store.blobs.values() if b.get("media") == csid), {})
    return [m.get("identificationNumber", ""), m.get("title", ""), blob.get("name", "")]


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


@app.get("/cspace-services/accounts/0/accountroles")
def accountroles(request: Request):
    """The signed-in account's roles, shaped like CollectionSpace's (design: Job scheduling). fail_next
    {"accountroles": 500} makes the next call fail."""
    u = _user(request)
    if not u:
        return _deny()
    if (fail := store.fail_next.pop("accountroles", None)):
        return Response(status_code=fail)
    roles = "".join(f"<role><roleRelationshipId>{uuid.uuid5(uuid.NAMESPACE_URL, u + r)}</roleRelationshipId>"
                    f"<roleId>{uuid.uuid5(uuid.NAMESPACE_URL, r)}</roleId><roleName>{escape(r)}</roleName></role>"
                    for r in _roles_for(u))
    return _xml(f'<ns2:account_role xmlns:ns2="http://collectionspace.org/services/authorization"><account>'
                f"<accountId>{uuid.uuid5(uuid.NAMESPACE_URL, 'account-' + u)}</accountId><screenName>{u}</screenName>"
                f"<userId>{u}</userId><tenantId>{TENANT_ID}</tenantId></account>{roles}</ns2:account_role>")


def _search(request: Request, table: dict, field: str, service: str):
    if (d := _check(request, service, "R")):
        return d
    m = _AS.match(request.query_params.get("as", ""))
    value = m.group(2).replace('\\"', '"') if m and m.group(1) == field else None
    step = "objectSearch" if service == "collectionobjects" else "mediaSearch"
    if (rule := _rule(request, step, [value or ""])) is not None:
        effect = rule.get("effect")
        if effect == "none":
            return _xml('<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb"></ns2:abstract-common-list>')
        if effect == "many":
            items = "".join(f"<list-item><csid>{uuid.uuid4()}</csid><{field}>{escape(value or '')}</{field}></list-item>" for _ in range(2))
            return _xml(f'<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb">{items}</ns2:abstract-common-list>')
        return Response(status_code=rule["status"])
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


def _page(items: list, request: Request, default: int = 40) -> list:
    """One page of a list, as CollectionSpace pages it: pgSz=0 means every item."""
    size = int(request.query_params.get("pgSz") or default)
    return items if size == 0 else items[:size]


@app.get("/cspace-services/{service}/urn:cspace:name({vocab})/items")
def search_terms(service: str, vocab: str, request: Request):
    if service == "vocabularies" and vocab == "languages":
        if (d := _check(request, "vocabularies", "R")):
            return d
        items = "".join(f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, c)}</csid><shortIdentifier>{c}</shortIdentifier>"
                        f"<displayName>{escape(n)}</displayName><refName>{escape(_language_ref(c))}</refName></list-item>"
                        for c, n in _page(list(LANGUAGES.items()), request))
        return _xml(f'<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb">{items}</ns2:abstract-common-list>')
    if service not in ("personauthorities", "orgauthorities"):
        return Response(status_code=404)
    if (d := _check(request, service, "R")):
        return d
    q = request.query_params.get("pt", "").lower()
    names = PEOPLE if service == "personauthorities" else ORGS
    matches = [n for n in names if q in n.lower()]
    page = _page(matches, request)
    items = "".join(
        f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, n)}</csid><termDisplayName>{escape(n)}</termDisplayName>"
        f"<refName>{escape(_ref(service, vocab, n))}</refName></list-item>"
        for n in page
    )
    return _xml(f'<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb"><totalItems>{len(matches)}</totalItems>'
                f'{items}</ns2:abstract-common-list>')


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]


def _fake_parse_date(text: str) -> dict | None:
    """A small stand-in for CollectionSpace's date parser (it understands far more). Returns the group or None."""
    import calendar
    t, cert = text.strip(), ""
    if m := re.match(r"^(?:circa|ca\.?|c\.)\s*(.+)$", t, re.I):
        cert, t = "approximate", m.group(1)
    def day(y, mo, d):
        return (y, mo, d) if 1 <= mo <= 12 and 1 <= d <= calendar.monthrange(y, mo)[1] else None
    e = l = None
    if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t):
        e = l = day(*map(int, m.groups()))
    elif m := re.match(r"^(\d{4})-(\d{2})$", t):
        y, mo = map(int, m.groups())
        if 1 <= mo <= 12:
            e, l = (y, mo, 1), (y, mo, calendar.monthrange(y, mo)[1])
    elif m := re.match(r"^(\d{4})$", t):
        y = int(m.group(1)); e, l = (y, 1, 1), (y, 12, 31)
    elif (m := re.match(r"^(\d{3}0)s$", t)):
        y = int(m.group(1)); e, l = (y, 1, 1), (y + 9, 12, 31)
    elif (m := re.match(r"^(\d{4})\s*(?:-|–|to)\s*(\d{4})$", t, re.I)) and int(m.group(2)) >= int(m.group(1)):
        e, l = (int(m.group(1)), 1, 1), (int(m.group(2)), 12, 31)
    elif (m := re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", t)) and m.group(1).lower() in _MONTHS:
        e = l = day(int(m.group(3)), _MONTHS.index(m.group(1).lower()) + 1, int(m.group(2)))
    if not e or not l:
        return None
    era = f"urn:cspace:{DOMAIN}:vocabularies:name(dateera):item:name(ce)'CE'"
    g = {"dateDisplayDate": text, "dateEarliestSingleYear": e[0], "dateEarliestSingleMonth": e[1], "dateEarliestSingleDay": e[2],
         "dateEarliestSingleEra": era, "dateLatestYear": l[0], "dateLatestMonth": l[1], "dateLatestDay": l[2], "dateLatestEra": era,
         "dateEarliestScalarValue": f"{e[0]:04d}-{e[1]:02d}-{e[2]:02d}T00:00:00.000Z",
         "dateLatestScalarValue": f"{l[0]:04d}-{l[1]:02d}-{l[2]:02d}T00:00:00.000Z", "scalarValuesComputed": "true"}
    if cert:
        g["dateEarliestSingleCertainty"] = g["dateLatestCertainty"] = cert
    return g


@app.get("/cspace-services/structureddates")
def structured_dates(request: Request):
    if not _user(request):
        return _deny()
    g = _fake_parse_date(request.query_params.get("displayDate", ""))
    if g is None:
        return Response(status_code=400)
    fields = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in g.items())
    return _xml(f'<ns2:structureddate_common xmlns:ns2="http://collectionspace.org/services/structureddate">{fields}</ns2:structureddate_common>')


@app.post("/cspace-services/media")
async def create_media(request: Request):
    if (d := _check(request, "media", "C")):
        return d
    body = await request.body()
    csid = str(uuid.uuid4())
    if _field(body, "blobCsid"):
        return Response(status_code=400)  # the BMU must not send blobCsid; the file is attached with PUT .../blob
    if (f := _fail(request, "media", [_field(body, "identificationNumber"), _field(body, "title")])) is not None:
        return f
    store.media[csid] = {"identificationNumber": _field(body, "identificationNumber"), "title": _field(body, "title"),
                         "blobCsid": "", "xml": body.decode()}
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
    if (f := _fail(request, "upload", [file.filename or "", *_media_names(csid)])) is not None:
        return f
    size, head = 0, b""
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size <= KEEP_BYTES:
            head += chunk
    blob = str(uuid.uuid4())
    store.blobs[blob] = {"name": file.filename, "size": size, "type": file.content_type, "media": csid}
    if size <= KEEP_BYTES:
        store.content[blob] = head  # small files are kept, to serve as their own derivatives
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


KEEP_BYTES = 5 * 1024 * 1024


@app.get("/cspace-services/blobs/{csid}/derivatives/{name}/content")
def derivative(csid: str, name: str, request: Request):
    """A Blob's derivative image. Real CollectionSpace makes resized JPEGs; the simulator returns the file itself."""
    if (d := _check(request, "media", "R")):
        return d
    blob = store.blobs.get(csid)
    if not blob or csid not in store.content or name not in ("Thumbnail", "Medium", "OriginalJpeg"):
        return Response(status_code=404)
    return Response(content=store.content[csid], media_type=blob.get("type") or "application/octet-stream")


@app.get("/cspace-services/relations")
def find_relations(request: Request):
    if (d := _check(request, "relations", "R")):
        return d
    q = request.query_params
    # Real CollectionSpace names relation results <relation-list-item>, unlike other lists' <list-item>.
    items = "".join(f"<relation-list-item><csid>{c}</csid></relation-list-item>" for c, r in store.relations.items()
                    if r["subjectCsid"] == q.get("sbj") and r["objectCsid"] == q.get("obj"))
    return _xml(f'<ns2:relations-common-list xmlns:ns2="http://collectionspace.org/services/relation">{items}</ns2:relations-common-list>')


@app.get("/cspace-services/collectionobjects/{csid}")
def get_object(csid: str, request: Request):
    """An Object record: its number, and for the sample sensitive objects the fields PAHMA's rules read."""
    if (d := _check(request, "collectionobjects", "R")):
        return d
    o = store.objects.get(csid)
    if not o or o.get("deleted"):
        return Response(status_code=404)
    sens = o.get("sensitivity") or {}
    dept = sens.get("department")
    common = (f"<objectNumber>{escape(o['objectNumber'])}</objectNumber>"
              + (f"<responsibleDepartments><responsibleDepartment>{escape(dept)}</responsibleDepartment></responsibleDepartments>" if dept else ""))
    statuses = "".join(f"<pahmaObjectStatus>{escape(x)}</pahmaObjectStatus>" for x in sens.get("objectStatus", []))
    restrictions = "".join(f"<accessRestrictionGroup><accessRestrictionType>{escape(a['type'])}</accessRestrictionType>"
                           f"<accessRestrictionLevel>{escape(a['level'])}</accessRestrictionLevel></accessRestrictionGroup>"
                           for a in sens.get("accessRestrictions", []))
    pahma = ((f"<pahmaObjectStatusList>{statuses}</pahmaObjectStatusList>" if statuses else "")
             + (f"<nagpraStatus>{escape(sens['nagpraStatus'])}</nagpraStatus>" if sens.get("nagpraStatus") else "")
             + (f"<accessRestrictionGroupList>{restrictions}</accessRestrictionGroupList>" if restrictions else ""))
    return _xml('<document name="collectionobjects">'
                f'<ns2:collectionobjects_common xmlns:ns2="http://collectionspace.org/services/collectionobject">{common}</ns2:collectionobjects_common>'
                f'<ns2:collectionobjects_pahma xmlns:ns2="http://collectionspace.org/services/collectionobject/local/pahma">{pahma}</ns2:collectionobjects_pahma>'
                "</document>")


@app.post("/cspace-services/collectionobjects")
async def create_object(request: Request):
    if (d := _check(request, "collectionobjects", "C")):
        return d
    body = await request.body()
    csid = str(uuid.uuid4())
    if (f := _fail(request, "objectCreate", [_field(body, "objectNumber")])) is not None:
        return f
    store.objects[csid] = {"objectNumber": _field(body, "objectNumber"), "deleted": False}
    return _created(request, "collectionobjects", csid)


@app.post("/cspace-services/groups")
async def create_group(request: Request):
    if (d := _check(request, "groups", "C")):
        return d
    body = await request.body()
    title = _field(body, "title")
    if (f := _fail(request, "group", [title])) is not None:
        return f
    if not title:
        return Response(status_code=400)
    csid = str(uuid.uuid4())
    store.groups[csid] = {"title": title}
    return _created(request, "groups", csid)


@app.post("/cspace-services/relations")
async def create_relation(request: Request):
    if (d := _check(request, "relations", "C")):
        return d
    body = await request.body()
    csid = str(uuid.uuid4())
    rel = {k: _field(body, k) for k in ("subjectCsid", "subjectDocumentType", "objectCsid", "objectDocumentType")}
    if (f := _fail(request, "relation", _media_names(rel["subjectCsid"]) + _media_names(rel["objectCsid"]))) is not None:
        return f
    store.relations[csid] = rel
    # "relations_lost": the relation is saved but the response is lost (e.g. a gateway timeout)
    if (fail := store.fail_next.pop("relations_lost", None)):
        return Response(status_code=fail)
    return _created(request, "relations", csid)


# ---- development helpers (not part of CollectionSpace) ----------------------------------
@app.middleware("http")
async def slow_down(request: Request, call_next):
    """With /_fake/slow, creates and uploads take a while, so a job runs long enough to watch or cancel."""
    if store.delay and request.method in ("POST", "PUT") and request.url.path.startswith("/cspace-services/"):
        import asyncio
        await asyncio.sleep(store.delay)
    return await call_next(request)


@app.post("/_fake/slow")
def slow(seconds: float = 2.0):
    """Development only: add this many seconds to every create and upload (0 to turn it off)."""
    store.delay = max(0.0, min(seconds, 30.0))
    return {"delay": store.delay}


@app.post("/_fake/fail")
def add_failure(step: str, match: str = "", status: int = 500, effect: str = "", count: int = 1, client: str = "worker"):
    """Development only: make CollectionSpace fail on purpose, to see how the BMU reports it.

    step:   media | upload | objectSearch | objectCreate | relation | mediaSearch | group
    match:  only requests whose identification number, filename, object number or group title contains this text ("" = any)
    status: the HTTP status to return, e.g. 400 (rejected), 401 (sign-in), 403 (permission), 409 (inactive
            account), 413 (file too large), 415 (file type), 500 (server error)
    effect: for objectSearch, "none" (no object found) or "many" (several objects) instead of a status
    count:  how many requests fail (0 = until cleared with DELETE /_fake/fail)
    client: "worker" (default: only job runs, so the editor's checks are unaffected) or "any"
    """
    if step not in STEPS:
        return Response(status_code=400, content=f"step must be one of {', '.join(sorted(STEPS))}")
    if effect and (step not in ("objectSearch", "mediaSearch") or effect not in ("none", "many")):
        return Response(status_code=400, content="effect is none or many, for objectSearch and mediaSearch")
    rule = {"step": step, "match": match, "status": status, "effect": effect, "count": max(0, count),
            "left": max(0, count), "client": "any" if client == "any" else "worker"}
    store.rules.append(rule)
    return {"rules": store.rules}


@app.get("/cspace-services/{service}")
def authority_vocabularies(service: str, request: Request):
    """The vocabularies of an authority. Like PAHMA's server: local Persons and Organizations only (no "shared")."""
    if service not in ("personauthorities", "orgauthorities"):
        return Response(status_code=404)
    if (d := _check(request, service, "R")):
        return d
    short, name = ("person", "Local Persons") if service == "personauthorities" else ("organization", "Local Organizations")
    item = (f"<list-item><csid>{uuid.uuid5(uuid.NAMESPACE_URL, service)}</csid><shortIdentifier>{short}</shortIdentifier>"
            f"<displayName>{name}</displayName></list-item>")
    return _xml(f'<ns2:abstract-common-list xmlns:ns2="http://collectionspace.org/services/jaxb">{item}</ns2:abstract-common-list>')


@app.get("/_fake/fail")
def list_failures():
    return {"rules": store.rules}


@app.delete("/_fake/fail")
def clear_failures():
    store.rules.clear()
    return {"rules": []}


@app.get("/_fake/state")
def state():
    return {"objects": store.objects, "media": {k: {x: y for x, y in v.items() if x != "xml"} for k, v in store.media.items()},
            "blobs": store.blobs, "relations": store.relations, "groups": store.groups}


@app.get("/_fake/objects")
def objects():
    """Development only: the Object records, one line each (object number, what it's for, sensitivity fields)."""
    return sorted(({"objectNumber": o["objectNumber"], "note": o.get("note", ""), "deleted": o.get("deleted", False),
                    **({"sensitivity": o["sensitivity"]} if o.get("sensitivity") else {})} for o in store.objects.values()),
                  key=lambda o: o["objectNumber"])


@app.post("/_fake/reset")
def reset():
    store.reset()
    return {"ok": True}
