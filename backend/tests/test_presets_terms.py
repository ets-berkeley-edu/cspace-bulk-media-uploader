"""Handling presets (design: Handling per document) and checks that a row's values still exist in CollectionSpace
(design: Authority term fields; Media record fields)."""
import copy
from importlib import resources

import pytest
import yaml
from fastapi.testclient import TestClient

from bmu import app as appmod
from bmu.cspace import CSpaceClient, CSpaceError
from bmu.rows import apply_edit, check_rows, from_preset, new_row
from bmu.tenant import load_tenant, parse_tenant
from fakecspace.app import app as fake_app

DOMAIN = "pahma.cspace.berkeley.edu"
LESLIE = f"urn:cspace:{DOMAIN}:personauthorities:name(person):item:name(7475)'Leslie Freund'"
NATASHA = f"urn:cspace:{DOMAIN}:personauthorities:name(person):item:name(NatashaJohnson1400000000000)'Natasha Johnson'"
HEARST = (f"urn:cspace:{DOMAIN}:orgauthorities:name(organization):item:name(PhoebeAHearstMuseumofAnthropology1400000000000)"
          "'Phoebe A. Hearst Museum of Anthropology'")
ENG = f"urn:cspace:{DOMAIN}:vocabularies:name(languages):item:name(eng)'English'"
SPA = f"urn:cspace:{DOMAIN}:vocabularies:name(languages):item:name(spa)'Spanish'"
ALL = {"media": True, "mediaUpdate": True, "relations": True, "objects": True, "readObjects": True, "groups": True,
       "readMedia": True, "readPersons": True, "readOrgs": True, "readDates": True}
PRESET_NOTE = " It was filled in from PAHMA’s preset, so the preset needs updating too: tell the BMU administrator."


def pahma_raw() -> dict:
    return yaml.safe_load(resources.files("bmu.tenants").joinpath("pahma.yaml").read_text(encoding="utf-8"))


def tenant_with(presets_by_handling: dict) -> "object":
    """PAHMA's configuration with test presets (PAHMA's own are empty)."""
    raw = pahma_raw()
    for h in raw["handling"]:
        h["presets"] = presets_by_handling.get(h["id"], {})
    return parse_tenant(raw, "pahma")


PRESETS = {"mediaonly": {"type": ["image"], "contributor": HEARST, "copyright": "© Regents", "language": [SPA]},
           "create": {"type": ["slide"]}}


@pytest.fixture
def preset_tenant(services):
    services.tenant = tenant_with(PRESETS)
    return services.tenant


@pytest.fixture(autouse=True)
def fresh_vocabularies():
    appmod._VOCAB_CACHE.clear()
    yield
    appmod._VOCAB_CACHE.clear()


def new_job(api):
    return api.post("/api/jobs", json={"name": "Presets"}).json()["id"]


def _texts(row, level=None):
    return [c["text"] for c in row["checks"] if level is None or c["level"] == level]


def client():
    return CSpaceClient("http://fake", "admin", "admin", http=TestClient(fake_app, base_url="http://fake"))


def uploaded(tenant, name="15-1234_1.jpg", n=1, handling=None):
    r = new_row(tenant, name, 10, "image/jpeg")
    r.update(n=n, upload={"s": "done"})
    if handling:
        apply_edit(tenant, r, {"handling": handling})
        r["touched"].remove("handling")
    return r


# ---- A. handling presets --------------------------------------------------------------------------------
def test_pahma_presets_are_empty_and_exposed_to_the_browser():
    t = load_tenant("pahma")
    assert all(h.presets == {} for h in t.handling)
    assert all(h["presets"] == {} for h in t.public_summary()["handling"])


