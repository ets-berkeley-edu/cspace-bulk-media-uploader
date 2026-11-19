"""Roles, the rest (docs/testing-checklist.md sections 2i, 2k and 12): Demo tools' "Sign in as" box; an intern's
term, language and date lookups through the read-only account; staff submitting an intern's draft; an intern's
Delete in a fix; a staff member without the groups permission and the bulk panel's Group list. As the simulator's
admin, intern and limited, each in a browser of its own signed in once; the Sign in as tests have browsers of their
own, since they change who is signed in."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.select import Select

from bmut.conftest import signed_in_browser
from bmut.pages.demo_page import DemoPage
from bmut.pages.drafts_page import DraftsPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.finished_page import FinishedPage
from bmut.pages.layout_page import LayoutPage

ADMIN = ("admin", "admin")  # the simulator's synthetic accounts: each password is its username
INTERN = ("intern", "intern")
LIMITED = ("limited", "limited")  # staff who can't create Objects or groups
FOUND = "Found — will link"
NO_ROLE = "doesn't have the BMU_Staff or BMU_Intern role, which the BMU needs."
RAN_DELETE_WHY = "This job has already run, so only staff can delete it."  # lib/roles.ts
# The simulator's users, as Sign in as lists them; never its read-only account, bmureader
USERS = ["admin", "limited", "intern", "newstaff", "reader"]


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


@pytest.fixture(scope="module")
def limited(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, LIMITED)
    yield browser
    browser.quit()


def sign_in_as_button(user: str) -> tuple[str, str]:
    return By.ID, f"demo-sign-in-as-{user}-btn"


def test_sign_in_as_lists_the_users_and_keeps_you_on_a_refusal(request: pytest.FixtureRequest, base_url: str) -> None:
    """Section 2i, step 1, and 2k, step 8: the Sign in as box says who you are and your role, with a button for each
    of the simulator's users but its read-only account; reader's and newstaff's buttons show the sign-in refusal and
    leave you signed in as you were."""
    browser = signed_in_browser(request.config, base_url, ADMIN)
    try:
        demo = DemoPage(browser, base_url)
        demo.open_pane()
        demo.wait_for_text((By.ID, "demo-current-user"), "You are signed in as admin (staff).")
        buttons = browser.find_elements(By.CSS_SELECTOR, "#demo-sign-in-as button[id^='demo-sign-in-as-']")
        shown = [str(b.get_attribute("id")).removeprefix("demo-sign-in-as-").removesuffix("-btn") for b in buttons]
        assert sorted(shown) == sorted(USERS)
        assert not demo.is_enabled(sign_in_as_button("admin"))  # already this user
        for user, refusal in (("reader", NO_ROLE),
                              ("newstaff", "has the BMU_Staff role, but it can't create Media records, update Media "
                                           "records or create relations.")):
            demo.click(sign_in_as_button(user))
            demo.wait_for_text(demo.ERROR, f"{user}: Your CollectionSpace account ")
            assert refusal in demo.text_of(demo.ERROR)
            assert "You are signed in as admin (staff)." in demo.text_of((By.ID, "demo-current-user"))
        browser.refresh()
        demo.open_pane()
        demo.wait_for_text((By.ID, "demo-current-user"), "You are signed in as admin (staff).")
    finally:
        browser.quit()


def test_sign_in_as_a_user_who_is_let_in(request: pytest.FixtureRequest, base_url: str) -> None:
    """Section 2i, step 2: a Sign in as button for a user who is let in reloads the app as that user, on Create /
    edit job."""
    browser = signed_in_browser(request.config, base_url, ADMIN)
    try:
        demo, layout = DemoPage(browser, base_url), LayoutPage(browser, base_url)
        layout.click(layout.tab("drafts"))
        layout.wait_for_page("Drafts")
        demo.open_pane()
        demo.click(sign_in_as_button("intern"))
        layout.wait_for_text(layout.ROLE, "Intern")
        demo.wait_for_url("/job")
        demo.open_pane()
        demo.wait_for_text((By.ID, "demo-current-user"), "You are signed in as intern (intern).")
        assert not demo.is_enabled(sign_in_as_button("intern"))
    finally:
        browser.quit()


def test_an_interns_lookups(intern: WebDriver, base_url: str) -> None:
    """Section 2k, step 6: as intern, the Creator search finds terms, the Language list fills, and 1920s gets its
    preview. The intern's own account can read nothing; the read-only account does these lookups."""
    editor = EditorPage(intern, base_url)
    editor.make_draft("bmut an intern's lookups", {"15-1240_l.jpg": FOUND})
    editor.expand(1)
    creator, first = editor.field(1, "creator"), editor.field(1, "creator-option-0")
    editor.type(creator, "Fre")
    editor.wait_for_text(first, "Leslie Freund", timeout=20)  # after the tenant's find delay
    editor.saving(lambda: editor.click(first))
    editor.wait_until(lambda d: editor.value_of(creator) == "Leslie Freund")
    languages = [str(o.text).strip() for o in Select(editor.wait_for(editor.field(1, "language-0"))).options]
    assert "Spanish" in languages and len(languages) > 2, languages
    editor.edit_text(editor.field(1, "date"), "1920s")
    note = (By.CSS_SELECTOR, "#document-1-date-container .field-note")
    editor.wait_until(lambda d: "1920" in editor.text_of(note), timeout=20)
    assert "can't" not in editor.text_of(note).lower()
    editor.new_job()


