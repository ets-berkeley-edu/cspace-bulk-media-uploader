"""Roles (docs/testing-checklist.md sections 2i, 2j and 2k: staff and interns; intern access and Submit from Drafts;
the read-only account for interns' checks), with the simulator's admin (staff) and intern side by side, each in a
browser of its own signed in once (conftest.signed_in_browser). The tests run in order and build on each other's
drafts, as two people would work. Move to Drafts is in test_drafts_and_queue.py, which holds jobs in the queue.

The files are named for the simulator's Objects (backend/fakecspace/app.py): 15-1240 and 15-1234 exist, 20-0777
doesn't, 12-2001 is sensitive and 12-2003 has a soft access note. The test stack's web app has the simulator's
read-only account (bmureader), so an intern's checks find what exists."""
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
INTERN = ("intern", "intern")  # an intern: no CollectionSpace permissions of its own
STAFF_DRAFT_WHY = "This draft is for staff only."  # lib/roles.ts
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


def test_staff_and_interns_in_the_header_and_the_job_queue(admin: WebDriver, intern: WebDriver, base_url: str) -> None:
    """Section 2i, step 5: admin has no Intern chip, and the Job queue has the schedule's controls. Step 7 and section
    2c (Job queue, last step): an intern has the chip, and in place of the controls the line that only staff can
    change the schedule."""
    for browser, staff in ((admin, True), (intern, False)):
        layout, queue = LayoutPage(browser, base_url), QueuePage(browser, base_url)
        queue.open_tab()
        queue.wait_until(lambda d: queue.is_shown(queue.SETTINGS) or queue.is_shown(queue.STAFF_ONLY))
        if staff:
            assert not layout.is_shown(layout.ROLE)
            assert queue.is_shown(queue.PAUSE)
            assert not queue.is_shown(queue.STAFF_ONLY)
        else:
            assert layout.text_of(layout.ROLE) == "Intern"
            assert queue.text_of(queue.STAFF_ONLY) == "Only staff can change the schedule or the order of the queue."
            assert not queue.is_shown(queue.SETTINGS)
        layout.click(layout.tab("job"))


def test_a_staff_draft_is_staff_only(admin: WebDriver, base_url: str) -> None:
    """Section 2i, step 6: admin's draft, closed with New job, reads "Staff only" in Drafts."""
    editor, drafts = EditorPage(admin, base_url), DraftsPage(admin, base_url)
    made["staff"] = editor.make_draft("bmut staff draft", {"15-1240.jpg": "Found — will link"})
    editor.new_job()
    drafts.open_tab()
    drafts.wait_for_text(drafts.access(made["staff"]), "Staff only")


def test_an_interns_draft(intern: WebDriver, base_url: str) -> None:
    """Section 2i, steps 7 and 9; 2k, step 1; 2l (an intern's 15-1234_1.jpg): the intern's own draft is found with
    no permission problem held against the intern's account. The editor has Submit for review, not Submit job. In
    Drafts it reads "Open to interns", and its Edit and Delete are on."""
    editor, drafts = EditorPage(intern, base_url), DraftsPage(intern, base_url)
    made["intern"] = editor.make_draft("bmut intern draft", {"15-1234_1.jpg": "Found — will link"})
    checks = " ".join(editor.checks_of(1))
    for problem in ("can't read", "can't update", "can't create", "Must fix"):
        assert problem not in checks
    assert editor.is_shown(editor.REVIEW)
    assert not editor.is_shown(editor.SUBMIT)
    editor.new_job()
    drafts.open_tab()
    drafts.wait_for_text(drafts.access(made["intern"]), "Open to interns")
    assert drafts.is_enabled(drafts.button(made["intern"], "edit"))
    assert drafts.is_enabled(drafts.button(made["intern"], "delete"))
    drafts.click(drafts.button(made["intern"], "edit"))
    editor.wait_for_url(f"/job/{made['intern']}")
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == "bmut intern draft")
    editor.new_job()


@pytest.mark.after("test_a_staff_draft_is_staff_only")
def test_a_staff_draft_is_off_for_an_intern(intern: WebDriver, base_url: str) -> None:
    """Section 2i, step 8: Edit and Delete on admin's draft are off, and say why."""
    drafts = DraftsPage(intern, base_url)
    drafts.open_tab()
    for action in ("edit", "delete"):
        button = drafts.button(made["staff"], action)
        assert not drafts.is_enabled(button), action
        assert drafts.title_of(button) == STAFF_DRAFT_WHY


@pytest.mark.after("test_a_staff_draft_is_off_for_an_intern")
def test_open_to_interns_from_drafts(admin: WebDriver, intern: WebDriver, base_url: str) -> None:
    """Section 2j, step 4: "Open to interns" on the draft's row changes the line under its name, a message says so,
    and the intern's Edit comes on. "Make staff only" changes it back."""
    drafts, theirs = DraftsPage(admin, base_url), DraftsPage(intern, base_url)
    drafts.open_tab()
    drafts.click(drafts.button(made["staff"], "access"))
    drafts.wait_for_text(drafts.MESSAGE, "“bmut staff draft” is now open to interns.")
    drafts.wait_for_text(drafts.access(made["staff"]), "Open to interns")
    theirs.open_tab()
    theirs.wait_until_enabled(theirs.button(made["staff"], "edit"))
    drafts.click(drafts.button(made["staff"], "access"))
    drafts.wait_for_text(drafts.MESSAGE, "“bmut staff draft” is now staff only.")
    drafts.wait_for_text(drafts.access(made["staff"]), "Staff only")
    theirs.open_tab()
    theirs.wait_until_enabled(theirs.button(made["staff"], "edit"), enabled=False)