@pytest.mark.parametrize("presets,problem", [
    ({"creator": LESLIE}, "creator can't be preset"),
    ({"description": "x"}, "description can't be preset"),
    ({"type": ["painting"]}, "media type 'painting' isn't in media_types"),
    ({"type": "image"}, "type must be a list"),
    ({"language": ["English"]}, "isn't a refName of pahma.cspace.berkeley.edu's languages vocabulary"),
    ({"language": [ENG.replace(DOMAIN, "bampfa.cspace.berkeley.edu")]}, "languages vocabulary"),
    ({"contributor": "Phoebe A. Hearst Museum"}, "contributor must be the full refName"),
    ({"contributor": HEARST.replace("name(organization)", "name(ulan_oa)")}, "contributor must be the full refName"),
    ({"copyright": 1920}, "copyright must be text"),
])
def test_presets_are_validated_when_the_tenant_loads(presets, problem):
    with pytest.raises(ValueError) as e:
        tenant_with({"link": presets})
    assert problem in str(e.value) and "presets of handling link" in str(e.value)


def test_valid_presets_load_and_are_exposed():
    t = tenant_with(PRESETS)
    summary = {h["id"]: h for h in t.public_summary()["handling"]}
    assert summary["mediaonly"]["presets"] == PRESETS["mediaonly"] and summary["link"]["presets"] == {}


def test_new_rows_get_their_handlings_presets():
    t = tenant_with({"link": PRESETS["mediaonly"]})
    r = new_row(t, "15-1234_1.jpg", 10, "image/jpeg")
    assert (r["type"], r["contributor"], r["copyright"], r["language"]) == (["image"], HEARST, "© Regents", [SPA])
    assert r["touched"] == [] and all(from_preset(t, r, k) for k in ("type", "contributor", "copyright", "language"))
    assert not from_preset(t, r, "creator")


def test_changing_handling_reapplies_presets_to_fields_the_user_has_not_edited():
    t = tenant_with(PRESETS)
    r = new_row(t, "15-1234_1.jpg", 10, "image/jpeg")  # link: no presets
    assert (r["type"], r["contributor"], r["copyright"], r["language"]) == ([], "", "", [t.language_default])
    apply_edit(t, r, {"copyright": "Mine"})
    apply_edit(t, r, {"handling": "mediaonly"})
    assert (r["type"], r["contributor"], r["copyright"], r["language"]) == (["image"], HEARST, "Mine", [SPA])
    assert from_preset(t, r, "type") and not from_preset(t, r, "copyright")
    # a field edited in the same change keeps the edit
    apply_edit(t, r, {"handling": "create", "language": [ENG, SPA]})
    assert (r["type"], r["contributor"], r["copyright"], r["language"]) == (["slide"], "", "Mine", [ENG, SPA])
    # back to a handling without presets: its untouched fields are emptied, Language gets the default
    apply_edit(t, r, {"handling": "link"})
    assert (r["type"], r["contributor"], r["copyright"], r["language"]) == ([], "", "Mine", [ENG, SPA])


def test_a_row_whose_media_record_exists_keeps_its_fields_when_its_handling_changes():
    t = tenant_with({"linkorcreate": {"type": ["slide"]}})
    r = new_row(t, "15-1234_1.jpg", 10, "image/jpeg")
    apply_edit(t, r, {"handling": "create"})
    r["result"] = {"state": "Partial", "steps": {"media": {"s": "done", "csid": "m1"},
                                                  "createObject": {"s": "failed", "code": "object_exists"}}}
    apply_edit(t, r, {"handling": "linkorcreate"})  # relinking after object_exists
    assert r["handling"] == "linkorcreate" and r["type"] == []


