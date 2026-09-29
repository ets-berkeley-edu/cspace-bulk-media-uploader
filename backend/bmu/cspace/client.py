"""Minimal CollectionSpace REST client used by the web app (checks, autocomplete) and the worker.

Every call uses the signed-in user's own credentials (HTTP Basic), never a service account.
Calls were checked against the Lyrasis PAHMA QA tenant with scripts/check_cspace.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO, Iterable
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree as SafeET

SERVICES = "/cspace-services/"


class CSpaceError(Exception):
    """A failed CollectionSpace request, with a failure code from the BMU's catalog."""

    def __init__(self, code: str, detail: str, status: int | None = None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.status = status


def _code_for_status(status: int) -> str:
    if status == 401:
        return "auth"
    if status == 403:
        return "forbidden"
    if status == 409:
        return "account_inactive"
    if status >= 500:
        return "server"
    return "unknown"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: Element, name: str) -> Iterable[Element]:
    return (c for c in el.iter() if _local(c.tag) == name)


def _items(root: Element) -> Iterable[Element]:
    """List results: <list-item>, or <relation-list-item> for relations (confirmed on QA)."""
    return (c for c in root.iter() if _local(c.tag).endswith("list-item"))


def _text(el: Element, name: str) -> str:
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


# CollectionSpace action letters (C)reate (R)ead (U)pdate (D)elete (L)ist
_ACTION_LETTER = {"CREATE": "C", "READ": "R", "UPDATE": "U", "DELETE": "D", "SEARCH": "L"}


@dataclass
class Permissions:
    """Actions per resource from accounts/0/accountperms, e.g. {"media": {"C", "R"}}."""

    resources: dict[str, set[str]] = field(default_factory=dict)

    def can(self, resource: str, action: str) -> bool:
        return action in self.resources.get(resource, set())

    @property
    def summary(self) -> dict[str, bool]:
        return {
            # The file goes through media/{csid}/blob, so only media permissions apply (no blobs permission).
            "media": self.can("media", "C"),
            "relations": self.can("relations", "C"),
            "objects": self.can("collectionobjects", "C"),
            "readObjects": self.can("collectionobjects", "R"),
            "authorities": self.can("personauthorities", "R") and self.can("orgauthorities", "R"),
            "groups": self.can("groups", "C"),
        }

    @classmethod
    def from_xml(cls, xml: bytes) -> "Permissions":
        # Confirmed on QA: <permission><resourceName> with an <actionGroup> such as "CRUDL";
        # <action><name> elements are also accepted.
        root = SafeET.fromstring(xml)
        res: dict[str, set[str]] = {}
        for perm in _children(root, "permission"):
            name = _text(perm, "resourceName")
            if not name:
                continue
            acts = res.setdefault(name, set())
            group = _text(perm, "actionGroup")
            acts.update(ch for ch in group.upper() if ch in "CRUDL")
            for a in _children(perm, "action"):
                letter = _ACTION_LETTER.get(_text(a, "name").upper())
                if letter:
                    acts.add(letter)
        return cls(res)