@pytest.mark.after("test_open_to_interns_from_drafts")
def test_open_to_interns_in_the_editor(admin: WebDriver, base_url: str) -> None:
    """Section 2j, step 5: the "Open to interns" checkbox under the job name does the same."""
    drafts, editor, layout = DraftsPage(admin, base_url), EditorPage(admin, base_url), LayoutPage(admin, base_url)
    drafts.open_tab()
    drafts.click(drafts.button(made["staff"], "edit"))
    editor.wait_for_url(f"/job/{made['staff']}")
    for ticked, label in ((True, "Open to interns"), (False, "Staff only")):
        editor.click(editor.INTERN_OPEN)
        editor.wait_until(lambda d: editor.wait_for(editor.INTERN_OPEN).is_selected() == ticked)
        drafts.open_tab()
        drafts.wait_for_text(drafts.access(made["staff"]), label)
        layout.click(layout.tab("job"))
        editor.wait_for_url(f"/job/{made['staff']}")
    editor.new_job()


@pytest.mark.after("test_open_to_interns_in_the_editor")
def test_submit_from_drafts(admin: WebDriver, base_url: str) -> None:
    """Section 2j, steps 1 and 2: Submit… on a draft with nothing to fix asks first, naming the document count, who
    created the draft and whose sign-in it runs with; Cancel changes nothing. Confirmed, it lands in the Job queue
    with the usual message."""
    drafts, layout = DraftsPage(admin, base_url), LayoutPage(admin, base_url)
    drafts.open_tab()
    submit = drafts.button(made["staff"], "submit")
    drafts.wait_until_enabled(submit, timeout=30)
    drafts.click(submit)
    text = drafts.text_of(drafts.confirm(made["staff"], "submit"))
    for words in ("Submit “bmut staff draft”?", "It has 1 document.", "Created by admin (staff)",
                  "with your sign-in"):
        assert words in text
    drafts.click(drafts.cancel_button(made["staff"], "submit"))
    drafts.wait_until_gone(drafts.confirm(made["staff"], "submit"))
    drafts.act(made["staff"], "submit", "submit")
    layout.wait_for_url("/queue")
    assert "“bmut staff draft” was submitted" in layout.text_of(layout.NOTICE)


def test_submit_from_drafts_is_off_when_a_document_needs_fixing(admin: WebDriver, base_url: str) -> None:
    """Section 2j, step 3: the tooltip says to open the draft with Edit."""
    editor, drafts = EditorPage(admin, base_url), DraftsPage(admin, base_url)
    job_id = editor.make_draft("bmut needs fixing", {"20-0777_1.jpg": "Needs fixing"})
    editor.new_job()
    drafts.open_tab()
    drafts.wait_for_checks(job_id, "1 needs fixing")
    submit = drafts.button(job_id, "submit")
    assert not drafts.is_enabled(submit)
    assert drafts.title_of(submit).endswith("open the draft with Edit")


def test_an_interns_checks_use_the_read_only_account(intern: WebDriver, base_url: str) -> None:
    """Section 2k, steps 2 to 4: a missing Object is a real finding; a sensitive Object's file is protected, with a
    reason that doesn't say why; a soft access note is a warning that doesn't say what kind."""
    editor = EditorPage(intern, base_url)
    made["checks"] = editor.make_draft("bmut intern checks", {"20-0777_1.jpg": "Needs fixing",
                                                              "12-2001_1.jpg": "Found — will link",
                                                              "12-2003_1.jpg": "Found — will link"})
    assert "Must fix: No object 20-0777 in CollectionSpace." in " ".join(editor.checks_of(1))
    reason = editor.protected_reason(2)
    assert reason == "marked sensitive in CollectionSpace"
    assert "Object 12-2003 has a note about access in CollectionSpace" in " ".join(editor.checks_of(3))
    for hidden in ("Human Remains", "culturally", "publication restriction", "preference"):
        assert hidden not in reason + " ".join(editor.checks_of(3))
    editor.new_job()


@pytest.mark.after("test_an_interns_checks_use_the_read_only_account")
def test_staff_see_the_full_reasons(admin: WebDriver, base_url: str) -> None:
    """Section 2k, step 5: the same draft, opened by admin, has the full reasons."""
    drafts, editor = DraftsPage(admin, base_url), EditorPage(admin, base_url)
    drafts.open_tab()
    drafts.click(drafts.button(made["checks"], "edit"))
    editor.wait_for_url(f"/job/{made['checks']}")
    editor.wait_for_text(editor.COUNTS, "3 documents")
    assert editor.protected_reason(2) == "culturally sensitive object in the Human Remains department"
    assert "Object 12-2003 has a display or publication restriction at the preference or recommendation level" in \
        " ".join(editor.checks_of(3))
    editor.new_job()
