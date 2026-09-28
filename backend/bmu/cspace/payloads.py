"""XML payloads for the records the BMU creates, built with ElementTree so every value is escaped."""
from __future__ import annotations

import re
from xml.etree.ElementTree import Element, SubElement, tostring

from ..tenant import Tenant

NS_MEDIA = "http://collectionspace.org/services/media"
NS_OBJECT = "http://collectionspace.org/services/collectionobject"
NS_RELATION = "http://collectionspace.org/services/relation"


def _doc(name: str) -> Element:
    return Element("document", {"name": name})


def _part(doc: Element, part: str, ns: str) -> Element:
    return SubElement(doc, f"ns2:{part}", {"xmlns:ns2": ns})


def _add(parent: Element, tag: str, value: str | None) -> None:
    if value not in (None, ""):
        SubElement(parent, tag).text = value


def _xml(doc: Element) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(doc, encoding="utf-8", xml_declaration=False)


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def media_xml(tenant: Tenant, row: dict, blob_csid: str) -> bytes:
    """Media record for a row. Authority fields are refNames; the UI only shows display names."""
    doc = _doc("media")
    common = _part(doc, "media_common", NS_MEDIA)
    _add(common, "blobCsid", blob_csid)
    _add(common, "identificationNumber", row.get("idnum"))
    _add(common, "title", row.get("file"))
    if row.get("type"):
        _add(SubElement(common, "typeList"), "type", row["type"])
    _add(common, "creator", row.get("creator"))
    _add(common, "contributor", row.get("contributor"))
    _add(common, "rightsHolder", row.get("rightsHolder"))
    if row.get("date"):
        grp = SubElement(SubElement(common, "dateGroupList"), "dateGroup")
        _add(grp, "dateDisplayDate", row["date"])
        m = _ISO.match(row["date"])
        if m:  # a single exact day: fill the structured earliest date too
            y, mo, d = m.groups()
            _add(grp, "dateEarliestSingleYear", str(int(y)))
            _add(grp, "dateEarliestSingleMonth", str(int(mo)))
            _add(grp, "dateEarliestSingleDay", str(int(d)))
            _add(grp, "dateEarliestScalarValue", f"{y}-{mo}-{d}")
            _add(grp, "dateLatestScalarValue", f"{y}-{mo}-{d}")
    langs = row.get("languages") or [tenant.language_default]
    ll = SubElement(common, "languageList")
    for lang in langs:
        _add(ll, "language", lang)
    _add(common, "description", row.get("description"))
    _add(common, "copyrightStatement", row.get("copyright"))

    local = _part(doc, tenant.media_extension, f"{NS_MEDIA}/local/{tenant.key}")
    pub = tenant.publish
    if pub.get("field") == "approvedForWeb":
        approved = not row.get("restricted", pub.get("default", False)) if pub.get("invert") else bool(row.get("publish", True))
        _add(local, "approvedForWeb", "true" if approved else "false")
    _add(local, "primaryDisplay", "false")
    return _xml(doc)


def object_xml(object_number: str) -> bytes:
    """A skeletal Object record, as the legacy 'media+create+accession' handling creates."""
    doc = _doc("collectionobjects")
    common = _part(doc, "collectionobjects_common", NS_OBJECT)
    _add(common, "objectNumber", object_number)
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
