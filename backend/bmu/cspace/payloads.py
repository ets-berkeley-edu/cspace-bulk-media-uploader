"""XML payloads for the records the BMU creates, built with ElementTree so every value is escaped."""
from __future__ import annotations

import re
from xml.etree.ElementTree import Element, SubElement, tostring

from ..tenant import Tenant

NS_MEDIA = "http://collectionspace.org/services/media"
NS_OBJECT = "http://collectionspace.org/services/collectionobject"
NS_RELATION = "http://collectionspace.org/services/relation"
NS_GROUP = "http://collectionspace.org/services/group"


def _doc(name: str) -> Element:
    return Element("document", {"name": name})


def _part(doc: Element, part: str, ns: str) -> Element:
    return SubElement(doc, f"ns2:{part}", {"xmlns:ns2": ns})


def _add(parent: Element, tag: str, value: str | None) -> None:
    if value not in (None, ""):
        SubElement(parent, tag).text = value


def _xml(doc: Element) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(doc, encoding="utf-8", xml_declaration=False)




def _as_list(v) -> list:
    """Repeating fields are lists; rows saved before they were repeating hold a single string."""
    return list(v) if isinstance(v, (list, tuple)) else ([v] if v else [])


def media_xml(tenant: Tenant, row: dict) -> bytes:
    """Media record for a row. Authority fields are refNames; the UI only shows display names.

    blobCsid is not sent: the file is attached afterwards with PUT media/{csid}/blob, which creates
    the Blob record and sets blobCsid itself.
    """
    doc = _doc("media")
    common = _part(doc, "media_common", NS_MEDIA)
    _add(common, "identificationNumber", row.get("idnum"))
    _add(common, "title", row.get("file"))
    types = [t for t in _as_list(row.get("type")) if t]
    if types:
        tl = SubElement(common, "typeList")
        for t in types:
            _add(tl, "type", t)
    _add(common, "creator", row.get("creator"))
    _add(common, "contributor", row.get("contributor"))
    _add(common, "rightsHolder", row.get("rightsHolder"))
    if row.get("date"):
        # The structured date group from CollectionSpace's parser (design: Structured dates), as the UI saves it.
        grp = SubElement(SubElement(common, "dateGroupList"), "dateGroup")
        _add(grp, "dateDisplayDate", row["date"])
        parsed = (row.get("lookups") or {}).get("date") or {}
        if parsed.get("value") == row["date"]:
            for k, v in (parsed.get("group") or {}).items():
                if k != "dateDisplayDate":
                    _add(grp, k, v)
    langs = [x for x in _as_list(row.get("language")) if x]  # required: an empty Language blocks the row
    ll = SubElement(common, "languageList")
    for lang in langs:
        _add(ll, "language", lang)
    _add(common, "description", row.get("description"))
    _add(common, "copyrightStatement", row.get("copyright"))

    local = _part(doc, tenant.media_extension, f"{NS_MEDIA}/local/{tenant.key}")
    # The tenant's one publish field (design: Protected files): approvedForWeb true/false at PAHMA, postToPublic
    # yes/no at UCJEPS. The UI shows it as Restricted, its inverse.
    pub = tenant.publish
    if pub.get("field"):
        approved = not row.get("restricted", pub.get("default", False)) if pub.get("invert") else bool(row.get("publish", True))
        yes, no = publish_values(tenant)
        _add(local, pub["field"], yes if approved else no)
    if tenant.primary_display:  # not in every tenant's Media extension (UCJEPS's has none)
        _add(local, "primaryDisplay", "false")
    return _xml(doc)


def publish_values(tenant: Tenant) -> tuple[str, str]:
    """What the publish field holds for "may go public" and for "may not": true/false unless the tenant's
    configuration names others (publish.values, for example [yes, no] for an option list such as yesNoValues)."""
    values = tenant.publish.get("values") or ["true", "false"]
    return str(values[0]), str(values[1])


def object_xml(object_number: str) -> bytes:
    """A skeletal Object record, as the legacy 'media+create+accession' handling creates."""
    doc = _doc("collectionobjects")
    common = _part(doc, "collectionobjects_common", NS_OBJECT)
    _add(common, "objectNumber", object_number)
    return _xml(doc)


def group_xml(title: str) -> bytes:
    """A Group record (design: Groups). VERIFY on QA with check_cspace.py --create: groups_common/title."""
    doc = _doc("groups")
    common = _part(doc, "groups_common", NS_GROUP)
    _add(common, "title", title)
    return _xml(doc)


def relation_xml(subject_csid: str, subject_type: str, object_csid: str, object_type: str) -> bytes:
    doc = _doc("relations")
    common = _part(doc, "relations_common", NS_RELATION)
    _add(common, "relationshipType", "affects")
    _add(common, "objectCsid", object_csid)
    _add(common, "objectDocumentType", object_type)
    _add(common, "subjectCsid", subject_csid)
    _add(common, "subjectDocumentType", subject_type)
    return _xml(doc)