def test_presets_apply_when_files_are_added_and_on_single_and_bulk_handling_changes(api, login, add_uploaded, preset_tenant):
    info = login()
    assert {h["id"]: h["presets"] for h in info["tenant"]["handling"]}["create"] == {"type": ["slide"]}
    assert {h["id"]: h["presets"] for h in api.get("/api/me").json()["tenant"]["handling"]}["mediaonly"]["contributor"] == HEARST
    job = new_job(api)
    a, b, c = add_uploaded(job, ["15-1234_1.jpg", "1-2345_1.jpg", "12-5678_1.jpg"])
    assert a["type"] == [] and a["language"] == [preset_tenant.language_default]
    r = api.patch(f"/api/jobs/{job}/rows/{a['n']}", json={"handling": "mediaonly"}).json()["row"]
    assert (r["type"], r["contributor"], r["copyright"], r["language"]) == (["image"], HEARST, "© Regents", [SPA])
    assert r["touched"] == ["handling"]
    api.patch(f"/api/jobs/{job}/rows/{b['n']}", json={"type": ["audio"]})
    r = api.post(f"/api/jobs/{job}/rows/bulk", json={"rows": [b["n"], c["n"]], "changes": {"handling": "create"}})
    assert r.status_code == 200, r.text
    rows = {x["n"]: x for x in api.get(f"/api/jobs/{job}").json()["rows"]}
    assert rows[b["n"]]["type"] == ["audio"] and rows[c["n"]]["type"] == ["slide"]  # the edited field keeps the edit


# ---- B. no row check for create on media ---------------------------------------------------------------
def test_no_row_check_for_create_on_media(fake):
    t = load_tenant("pahma")
    r = uploaded(t, handling="mediaonly")
    check_rows(t, [r], client(), {**ALL, "media": False})
    assert not any("create Media records" in x for x in _texts(r))
    check_rows(t, [r], client(), {**ALL, "mediaUpdate": False})
    assert any("can't update Media records" in x for x in _texts(r, "block"))  # the other checks stay


# ---- C. values that no longer exist in CollectionSpace -------------------------------------------------------
def test_fake_authority_items_by_urn_and_deleted_terms(fake):
    c = client()
    assert c.authority_term("personauthorities", "person", "7475") == LESLIE
    fake.term_states["7475"] = "deleted"
    assert c.authority_term("personauthorities", "person", "7475") is None  # soft-deleted: workflow state deleted
    assert "Leslie" not in str(c.search_terms("personauthorities", "person", "Leslie"))  # searches leave it out
    assert c.authority_term("personauthorities", "person", "nobody") is None  # 404
    tc = TestClient(fake_app, base_url="http://fake")
    assert tc.post("/_fake/delete-term", params={"name": "Natasha Johnson", "how": "gone"}).status_code == 200
    assert c.authority_term("personauthorities", "person", "NatashaJohnson1400000000000") is None
    assert tc.post("/_fake/delete-language", params={"code": "spa"}).status_code == 200
    assert SPA not in [x["refName"] for x in c.vocabulary_items("languages")]
    fake.fail_next["orgauthorities"] = 500
    with pytest.raises(Exception) as e:
        c.authority_term("orgauthorities", "organization", "x")
    assert getattr(e.value, "code", "") == "server"


def test_deleted_or_merged_terms_block_with_their_label(fake):
    t = load_tenant("pahma")
    fake.term_states.update({"7475": "deleted", "NatashaJohnson1400000000000": "gone"})
    r = uploaded(t, handling="mediaonly")
    apply_edit(t, r, {"creator": LESLIE, "contributor": HEARST, "rightsHolder": NATASHA})
    check_rows(t, [r], client(), ALL)
    blocks = _texts(r, "block")
    assert ("Creator “Leslie Freund” no longer exists in CollectionSpace (it was deleted, or merged into another term). "
            "Choose another creator.") in blocks
    assert ("Rights holder “Natasha Johnson” no longer exists in CollectionSpace (it was deleted, or merged into another "
            "term). Choose another rights holder.") in blocks
    assert not any("Contributor" in x for x in _texts(r))  # the Hearst Museum still exists
    assert r["lookups"]["term:creator"]["csids"] == [] and r["lookups"]["term:contributor"]["csids"] == [HEARST]
    # a cleared field forgets its lookup
    apply_edit(t, r, {"creator": ""})
    check_rows(t, [r], client(), ALL)
    assert "term:creator" not in r["lookups"] and not any("Creator" in x for x in _texts(r))