class CSpaceClient:
    def __init__(self, base_url: str, username: str, password: str,
                 http: httpx.Client | None = None, timeout: float = 300.0, agent: str = "bmu-web"):
        """agent: the User-Agent sent with every request ("bmu-web" or "bmu-worker"), so CollectionSpace's
        logs show which part of the BMU made a call."""
        self.base = base_url.rstrip("/") + SERVICES
        self._http = http or httpx.Client(timeout=timeout, follow_redirects=False)
        self._auth = httpx.BasicAuth(username, password)
        self._headers = {"User-Agent": agent}

    def close(self) -> None:
        self._http.close()

    # -- low level ----------------------------------------------------------------------
    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            headers = {**self._headers, **kw.pop("headers", {})}
            r = self._http.request(method, self.base + path, auth=self._auth, headers=headers, **kw)
        except httpx.TransportError as e:  # network problem, DNS, timeout
            raise CSpaceError("unavailable", f"{method} {path}: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise CSpaceError(_code_for_status(r.status_code), f"{method} {path} returned {r.status_code}", r.status_code)
        return r

    def _post_xml(self, path: str, xml: bytes) -> str:
        r = self._request("POST", path, content=xml, headers={"Content-Type": "application/xml"})
        return _csid_from(r)

    # -- account --------------------------------------------------------------------------
    def account_permissions(self) -> Permissions:
        """Verifies the credentials (401 if wrong) and returns the account's permissions."""
        r = self._request("GET", "accounts/0/accountperms")
        return Permissions.from_xml(r.content)

    # -- lookups --------------------------------------------------------------------------
    def find_objects(self, object_number: str) -> list[str]:
        """CSIDs of non-deleted Object records whose objectNumber equals object_number exactly."""
        # Confirmed on QA: the advanced search matches objectNumber exactly.
        q = f'collectionobjects_common:objectNumber = "{_quote(object_number)}"'
        r = self._request("GET", "collectionobjects", params={"as": q, "wf_deleted": "false", "pgSz": "10"})
        return [csid for csid, num in _list_items(r.content, "objectNumber") if num == object_number]

    def get_object(self, csid: str) -> bytes:
        """An Object record's XML, all parts (for its sensitivity fields)."""
        return self._request("GET", f"collectionobjects/{csid}").content

    def find_media(self, identification_number: str) -> list[str]:
        q = f'media_common:identificationNumber = "{_quote(identification_number)}"'
        r = self._request("GET", "media", params={"as": q, "wf_deleted": "false", "pgSz": "10"})
        return [csid for csid, num in _list_items(r.content, "identificationNumber") if num == identification_number]

    def search_terms(self, service: str, vocabulary: str, text: str, limit: int = 20) -> list[dict[str, str]]:
        """Authority terms whose display name matches `text` (partial term search)."""
        path = f"{service}/urn:cspace:name({vocabulary})/items"
        r = self._request("GET", path, params={"pt": text, "wf_deleted": "false", "pgSz": str(limit)})
        out = []
        root = SafeET.fromstring(r.content)
        for item in _items(root):
            ref = _text(item, "refName")
            name = _text(item, "termDisplayName") or _text(item, "displayName") or display_name(ref)
            if ref:
                out.append({"refName": ref, "displayName": name})
        return out

    def parse_date(self, text: str) -> dict[str, str] | None:
        """Parse a display date with CollectionSpace's own parser (GET structureddates?displayDate=), as the
        CollectionSpace UI does. Returns the structured date group's fields (earliest and latest parts,
        era, certainty, qualifiers and the scalar values used for searching), or None if CollectionSpace
        can't interpret the text. VERIFY on QA: the response's element names (check_cspace.py prints them)."""
        try:
            r = self._request("GET", "structureddates", params={"displayDate": text})
        except CSpaceError as e:
            if e.status == 400:
                return None
            raise
        root = SafeET.fromstring(r.content)
        fields = {}
        for el in root.iter():
            name = _local(el.tag)
            if (name.startswith("date") or name == "scalarValuesComputed") and len(el) == 0 and (el.text or "").strip():
                fields[name] = el.text.strip()
        return fields if any(k.startswith("dateEarliest") for k in fields) else None

    def vocabulary_items(self, vocabulary: str, limit: int = 1000) -> list[dict[str, str]]:
        """Every term of a vocabulary (e.g. languages), as refName and display name."""
        r = self._request("GET", f"vocabularies/urn:cspace:name({vocabulary})/items",
                          params={"wf_deleted": "false", "pgSz": str(limit)})
        out = []
        for item in _items(SafeET.fromstring(r.content)):
            ref = _text(item, "refName")
            if ref:
                out.append({"refName": ref, "displayName": _text(item, "displayName") or display_name(ref)})
        return out

    # -- creates (the BMU never updates or deletes) ---------------------------------------
    def upload_file(self, media_csid: str, filename: str, stream: IO[bytes], content_type: str) -> str:
        """Attach the file to an existing Media record: multipart PUT media/{csid}/blob.

        CollectionSpace creates the Blob record, stores the file and sets the Media record's blobCsid
        in one call. The body is streamed. Returns the new Blob CSID when the response names it, else "".
        Confirmed on QA: field "file"; the Media record's blobCsid is set to the new Blob.
        """
        files = {"file": (filename, stream, content_type or "application/octet-stream")}
        r = self._request("PUT", f"media/{media_csid}/blob", files=files)
        loc = r.headers.get("location", "")
        return loc.rstrip("/").rsplit("/", 1)[-1] if loc else ""

    def create_media(self, xml: bytes) -> str:
        return self._post_xml("media", xml)

    def create_object(self, xml: bytes) -> str:
        return self._post_xml("collectionobjects", xml)

    def create_group(self, xml: bytes) -> str:
        return self._post_xml("groups", xml)

    def create_relation(self, xml: bytes) -> str:
        return self._post_xml("relations", xml)

    def media_blob_csid(self, media_csid: str) -> str:
        """The blobCsid CollectionSpace set on a Media record (after PUT media/{csid}/blob)."""
        r = self._request("GET", f"media/{media_csid}")
        return _text(SafeET.fromstring(r.content), "blobCsid")

    def find_relations(self, subject_csid: str, object_csid: str, predicate: str = "affects") -> list[str]:
        """CSIDs of existing relations from subject to object, so a rerun never creates a duplicate.
        Results are <relation-list-item> elements, not <list-item> (seen on QA)."""
        r = self._request("GET", "relations", params={"sbj": subject_csid, "obj": object_csid, "prd": predicate, "wf_deleted": "false"})
        return [csid for csid, _ in _list_items(r.content, "csid") if csid]


def _quote(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _csid_from(r: httpx.Response) -> str:
    loc = r.headers.get("location", "")
    csid = loc.rstrip("/").rsplit("/", 1)[-1]
    if r.status_code != 201 or not csid:
        raise CSpaceError("unknown", f"expected 201 with a Location header, got {r.status_code}", r.status_code)
    return csid


def _list_items(xml: bytes, field_name: str) -> list[tuple[str, str]]:
    root = SafeET.fromstring(xml)
    return [(_text(it, "csid"), _text(it, field_name)) for it in _items(root)]


def display_name(ref_name: str) -> str:
    """The display part of a refName: urn:...:item:name(x)'Display Name' -> Display Name."""
    if ref_name.endswith("'") and "'" in ref_name[:-1]:
        return ref_name[ref_name.index("'") + 1:-1]
    return ref_name
