import base64

import boto3
import pytest
from cryptography.exceptions import InvalidTag
from defusedxml import ElementTree as ET

from bmu.crypto import KmsCrypto, LocalCrypto
from bmu.cspace.client import Permissions, display_name
from bmu.cspace.payloads import media_xml, object_xml, relation_xml
from bmu.rows import apply_edit, new_row
from bmu.tenant import load_tenant, parse_filename

T = load_tenant("pahma")


def text(xml: bytes, tag: str) -> list[str]:
    root = ET.fromstring(xml)
    return [(e.text or "") for e in root.iter() if e.tag.split(":")[-1] == tag]


@pytest.mark.parametrize("name,obj,ok", [
    ("15-1234_a.jpg", "15-1234", True),
    ("15-1234.tif", "15-1234", True),
    ("1-2345_1.tif", "1-2345", True),
    ("_bad name.jpg", "", False),
])
def test_parse_filename(name, obj, ok):
    p = parse_filename(T, name)
    assert p["ok"] is ok and p["obj"] == obj


def test_new_row_defaults_and_mediaonly_idnum():
    r = new_row(T, "15-1234_a.jpg", 10, "image/jpeg")
    assert r["handling"] == "link" and r["idnum"] == "15-1234" and r["restricted"] is False
    apply_edit(T, r, {"handling": "mediaonly"})
    assert r["idnum"] == "15-1234_a"  # legacy PAHMA: image number for media-only records
    apply_edit(T, r, {"idnum": "custom"})
    apply_edit(T, r, {"handling": "link"})
    assert r["idnum"] == "custom"  # an ID the user typed is kept


def test_authority_fields_must_be_refnames():
    r = new_row(T, "15-1234_a.jpg", 10, "image/jpeg")
    with pytest.raises(ValueError):
        apply_edit(T, r, {"creator": "Leslie Freund"})
    ref = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'"
    apply_edit(T, r, {"creator": ref})
    assert r["creator"] == ref and display_name(ref) == "Leslie Freund"


def test_locked_row_cannot_change():
    r = new_row(T, "15-1234_a.jpg", 10, "image/jpeg")
    r["result"] = {"state": "Partial", "steps": {"media": {"s": "done", "csid": "abc"}}}
    with pytest.raises(ValueError):
        apply_edit(T, r, {"handling": "create"})


def test_media_xml_restricted_refnames_and_escaping():
    r = new_row(T, "15-1234_a.jpg", 10, "image/jpeg")
    ref = "urn:cspace:pahma.cspace.berkeley.edu:personauthorities:name(person):item:name(7475)'Leslie Freund'"
    r.update(restricted=True, creator=ref, description="Bowl & <lid>", date="2025-06-14", type=["image"],
             lookups={"date": {"value": "2025-06-14", "ok": True,  # as parsed by CollectionSpace's structureddates
                               "group": {"dateEarliestSingleYear": "2025", "dateEarliestScalarValue": "2025-06-14T00:00:00.000Z"}}})
    xml = media_xml(T, r)
    assert text(xml, "approvedForWeb") == ["false"]
    assert text(xml, "creator") == [ref]
    assert text(xml, "description") == ["Bowl & <lid>"]
    assert text(xml, "blobCsid") == []  # the file is attached later with PUT media/{csid}/blob
    assert text(xml, "identificationNumber") == ["15-1234"]
    assert text(xml, "dateEarliestSingleYear") == ["2025"]
    assert text(xml, "language") == [T.language_default]
    r["restricted"] = False
    assert text(media_xml(T, r), "approvedForWeb") == ["true"]
    assert text(object_xml("15-9"), "objectNumber") == ["15-9"]
    assert text(relation_xml("m", "Media", "o", "CollectionObject"), "subjectDocumentType") == ["Media"]


def test_permissions_both_formats():
    xml = b"""<ns2:account_permission xmlns:ns2="x"><permission><resourceName>media</resourceName><actionGroup>CRUDL</actionGroup></permission>
    <permission><resourceName>blobs</resourceName><action><name>CREATE</name></action><action><name>READ</name></action></permission>
    <permission><resourceName>relations</resourceName><actionGroup>RL</actionGroup></permission></ns2:account_permission>"""
    p = Permissions.from_xml(xml)
    assert p.can("media", "C") and p.can("blobs", "C") and not p.can("relations", "C")
    assert p.summary["media"] and not p.summary["relations"]
    # only media permissions are needed to attach the file (PUT media/{csid}/blob)
    assert Permissions({"media": {"C", "U"}}).summary["media"]


def test_local_crypto_binds_context():
    c = LocalCrypto({"session": b"a" * 32, "job": b"b" * 32})
    tok = c.encrypt("job", "secret", {"user": "u", "job": "1"})
    assert c.decrypt("job", tok, {"user": "u", "job": "1"}) == "secret"
    with pytest.raises(InvalidTag):
        c.decrypt("job", tok, {"user": "u", "job": "2"})
    with pytest.raises(InvalidTag):
        c.decrypt("session", base64.b64encode(base64.b64decode(tok)).decode(), {"user": "u", "job": "1"})


def test_kms_crypto(aws):
    kms = boto3.client("kms", region_name="us-west-2")
    ks = kms.create_key()["KeyMetadata"]["KeyId"]
    kj = kms.create_key()["KeyMetadata"]["KeyId"]
    c = KmsCrypto(kms, {"session": ks, "job": kj})
    secret = "correct-horse-battery-staple"  # long enough never to appear in the token by chance
    tok = c.encrypt("job", secret, {"user": "u", "job": "9"})
    assert secret not in tok and c.decrypt("job", tok, {"user": "u", "job": "9"}) == secret


def test_step_plan_follows_design():
    from bmu.worker import plan_steps
    r = new_row(T, "15-1234_a.jpg", 10, "image/jpeg")
    assert plan_steps(T, r) == [("media", []), ("findObject", []), ("upload", ["media"]),
                                ("relMediaObject", ["media", "findObject"]), ("relObjectMedia", ["media", "findObject"])]
    r["handling"] = "mediaonly"
    assert plan_steps(T, r) == [("media", []), ("upload", ["media"])]


def test_create_tables_waits_for_local_services(monkeypatch):
    """docker compose starts the web app and worker with DynamoDB Local/S3: retry until they answer."""
    from botocore.exceptions import EndpointConnectionError
    from bmu.storage import Storage

    calls = []
    def flaky(self):
        calls.append(1)
        if len(calls) < 3:
            raise EndpointConnectionError(endpoint_url="http://dynamodb:8000")
    monkeypatch.setattr(Storage, "_create_tables", flaky)
    monkeypatch.setattr("bmu.storage.time.sleep", lambda s: None)
    Storage.create_tables(object.__new__(Storage))
    assert len(calls) == 3