def test_one_request_per_distinct_refname_per_check(fake):
    t = load_tenant("pahma")
    rows = []
    for n in range(1, 1001):
        r = uploaded(t, f"15-1234_{n}.jpg", n, handling="mediaonly")
        apply_edit(t, r, {"creator": LESLIE, "rightsHolder": LESLIE, "contributor": HEARST if n % 2 else ""})
        rows.append(r)
    fake.term_reads.clear()
    check_rows(t, rows, client(), ALL)
    assert sorted(fake.term_reads) == sorted(["7475", "PhoebeAHearstMuseumofAnthropology1400000000000"])
    assert not any("no longer exists" in x for r in rows for x in _texts(r))
    # kept on the rows like the other lookups: an edit re-checks only its own row's terms, from the stored lookup
    fake.term_reads.clear()
    assert check_rows(t, rows, client(), ALL, targets={1}) == set()
    assert fake.term_reads == []
    # scheduling (refresh) reads them again, once each
    fake.term_states["7475"] = "deleted"
    check_rows(t, rows, client(), ALL, refresh=True)
    assert sorted(fake.term_reads) == sorted(["7475", "PhoebeAHearstMuseumofAnthropology1400000000000"])
    assert all("Creator “Leslie Freund” no longer exists" in " ".join(_texts(r, "block")) for r in rows)


def test_a_failed_lookup_warns_and_never_claims_the_term_is_missing(fake):
    t = load_tenant("pahma")
    rows = [uploaded(t, f"15-1234_{n}.jpg", n, handling="mediaonly") for n in (1, 2, 3)]
    for r in rows:
        apply_edit(t, r, {"creator": LESLIE})
    fake.term_reads.clear()
    fake.fail_next["personauthorities"] = 500
    check_rows(t, rows, client(), ALL)
    assert fake.term_reads == ["7475"]  # the failure is kept for the call too: not one request per row
    for r in rows:
        assert "Couldn't check Creator “Leslie Freund” in CollectionSpace (server)." in _texts(r, "warn")
        assert not any("no longer exists" in x for x in _texts(r)) and "term:creator" not in r.get("lookups", {})
    check_rows(t, rows, client(), ALL)  # not stored, so the next check asks again
    assert fake.term_reads == ["7475", "7475"] and not any("Couldn't check Creator" in x for x in _texts(rows[0]))


def test_an_authority_the_user_cannot_read_blocks_instead_of_the_existence_check(fake):
    t = load_tenant("pahma")
    fake.term_states["7475"] = "deleted"
    r = uploaded(t, handling="mediaonly")
    apply_edit(t, r, {"creator": LESLIE})
    fake.term_reads.clear()
    check_rows(t, [r], client(), {**ALL, "readPersons": False})
    assert any("can't read the Person authority" in x for x in _texts(r, "block"))
    assert not any("no longer exists" in x for x in _texts(r)) and fake.term_reads == []


def test_preset_terms_that_no_longer_exist_say_the_preset_needs_updating(fake):
    t = tenant_with({"mediaonly": {"contributor": HEARST}})
    fake.term_states["PhoebeAHearstMuseumofAnthropology1400000000000"] = "deleted"
    r = uploaded(t, handling="mediaonly")
    assert r["contributor"] == HEARST
    check_rows(t, [r], client(), ALL)
    assert ("Contributor “Phoebe A. Hearst Museum of Anthropology” no longer exists in CollectionSpace (it was deleted, or "
            "merged into another term). Choose another contributor." + PRESET_NOTE) in _texts(r, "block")
    # the same value chosen by the user is the user's
    r2 = uploaded(t, handling="mediaonly")
    apply_edit(t, r2, {"contributor": ""})
    apply_edit(t, r2, {"contributor": HEARST})
    check_rows(t, [r2], client(), ALL)
    assert any(x.endswith("Choose another contributor.") for x in _texts(r2, "block"))


