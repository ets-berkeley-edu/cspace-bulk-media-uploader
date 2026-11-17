"""Drafts and their addresses (docs/testing-checklist.md sections 2, 2b, 2j and 12): who has a draft open after New
job, Back and sign-out; a deleted draft's old address; Delete selected while it works; a change refused after a
take-over, and an intern's change refused once the draft is staff only. As the simulator's admin, a second admin
session and intern, each in a browser of its own signed in once; the sign-out test has a browser of its own."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.conftest import signed_in_browser
from bmut.pages.drafts_page import DraftsPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.layout_page import LayoutPage
from bmut.pages.sign_in_page import SignInPage

ADMIN = ("admin", "admin")  # the simulator's synthetic accounts: each password is its username
LIMITED = ("limited", "limited")
INTERN = ("intern", "intern")
FOUND = "Found — will link"


@pytest.fixture(scope="module")
def admin(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, ADMIN)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def admin2(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    """admin again, in a session of its own."""
    browser = signed_in_browser(request.config, base_url, ADMIN)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def intern(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, INTERN)
    yield browser
    browser.quit()


def open_in_drafts(drafts: DraftsPage, job_id: str) -> None:
    drafts.open_tab()
    drafts.wait_for(drafts.job(job_id))


def test_new_job_releases_the_draft_and_back_reopens_it(admin: WebDriver, base_url: str) -> None:
    """Section 2, Tabs, step 7: New job while a draft is open gives an empty editor, and in Drafts the draft is no
    longer shown as being edited by you. Section 2b, step 4: then the browser's Back button reopens the draft."""
    editor, drafts = EditorPage(admin, base_url), DraftsPage(admin, base_url)
    name = "bmut new job and back"
    job_id = editor.make_draft(name, {"3-1001_n.jpg": FOUND})
    open_in_drafts(drafts, job_id)
    assert drafts.text_of(drafts.editing(job_id)) == "You"
    LayoutPage(admin, base_url).click(LayoutPage.tab("job"))
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == name)
    editor.new_job()
    open_in_drafts(drafts, job_id)
    assert not drafts.is_shown(drafts.editing(job_id))

    admin.back()  # Drafts → the empty editor
    editor.wait_for_url("/job")
    admin.back()  # → the draft
    editor.wait_for_url(f"/job/{job_id}")
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == name)
    editor.wait_for(editor.EDITING)
    editor.new_job()


def test_a_deleted_drafts_old_address(admin: WebDriver, base_url: str) -> None:
    """Section 2b, step 5: delete a draft from Drafts, then open its old address: a message that the job isn't there,
    and a new, empty job."""
    editor, drafts, layout = EditorPage(admin, base_url), DraftsPage(admin, base_url), LayoutPage(admin, base_url)
    job_id = editor.make_draft("bmut deleted address", {"3-1002_n.jpg": FOUND})
    editor.new_job()
    open_in_drafts(drafts, job_id)
    drafts.act(job_id, "delete", "delete")
    drafts.wait_until_gone(drafts.job(job_id))
    editor.open(f"job/{job_id}")
    layout.wait_for_text(layout.NOTICE, "The job at that address isn't there")
    editor.wait_for_url("/job")
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == "")


def test_delete_selected_while_it_works(admin: WebDriver, base_url: str) -> None:
    """Section 2b, step 6: Delete selected on three documents: each row reads "Deleting…" and is dimmed, and so does
    the button, until they disappear. Chrome slows the requests down so the test sees it."""
    editor = EditorPage(admin, base_url)
    editor.make_draft("bmut deleting", {"3-1001_s.jpg": FOUND, "3-1002_s.jpg": FOUND, "12-5678_s.jpg": FOUND,
                                        "15-1240_s.jpg": FOUND})
    editor.wait_for_checks()
    for n in (1, 2, 3):
        editor.click(editor.field(n, "select"))
    editor.click(editor.BULK_DELETE)
    editor.wait_for(editor.BULK_DELETE_CONFIRM)
    admin.set_network_conditions(offline=False, latency=3000, download_throughput=500 * 1024,
                                 upload_throughput=500 * 1024)
    try:
        editor.click(editor.BULK_DELETE_CONFIRM_BTN)
        editor.wait_for_text(editor.BULK_DELETE, "Deleting…")
        for n in (1, 2, 3):
            assert editor.text_of(editor.status(n)) == "Deleting…"
            row = admin.find_element(*editor.field(n, "file")).find_element("xpath", "ancestor::tr[1]")
            assert "row-deleting" in str(row.get_attribute("class"))
        assert editor.text_of(editor.status(4)) == FOUND
    finally:
        admin.delete_network_conditions()
    for n in (1, 2, 3):
        editor.wait_until_gone(editor.field(n, "file"), timeout=20)
    editor.wait_for_text(editor.COUNTS, "1 document ")
    editor.wait_for_text(editor.BULK_DELETE, "Delete selected")
    editor.new_job()


