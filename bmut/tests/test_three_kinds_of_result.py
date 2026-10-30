"""Three kinds of result (docs/testing-checklist.md section 2l, roles part 4): a document that needs a new Object,
which this user can't create, is "Needs an Object creator", not a mistake in the job; a group the account can't
create stops only Submit. With the simulator's limited (staff who can't create Objects or groups), admin and intern,
each in a browser of its own signed in once. The tests run in order, as the people would work.

20-0990 to 20-0992 are object numbers the simulator doesn't have (backend/fakecspace/app.py), so "Link to object
(create if missing)" (linkorcreate, bmu/tenants/pahma.yaml) creates them; 15-1234 exists."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.conftest import signed_in_browser
from bmut.pages.drafts_page import DraftsPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.layout_page import LayoutPage

ADMIN = ("admin", "admin")        # staff with every permission (each password is its username)
LIMITED = ("limited", "limited")  # staff who can't create Objects or groups
INTERN = ("intern", "intern")
NEEDS_CREATOR = "Needs an Object creator"  # lib/status.ts
# The drafts the tests made, for the tests after them.
made: dict[str, str] = {}


@pytest.fixture(scope="module")
def limited(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, LIMITED)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def admin(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, ADMIN)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def intern(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, INTERN)
    yield browser
    browser.quit()


def test_a_document_that_needs_an_object_creator(limited: WebDriver, base_url: str) -> None:
    """Section 2l, steps 1 to 5: set to "Link to object (create if missing)", a missing Object's document reads
    "Needs an Object creator", with one line at the top of the job and the count in the bar; Submit job is off, with
    a reason; the handling list says which option needs an Object creator; there is no way to submit the rest.
    Deleting the document from the job turns Submit job on."""
    editor = EditorPage(limited, base_url)
    editor.make_draft("bmut needs a creator", {"20-0990_1.jpg": "Needs fixing", "15-1234_1.jpg": "Found — will link"})
    editor.set_handling(1, "linkorcreate", NEEDS_CREATOR)
    note = editor.text_of(editor.CREATOR_NOTE)
    assert "1 document needs a new Object, which your account can't create" in note
    assert "Leave the draft for a colleague who can create Objects" in note
    editor.wait_for_text(editor.COUNTS, "nothing to fix · 1 needs an Object creator")
    assert not editor.is_enabled(editor.SUBMIT)
    assert editor.title_of(editor.SUBMIT)
    assert editor.handling_option(1, "create").endswith("(needs an Object creator)")
    assert "Submit without" not in editor.driver.page_source
    editor.click(editor.delete(1))
    editor.click(editor.delete_confirm(1))
    editor.wait_for_text(editor.COUNTS, "1 document")
    editor.wait_until_gone(editor.CREATOR_NOTE)
    editor.wait_until_enabled(editor.SUBMIT)
    editor.new_job()


def test_in_drafts_it_waits_for_someone_who_can_create_objects(limited: WebDriver, admin: WebDriver,
                                                               base_url: str) -> None:
    """Section 2l, step 8: limited's draft reads "nothing to fix · 1 needs an Object creator" in Drafts, and its
    Submit… is off with the reason; for admin the same draft reads "nothing to fix · 1 new Object", and Submit… is
    on."""
    editor, drafts, theirs = EditorPage(limited, base_url), DraftsPage(limited, base_url), DraftsPage(admin, base_url)
    made["creator"] = editor.make_draft("bmut for a creator", {"20-0990_1.jpg": "Needs fixing"})
    editor.set_handling(1, "linkorcreate", NEEDS_CREATOR)
    editor.new_job()
    drafts.open_tab()
    drafts.wait_for_checks(made["creator"], "nothing to fix · 1 needs an Object creator")
    submit = drafts.button(made["creator"], "submit")
    assert not drafts.is_enabled(submit)
    assert "leave the draft for a colleague who can create Objects" in drafts.title_of(submit)
    theirs.open_tab()
    theirs.wait_for_checks(made["creator"], "nothing to fix · 1 new Object")
    theirs.wait_until_enabled(theirs.button(made["creator"], "submit"))


@pytest.mark.after("test_in_drafts_it_waits_for_someone_who_can_create_objects")
def test_staff_who_can_create_objects_submit_it(admin: WebDriver, base_url: str) -> None:
    """Section 2l, step 6: admin's Submit… from the Drafts list works, and the job runs and is Completed (it creates
    Object 20-0990)."""
    drafts, layout = DraftsPage(admin, base_url), LayoutPage(admin, base_url)
    drafts.act(made["creator"], "submit", "submit")
    layout.wait_for_url("/queue")
    assert "“bmut for a creator” was submitted" in layout.text_of(layout.NOTICE)
    assert drafts.wait_for_outcome(made["creator"]) == "Completed"
    layout.click(layout.tab("job"))


def test_a_group_the_account_cant_create(limited: WebDriver, base_url: str) -> None:
    """Section 2l, steps 9 and 10: a group stops only Submit, with one message beside the group and nothing on the
    document. Unticking Group on the document clears it."""
    editor = EditorPage(limited, base_url)
    editor.make_draft("bmut group", {"15-1234_1.jpg": "Found — will link"})
    editor.click(editor.GROUP_ON)
    editor.wait_until_enabled(editor.GROUP_TITLE)  # once the server has the group on
    editor.type(editor.GROUP_TITLE, "bmut group")
    editor.driver.execute_script("arguments[0].blur()", editor.wait_for(editor.GROUP_TITLE))
    assert "Contact your CollectionSpace administrator" in editor.text_of(editor.GROUP_PROBLEM)
    assert editor.text_of(editor.status(1)) != "Needs fixing"
    editor.wait_until_enabled(editor.SUBMIT, enabled=False)
    editor.click(editor.group(1))
    editor.wait_until_gone(editor.GROUP_PROBLEM)
    editor.wait_until_enabled(editor.SUBMIT)
    editor.new_job()


def test_an_interns_document_that_needs_an_object_creator(intern: WebDriver, base_url: str) -> None:
    """Section 2l, step 11: for an intern too it reads "Needs an Object creator", and the line at the top says the
    staff member who submits must be able to create Objects."""
    editor = EditorPage(intern, base_url)
    editor.make_draft("bmut intern creator", {"20-0991_1.jpg": "Needs fixing"})
    editor.set_handling(1, "linkorcreate", NEEDS_CREATOR)
    note = editor.text_of(editor.CREATOR_NOTE)
    assert "The staff member who submits this job must be able to create Objects." in note
    editor.new_job()