def test_staff_submit_an_interns_draft(admin: WebDriver, intern: WebDriver, base_url: str) -> None:
    """Section 2i, step 9: as admin, open the intern's draft and submit it: it runs under admin."""
    editor, finished = EditorPage(intern, base_url), FinishedPage(admin, base_url)
    job_id = editor.make_draft("bmut an intern's draft, submitted by staff", {"15-1234_s.jpg": FOUND})
    editor.new_job()
    staff = EditorPage(admin, base_url)
    staff.open(f"job/{job_id}")
    staff.wait_for(staff.EDITING)
    staff.wait_until_enabled(staff.SUBMIT, timeout=30)
    staff.click(staff.SUBMIT)
    staff.wait_for_url("/queue")
    assert finished.wait_for_outcome(job_id) == "Completed"
    row = finished.text_of(finished.job(job_id))
    assert "by admin" in row and "by intern" not in row, row


def test_an_intern_cant_delete_a_fix(admin: WebDriver, intern: WebDriver, base_url: str) -> None:
    """Section 12, step 9: as intern, in a fix open to interns with one document, Delete is off in Drafts, with the
    reason; the document's Delete in the editor is off too, and the job stays."""
    editor, demo, finished = EditorPage(admin, base_url), DemoPage(admin, base_url), FinishedPage(admin, base_url)
    job_id = editor.make_draft("bmut an intern's fix", {"16-4711_d.jpg": FOUND})
    demo.add_failure("upload", "500 server error", "16-4711_d")
    editor.wait_until_enabled(editor.SUBMIT, timeout=30)
    editor.click(editor.SUBMIT)
    editor.wait_for_url("/queue")
    assert finished.wait_for_outcome(job_id) == "Needs attention"
    finished.click(finished.button(job_id, "fix"))
    editor.wait_for_url(f"/job/{job_id}")
    editor.click(editor.INTERN_OPEN)
    editor.wait_until(lambda d: editor.wait_for(editor.INTERN_OPEN).is_selected())
    editor.new_job()

    drafts, ieditor = DraftsPage(intern, base_url), EditorPage(intern, base_url)
    drafts.open_tab()
    delete = drafts.button(job_id, "delete")
    drafts.wait_for(delete)
    assert not drafts.is_enabled(delete)
    assert drafts.title_of(delete) == RAN_DELETE_WHY
    ieditor.open(f"job/{job_id}")
    ieditor.wait_for(ieditor.EDITING)
    ieditor.expand(1)
    # The run created its Media record before the upload failed, so the row's Delete is off too (the server's
    # refusal to delete an intern's last document of a job that ran is in the backend's tests)
    assert not ieditor.is_enabled(ieditor.delete(1))
    ieditor.new_job()
    drafts.open_tab()
    drafts.wait_for(drafts.job(job_id))


def test_without_the_groups_permission_the_bulk_group_list_leaves_out(limited: WebDriver, base_url: str) -> None:
    """Section 12, step 10: as limited (no groups permission), with the job's group on, the bulk panel's Group list
    offers "No (leave out)"; "Yes" can't be chosen."""
    editor = EditorPage(limited, base_url)
    job_id = editor.make_draft("bmut no groups permission", {"15-1240_n.jpg": FOUND})
    editor.saving(lambda: editor.click(editor.GROUP_ON), path=f"/api/jobs/{job_id}")
    editor.wait_for_checks()
    editor.click(editor.field(1, "select"))
    group = Select(editor.wait_for((By.ID, "bulk-group-select")))
    options = {str(o.text).strip(): o.is_enabled() for o in group.options}
    assert options.get("No (leave out)") is True, options
    assert options.get("Yes") is False, options
    editor.new_job()