def test_after_a_take_over_the_first_sessions_change_is_refused(admin: WebDriver, admin2: WebDriver,
                                                                base_url: str) -> None:
    """Section 12, step 2: two browsers, the same draft: take it over in the second, then change a field in the
    first. The first shows that it's no longer editing; the field isn't changed for the second."""
    editor, editor2 = EditorPage(admin, base_url), EditorPage(admin2, base_url)
    job_id = editor.make_draft("bmut taken over", {"16-4711_t.jpg": FOUND})
    editor.expand(1)
    editor.edit_text(editor.field(1, "description"), "bmut: before")
    editor2.open(f"job/{job_id}")
    editor2.click(editor2.TAKE_OVER)
    editor2.click(editor2.TAKE_OVER_CONFIRM_BTN)
    editor2.wait_until_gone(editor2.LOCKED)
    editor2.wait_for(editor2.EDITING)

    editor.edit_text(editor.field(1, "description"), "bmut: after the take-over")
    editor.wait_for_text(editor.MESSAGE, "admin is editing this draft now, so your change wasn't saved")
    editor.wait_for(editor.LOCKED)

    admin2.refresh()
    editor2.wait_for(editor2.EDITING)
    editor2.expand(1)
    assert editor2.value_of(editor2.field(1, "description")) == "bmut: before"
    editor2.new_job()
    editor.new_job()


def test_sign_out_releases_the_draft(request: pytest.FixtureRequest, base_url: str) -> None:
    """Section 2, Sign-in, step 6: open a draft, sign out, and sign in as a different user: that user edits the
    draft without Take over."""
    browser = signed_in_browser(request.config, base_url, ADMIN)
    try:
        editor, layout = EditorPage(browser, base_url), LayoutPage(browser, base_url)
        job_id = editor.make_draft("bmut sign out", {"1-2345_o.jpg": FOUND})
        layout.sign_out()
        SignInPage(browser, base_url).sign_in(*LIMITED)
        layout.wait_for(layout.TENANT)
        editor.open(f"job/{job_id}")
        editor.wait_for(editor.EDITING)
        assert not editor.is_shown(editor.LOCKED)
        assert editor.is_enabled(editor.JOB_NAME)
        editor.new_job()
    finally:
        browser.quit()


def test_an_interns_change_after_the_draft_is_made_staff_only(admin: WebDriver, intern: WebDriver,
                                                              base_url: str) -> None:
    """Section 2j, step 6: an intern has a draft open to interns open; staff make it staff only; the intern's next
    change is refused, and the page becomes read-only."""
    editor, drafts = EditorPage(intern, base_url), DraftsPage(admin, base_url)
    job_id = editor.make_draft("bmut made staff only", {"15-1234_i.jpg": FOUND})
    open_in_drafts(drafts, job_id)
    assert drafts.text_of(drafts.access(job_id)) == "Open to interns"
    drafts.click(drafts.button(job_id, "access"))
    drafts.wait_for_text(drafts.MESSAGE, "is now staff only.")

    editor.expand(1)
    description = editor.field(1, "description")
    editor.edit_text(description, "bmut: an intern's change")
    # Making it staff only ended the intern's editing (app.py: intern_access), so the change is refused, with that
    # reason, and the page becomes read-only.
    editor.wait_for_text(editor.MESSAGE, "This draft is for staff only now, so an intern can't edit it")
    editor.wait_until_enabled(description, enabled=False)
    editor.new_job()