def test_languages_no_longer_in_the_vocabulary_block(fake):
    t = load_tenant("pahma")
    fake.deleted_languages.update({"spa", "eng"})
    terms = lambda: client().vocabulary_items("languages")  # noqa: E731
    r = uploaded(t, handling="mediaonly")  # the default language, English: from the tenant's default
    check_rows(t, [r], client(), ALL, languages=terms)
    assert ("Language “English” is no longer in CollectionSpace’s language list. Choose another language." + PRESET_NOTE
            in _texts(r, "block"))
    apply_edit(t, r, {"language": [ENG, SPA, ENG.replace("(eng)'English'", "(fre)'French'")]})
    check_rows(t, [r], client(), ALL, languages=terms)
    assert [x for x in _texts(r, "block") if x.startswith("Language")] == [
        "Language “English” is no longer in CollectionSpace’s language list. Choose another language.",
        "Language “Spanish” is no longer in CollectionSpace’s language list. Choose another language."]
    # a term renamed in CollectionSpace is still the same term
    apply_edit(t, r, {"language": [ENG.replace("(eng)'English'", "(fre)'Français'")]})
    check_rows(t, [r], client(), ALL, languages=terms)
    assert not any(x.startswith("Language") for x in _texts(r))


def test_a_language_list_that_could_not_be_read_warns(fake):
    t = load_tenant("pahma")
    r = uploaded(t, handling="mediaonly")
    calls = []

    def failing():
        calls.append(1)
        fake.fail_next["vocabularies"] = 503
        return client().vocabulary_items("languages")
    check_rows(t, [r, uploaded(t, "1-2345_1.jpg", 2, handling="mediaonly")], client(), ALL, languages=failing)
    assert "Couldn't check the language list in CollectionSpace (server)." in _texts(r, "warn")
    assert len(calls) == 1 and not any("no longer" in x for x in _texts(r))


def test_media_types_no_longer_in_the_tenants_list_block(fake):
    t = tenant_with({"mediaonly": {"type": ["slide"]}})
    r = uploaded(t, handling="mediaonly")
    check_rows(t, [r], client(), ALL)
    assert not any("Media type" in x for x in _texts(r))
    raw = pahma_raw()  # the option list changes; the row was filled before
    raw["media_types"] = ["document", "image"]
    t2 = parse_tenant(raw, "pahma")
    r["type"] = ["slide", "image"]
    r["touched"] = ["type"]
    check_rows(t2, [r], client(), ALL)
    assert [x for x in _texts(r, "block") if x.startswith("Media type")] == [
        "Media type “slide” isn’t one of PAHMA’s media types. Choose another media type."]


def test_through_the_api_while_editing_scheduling_and_in_a_queued_jobs_preview(api, login, add_uploaded, fake):
    login()
    job = new_job(api)
    n = add_uploaded(job, ["15-1234_1.jpg"])[0]["n"]
    r = api.patch(f"/api/jobs/{job}/rows/{n}", json={"handling": "mediaonly", "creator": LESLIE, "language": [ENG, SPA]}).json()["row"]
    assert not _texts(r, "block")
    fake.term_states["7475"] = "deleted"
    fake.deleted_languages.add("spa")
    appmod._VOCAB_CACHE.clear()
    s = api.post(f"/api/jobs/{job}/schedule")  # scheduling looks everything up again
    assert s.status_code == 409 and s.json()["detail"]["rows"] == [n]
    row = api.get(f"/api/jobs/{job}").json()["rows"][0]
    assert any(x.startswith("Creator “Leslie Freund” no longer exists") for x in _texts(row, "block"))
    assert any(x.startswith("Language “Spanish” is no longer") for x in _texts(row, "block"))
    # fixed, scheduled, and then deleted in CollectionSpace: the queued job's preview shows it
    api.patch(f"/api/jobs/{job}/rows/{n}", json={"creator": "", "language": [ENG]})
    assert api.post(f"/api/jobs/{job}/schedule").status_code == 200
    fake.deleted_languages.add("eng")
    appmod._VOCAB_CACHE.clear()
    preview = api.post(f"/api/jobs/{job}/check").json()
    assert preview["counts"]["block"] == 1
    assert any(x.startswith("Language “English” is no longer") for x in _texts(preview["rows"][0], "block"))
    assert api.get(f"/api/jobs/{job}").json()["job"]["status"] == "Queued"  # shown, not saved


