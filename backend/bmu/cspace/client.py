"""Minimal CollectionSpace REST client used by the web app (checks, autocomplete) and the worker.

Every call uses the signed-in user's own credentials (HTTP Basic), never a service account.
Items marked VERIFY are to be confirmed against the Lyrasis QA tenant.
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
            "media": self.can("media", "C") and self.can("blobs", "C"),
            "relations": self.can("relations", "C"),
            "objects": self.can("collectionobjects", "C"),
            "readObjects": self.can("collectionobjects", "R"),
            "authorities": self.can("personauthorities", "R") and self.can("orgauthorities", "R"),
        }

    @classmethod
    def from_xml(cls, xml: bytes) -> "Permissions":
        # VERIFY: accountperms may list either an <actionGroup> (e.g. "CRUDL") or <action><name> elements.
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
                 http: httpx.Client | None = None, timeout: float = 300.0):
        self.base = base_url.rstrip("/") + SERVICES
        self._http = http or httpx.Client(timeout=timeout, follow_redirects=False)
        self._auth = httpx.BasicAuth(username, password)

    def close(self) -> None:
        self._http.close()

    # -- low level ----------------------------------------------------------------------
    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = self._http.request(method, self.base + path, auth=self._auth, **kw)
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
        # VERIFY: advanced search syntax and exact-match behavior on the QA tenant.
        q = f'collectionobjects_common:objectNumber = "{_quote(object_number)}"'
        r = self._request("GET", "collectionobjects", params={"as": q, "wf_deleted": "false", "pgSz": "10"})
        return [csid for csid, num in _list_items(r.content, "objectNumber") if num == object_number]

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
        for item in _children(root, "list-item"):
            ref = _text(item, "refName")
            name = _text(item, "termDisplayName") or _text(item, "displayName") or display_name(ref)
            if ref:
                out.append({"refName": ref, "displayName": name})
        return out

    # -- creates (the BMU never updates or deletes) ---------------------------------------
    def create_blob(self, filename: str, stream: IO[bytes], content_type: str) -> str:
        """Upload a file as a Blob (multipart POST /blobs, as the legacy BMU does). Streams the body."""
        files = {"file": (filename, stream, content_type or "application/octet-stream")}
        r = self._request("POST", "blobs", files=files, data={"submit": "OK"})
        return _csid_from(r)

    def create_media(self, xml: bytes) -> str:
        return self._post_xml("media", xml)

    def create_object(self, xml: bytes) -> str:
        return self._post_xml("collectionobjects", xml)

    def create_relation(self, xml: bytes) -> str:
        return self._post_xml("relations", xml)


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
    return [(_text(it, "csid"), _text(it, field_name)) for it in _children(root, "list-item")]


def display_name(ref_name: str) -> str:
    """The display part of a refName: urn:...:item:name(x)'Display Name' -> Display Name."""
    if ref_name.endswith("'") and "'" in ref_name[:-1]:
        return ref_name[ref_name.index("'") + 1:-1]
    return ref_name
