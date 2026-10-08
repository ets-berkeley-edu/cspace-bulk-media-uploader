"""UCJEPS's tenant configuration (tenants/ucjeps.yaml): what the legacy BMU did for UCJEPS, as configuration, and the
two things it needed from the code: a publish field with yes/no values (postToPublic) and no primaryDisplay."""
from importlib import resources

import pytest
import yaml
from defusedxml import ElementTree as ET

from bmu import sensitivity
from bmu.cspace.payloads import media_xml
from bmu.rows import apply_edit, new_row
from bmu.tenant import load_tenant, parse_filename, parse_tenant

U = load_tenant("ucjeps")
P = load_tenant("pahma")
NS = "http://collectionspace.org/services/media/local/ucjeps"


def text(xml: bytes, tag: str) -> list[str]:
    return [(e.text or "") for e in ET.fromstring(xml).iter() if e.tag.split(":")[-1].split("}")[-1] == tag]


def test_ucjeps_loads_with_the_legacy_options():
    assert (U.key, U.name, U.domain, U.media_extension) == ("ucjeps", "UCJEPS", "ucjeps.cspace.berkeley.edu", "media_ucjeps")
    assert [h.id for h in U.handling] == ["link", "create", "mediaonly", "slide"]  # born-digital waits for DP numbers
    assert [h.legacy for h in U.handling] == ["media+accession", "media+create+accession", "mediaonly", "slide"]
    assert all(h.id_rule == "object" for h in U.handling)  # legacy: identificationNumber = the object number, always
    assert U.handling_by_id("slide").object == "none" and U.handling_by_id("mediaonly").object == "none"
    assert U.language_default == "urn:cspace:ucjeps.cspace.berkeley.edu:vocabularies:name(languages):item:name(eng)'English'"
    assert set(U.authority_fields["contributor"]) == {"person", "organization", "institution"}
    assert U.authorities["institution"] == {"service": "orgauthorities", "vocabulary": "institution"}


def test_media_types_are_ucjeps_values_with_its_labels():
    assert [(o.value, o.label) for o in U.media_types][:3] == [("dataset", "dataset"), ("Digital Image", "digital image"),
                                                               ("document", "document")]
    assert "Slide (Photograph)" in U.media_type_values and "image" not in U.media_type_values  # not PAHMA's list


@pytest.mark.parametrize("name, obj", [
    ("UC1107670.JPG", "UC1107670"),
    ("UC1107670_a_nice_pic.JPG", "UC1107670"),
    ("JEPS12345.v2.tif", "JEPS12345"),  # legacy: the name up to its first "."
    ("UC-123_x.jpg", "UC-123"),
])
def test_the_object_number_is_the_name_up_to_its_first_dot_or_underscore(name, obj):
    p = parse_filename(U, name)
    assert p["ok"] and p["obj"] == obj


def test_a_name_with_other_characters_doesnt_parse():
    assert not parse_filename(U, "UC 1107670.jpg")["ok"]


def test_slide_presets_type_copyright_and_contributor():
    r = new_row(U, "UC1107670.jpg", 10, "image/jpeg")
    assert r["handling"] == "link" and r["type"] == [] and r["contributor"] == ""
    apply_edit(U, r, {"handling": "slide"})
    assert r["type"] == ["Slide (Photograph)"]
    assert r["copyright"] == "Material may be protected by copyright (Title 17, U.S. Code)."
    assert r["contributor"].endswith("'University and Jepson Herbaria Image Collection'")
    assert r["idnum"] == "UC1107670"


def test_media_record_sends_post_to_public_yes_or_no_and_no_primary_display():
    r = new_row(U, "UC1107670.jpg", 10, "image/jpeg")
    xml = media_xml(U, r)
    root = ET.fromstring(xml)
    assert [e.tag for e in root if "/local/" in e.tag] == [f"{{{NS}}}media_ucjeps"]  # UCJEPS's extension
    assert text(xml, "postToPublic") == ["yes"]  # not restricted, as UCJEPS's UI defaults it
    assert text(xml, "approvedForWeb") == [] and text(xml, "primaryDisplay") == []
    r["restricted"] = True
    assert text(media_xml(U, r), "postToPublic") == ["no"]


def test_pahma_still_sends_approved_for_web_true_or_false_and_primary_display():
    r = new_row(P, "15-1234_a.jpg", 10, "image/jpeg")
    assert text(media_xml(P, r), "approvedForWeb") == ["true"] and text(media_xml(P, r), "primaryDisplay") == ["false"]
    r["restricted"] = True
    assert text(media_xml(P, r), "approvedForWeb") == ["false"] and text(media_xml(P, r), "postToPublic") == []


def obj(post_to_public: str) -> bytes:
    return (f'<document name="collectionobjects"><ns2:collectionobjects_ucjeps xmlns:ns2="http://collectionspace.org/'
            f'services/collectionobject/local/ucjeps"><postToPublic>{post_to_public}</postToPublic>'
            f'</ns2:collectionobjects_ucjeps></document>').encode()


def test_a_specimen_not_posted_to_public_makes_its_documents_protected():
    assert sensitivity.evaluate(U.sensitivity, obj("no"))["protect"] == ["specimen not posted to public"]
    assert sensitivity.evaluate(U.sensitivity, obj("yes"))["protect"] == []
    assert sensitivity.evaluate(U.sensitivity, obj(""))["protect"] == []  # not set: UCJEPS's UI default is yes


@pytest.mark.parametrize("values", [[True, False], ["yes"], "yes", ["yes", ""]])
def test_publish_values_must_be_two_words(values):
    raw = yaml.safe_load(resources.files("bmu.tenants").joinpath("ucjeps.yaml").read_text(encoding="utf-8"))
    raw["publish"]["values"] = values
    with pytest.raises(ValueError, match="publish.values"):
        parse_tenant(raw, "ucjeps")


def test_bare_yes_and_no_in_yaml_are_caught():
    """YAML reads [yes, no] as [true, false]: the configuration must quote them, and loading refuses it otherwise."""
    assert yaml.safe_load("v: [yes, no]")["v"] == [True, False]
