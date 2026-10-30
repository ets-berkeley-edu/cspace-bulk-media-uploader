"""Submit for review (docs/testing-checklist.md section 2m): an intern sends a finished draft to staff, who review and
submit it. With the simulator's intern and admin, each in a browser of its own signed in once; the tests run in
order, building on the first draft, as the two would work.

15-1234 exists in the simulator (backend/fakecspace/app.py); 20-0777 and 20-0993 don't."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.conftest import signed_in_browser
from bmut.pages.drafts_page import DraftsPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.layout_page import LayoutPage
from bmut.pages.queue_page import QueuePage

ADMIN = ("admin", "admin")     # staff with every permission (each password is its username)
INTERN = ("intern", "intern")
NAME = "bmut for review"
# The drafts the tests made, for the tests after them.
made: dict[str, str] = {}


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


def test_submit_for_review_waits_for_what_needs_fixing(intern: WebDriver, base_url: str) -> None:
    """Section 2m, step 1: where staff have Submit job, an intern has "Submit for review…"; it is off while a
    document needs fixing, and says so. Nothing under the job name."""
    editor = EditorPage(intern, base_url)
    made["first"] = editor.make_draft(NAME, {"15-1234_1.jpg": "Found — will link", "20-0777_1.jpg": "Needs fixing"})
    assert not editor.is_enabled(editor.REVIEW)
    assert editor.title_of(editor.REVIEW).startswith("Fix or exclude the document")
    assert not editor.is_shown(editor.SUBMIT)
    assert not editor.is_shown(editor.INTERN_OPEN)
    assert not editor.is_shown(editor.REVIEW_NOTE)


@pytest.mark.after("test_submit_for_review_waits_for_what_needs_fixing")
def test_exclude_then_submit_for_review(intern: WebDriver, base_url: str) -> None:
    """Section 2m, steps 2 and 3: with the document excluded, it comes on and asks first. Confirmed, the editor
    starts a new job with a message; in Drafts the draft is first, marked "Needs review", staff only, and its Edit
    and Delete are off for the intern."""
    editor, drafts, layout = EditorPage(intern, base_url), DraftsPage(intern, base_url), LayoutPage(intern, base_url)
    editor.click(editor.exclude(2))
    editor.wait_for_text(editor.status(2), "Excluded — ignored")
    editor.wait_until_enabled(editor.REVIEW)
    editor.click(editor.REVIEW)
    editor.wait_for(editor.REVIEW_CONFIRM)
    editor.click(editor.REVIEW_CONFIRM_BTN)
    layout.wait_for_url("/job")
    assert layout.text_of(layout.NOTICE).startswith(f"“{NAME}” was sent to staff for review.")
    assert editor.value_of(editor.JOB_NAME) == ""
    drafts.open_tab()
    assert drafts.text_of(drafts.review(made["first"])).startswith("Needs review · sent by intern, ")
    assert drafts.job_ids()[0] == made["first"]
    assert drafts.text_of(drafts.access(made["first"])) == "Staff only"
    assert not drafts.is_enabled(drafts.button(made["first"], "edit"))
    assert not drafts.is_enabled(drafts.button(made["first"], "delete"))
    layout.click(layout.tab("job"))


def test_submit_for_review_from_drafts(intern: WebDriver, base_url: str) -> None:
    """Section 2m, steps 4 and 5: a document that needs an Object creator doesn't stop it (that's for staff), in the
    editor or on the draft's row in Drafts; on a draft with a document that needs fixing, the row's button is off with
    the reason."""
    editor, drafts = EditorPage(intern, base_url), DraftsPage(intern, base_url)
    creator = editor.make_draft("bmut review a creator", {"20-0993_1.jpg": "Needs fixing"})
    editor.set_handling(1, "linkorcreate", "Needs an Object creator")
    editor.wait_until_enabled(editor.REVIEW)
    editor.new_job()
    fixing = editor.make_draft("bmut review needs fixing", {"20-0777_1.jpg": "Needs fixing"})
    editor.new_job()
    drafts.open_tab()
    drafts.wait_for_checks(fixing, "1 needs fixing")
    assert not drafts.is_enabled(drafts.button(fixing, "hand-over"))
    assert drafts.title_of(drafts.button(fixing, "hand-over")).startswith("Fix or exclude the document")
    drafts.wait_until_enabled(drafts.button(creator, "hand-over"), timeout=30)
    drafts.act(creator, "hand-over", "handover")
    drafts.wait_for_text(drafts.MESSAGE, "“bmut review a creator” was sent to staff for review.")
    drafts.wait_for(drafts.review(creator))


@pytest.mark.after("test_exclude_then_submit_for_review")
def test_staff_review_the_draft(admin: WebDriver, base_url: str) -> None:
    """Section 2m, steps 6 and 7: admin's button still reads Submit job; the draft, opened with Edit, says who sent
    it and when, and the mark stays after a change."""
    drafts, editor = DraftsPage(admin, base_url), EditorPage(admin, base_url)
    drafts.open_tab()
    drafts.click(drafts.button(made["first"], "edit"))
    editor.wait_for_url(f"/job/{made['first']}")
    assert editor.text_of(editor.REVIEW_NOTE).startswith("intern sent this draft for review on ")
    assert editor.is_shown(editor.SUBMIT)
    assert not editor.is_shown(editor.REVIEW)
    editor.type(editor.JOB_NAME, f"{NAME}, reviewed")
    editor.driver.execute_script("arguments[0].blur()", editor.wait_for(editor.JOB_NAME))
    editor.wait_for_text(editor.EDITING, f"Editing draft {NAME}, reviewed.")
    editor.new_job()
    drafts.open_tab()
    drafts.wait_for_text(drafts.name(made["first"]), f"{NAME}, reviewed")
    assert drafts.text_of(drafts.review(made["first"])).startswith("Needs review · sent by intern, ")


@pytest.mark.after("test_staff_review_the_draft")
def test_open_to_interns_sends_it_back(admin: WebDriver, intern: WebDriver, base_url: str) -> None:
    """Section 2m, step 8: "Open to interns" on the row takes the mark off, and the intern can edit it again."""
    drafts, theirs = DraftsPage(admin, base_url), DraftsPage(intern, base_url)
    drafts.click(drafts.button(made["first"], "access"))
    drafts.wait_until_gone(drafts.review(made["first"]))
    drafts.wait_for_text(drafts.access(made["first"]), "Open to interns")
    theirs.open_tab()
    theirs.wait_until_enabled(theirs.button(made["first"], "edit"))


@pytest.mark.after("test_open_to_interns_sends_it_back")
def test_submit_a_reviewed_draft_and_move_it_back(admin: WebDriver, intern: WebDriver, base_url: str) -> None:
    """Section 2m, step 9: sent for review again from the intern's Drafts, admin's Submit… on the row puts it in the
    Job queue; moved back to Drafts, it has no "Needs review" mark. The queue is paused meanwhile, so the job waits
    there instead of running at once."""
    drafts, theirs, queue = DraftsPage(admin, base_url), DraftsPage(intern, base_url), QueuePage(admin, base_url)
    theirs.wait_until_enabled(theirs.button(made["first"], "hand-over"), timeout=30)
    theirs.act(made["first"], "hand-over", "handover")
    theirs.wait_for(theirs.review(made["first"]))
    queue.pause("bmut: Submit for review")
    try:
        drafts.open_tab()
        drafts.wait_for(drafts.review(made["first"]))
        drafts.wait_until_enabled(drafts.button(made["first"], "submit"), timeout=30)
        drafts.act(made["first"], "submit", "submit")
        queue.wait_for_url("/queue")
        queue.wait_for_text(queue.status(made["first"]), "Queued")
        queue.act(made["first"], "to-drafts", "todrafts")
        queue.wait_for_text(queue.MESSAGE, f"Moved “{NAME}, reviewed” to Drafts.")
        drafts.open_tab()
        drafts.wait_for(drafts.access(made["first"]))
        assert not drafts.is_shown(drafts.review(made["first"]))
    finally:
        queue.resume()