def test_the_existing_seed_terms_still_resolve(fake):
    t = load_tenant("pahma")
    r = uploaded(t, handling="mediaonly")
    apply_edit(t, r, {"creator": LESLIE, "contributor": HEARST, "rightsHolder": NATASHA})
    check_rows(t, [r], client(), ALL, languages=lambda: client().vocabulary_items("languages"))
    assert not _texts(r, "block"), r["checks"]
    assert copy.deepcopy(r["lookups"]["term:rightsHolder"]["csids"]) == [NATASHA]


def test_preset_languages_that_no_longer_exist_say_the_preset_needs_updating(fake):
    t = tenant_with({"mediaonly": {"type": ["slide"], "language": [SPA]}})
    fake.deleted_languages.add("spa")
    r = uploaded(t, handling="mediaonly")
    check_rows(t, [r], client(), ALL, languages=lambda: client().vocabulary_items("languages"))
    assert ("Language “Spanish” is no longer in CollectionSpace’s language list. Choose another language." + PRESET_NOTE
            in _texts(r, "block"))
    # the tenant's default language is a preset only when the handling presets no language
    apply_edit(t, r, {"language": [ENG]})
    r["touched"].remove("language")
    fake.deleted_languages.add("eng")
    check_rows(t, [r], client(), ALL, languages=lambda: client().vocabulary_items("languages"))
    assert ("Language “English” is no longer in CollectionSpace’s language list. Choose another language."
            in _texts(r, "block"))


def test_a_preset_media_type_no_longer_in_the_option_list_says_the_preset_needs_updating(fake, monkeypatch):
    t = tenant_with({"mediaonly": {"type": ["slide"]}})
    r = uploaded(t, handling="mediaonly")
    assert r["type"] == ["slide"] and from_preset(t, r, "type")
    # the option list changed after the tenant loaded (monkeypatched: load-time validation would refuse the preset)
    monkeypatch.setattr(type(t), "media_type_values", property(lambda self: {"image", "document"}))
    check_rows(t, [r], client(), ALL)
    assert ("Media type “slide” isn’t one of PAHMA’s media types. Choose another media type." + PRESET_NOTE
            in _texts(r, "block"))


def test_value_checks_follow_the_mockups_order(fake, monkeypatch):
    t = load_tenant("pahma")
    fake.term_states["7475"] = "deleted"
    fake.deleted_languages.add("spa")
    r = uploaded(t, handling="mediaonly")
    apply_edit(t, r, {"creator": LESLIE, "language": [SPA], "type": ["image"]})
    monkeypatch.setattr(type(t), "media_type_values", property(lambda self: {"document"}))
    check_rows(t, [r], client(), ALL, languages=lambda: client().vocabulary_items("languages"))
    firsts = [x.split(" ")[0] for x in _texts(r, "block") if "no longer" in x or "isn’t one of" in x]
    assert firsts == ["Creator", "Language", "Media"]


def test_a_date_that_could_not_be_checked_says_it_is_checked_again_on_submit(fake):
    t = load_tenant("pahma")
    r = uploaded(t, handling="mediaonly")
    apply_edit(t, r, {"date": "1920"})
    c = client()

    def unavailable(text):
        raise CSpaceError("server", "GET structureddates returned 503")
    c.parse_date = unavailable
    check_rows(t, [r], c, ALL)
    assert "Couldn't check the date with CollectionSpace (server). It is checked again when you submit the job." in _texts(r, "block")
