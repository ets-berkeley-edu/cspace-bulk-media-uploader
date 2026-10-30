"""Create / edit job (docs/testing-checklist.md section 2a): editing each kind of field, handling, Restricted and
Exclude, deleting a document, "Change selected documents", sorting, paging and the Show filter, a group, a failed
upload and Retry, and the locked banner with Take over. As the simulator's admin, with a second admin session (a
browser of its own) for a draft someone else is editing. The tests run in order; each makes its own draft.

The files are named for the simulator's sample Objects (backend/fakecspace/app.py), so their documents are found
and link; 20-0994 is an object number it doesn't have. Replace file, the other half of 2a's failed-upload step, needs
a run that failed: test_finished_jobs.py has it."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.select import Select

from bmut.conftest import signed_in_browser
from bmut.files import jpeg
from bmut.pages.editor_page import EditorPage
from bmut.pages.layout_page import LayoutPage
from bmut.pages.queue_page import QueuePage

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
FOUND = "Found — will link"
# Where the test stack's browser uploads go (./bmu: BMU_S3_PORT for the test stack; docker-compose.yml)
S3_UPLOADS = "http://localhost:9500/*"
# The draft the first test made, for the tests after it.
made: dict[str, str] = {}


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


def test_edit_each_kind_of_field_and_reload(admin: WebDriver, base_url: str) -> None:
    """Section 2a, step 3 (and 2b, step 1): filename, identification and object number with "Use parsed value",
    date, media type with "Add an additional type", creator picked with the mouse and contributor with the arrow keys,
    description and language. After a reload the draft is open again with every edit."""
    editor = EditorPage(admin, base_url)
    made["fields"] = job_id = editor.make_draft("bmut fields", {"12-5678_a.jpg": FOUND})
    editor.expand(1)
    editor.edit_text(editor.field(1, "filename"), "12-5678_b.jpg")
    editor.wait_for_text(editor.field(1, "file"), "12-5678_b.jpg")
    editor.edit_text(editor.field(1, "idnum"), "12-5678 bmut")
    editor.saving(lambda: editor.click(editor.field(1, "idnum-parsed-btn")))
    editor.wait_until(lambda d: editor.value_of(editor.field(1, "idnum")) == "12-5678")
    editor.edit_text(editor.field(1, "obj"), "15-1240")
    editor.wait_for_text(editor.status(1), FOUND, timeout=30)
    editor.saving(lambda: editor.click(editor.field(1, "obj-parsed-btn")))
    editor.wait_until(lambda d: editor.value_of(editor.field(1, "obj")) == "12-5678")
    editor.edit_text(editor.field(1, "date"), "1920s")
    editor.choose(editor.field(1, "type-0"), "image")
    editor.click(editor.field(1, "type-add-btn"))
    editor.choose(editor.field(1, "type-1"), "slide")
    pick_term(editor, "creator", "Fre", "Leslie Freund", keys=False)
    pick_term(editor, "contributor", "Nat", "Natasha Johnson", keys=True)
    editor.edit_text(editor.field(1, "description"), "bmut: a description")
    editor.choose(editor.field(1, "language-0"), "Spanish")

    admin.refresh()
    editor.wait_for_url(f"/job/{job_id}")
    editor.wait_for_text(editor.COUNTS, "1 document")
    editor.expand(1)
    assert editor.text_of(editor.field(1, "file")) == "12-5678_b.jpg"
    expected = {"idnum": "12-5678", "obj": "12-5678", "date": "1920s", "creator": "Leslie Freund",
                "contributor": "Natasha Johnson", "description": "bmut: a description"}
    assert {name: editor.value_of(editor.field(1, name)) for name in expected} == expected
    assert [editor.selected_label(editor.field(1, name)) for name in ("type-0", "type-1", "language-0")] == [
        "image", "slide", "Spanish"]


def pick_term(editor: EditorPage, field: str, typed: str, term: str, keys: bool) -> None:
    """Types the start of a term in the document's authority field and picks it from the list: with the arrow keys
    and Enter, or with the mouse."""
    locator, first = editor.field(1, field), editor.field(1, f"{field}-option-0")
    editor.type(locator, typed)
    editor.wait_for_text(first, term, timeout=20)  # after the tenant's find delay
    if keys:
        editor.saving(lambda: editor.wait_for(locator).send_keys(Keys.ARROW_DOWN, Keys.ENTER))
    else:
        editor.saving(lambda: editor.click(first))
    editor.wait_until(lambda d: editor.value_of(locator) == term)


@pytest.mark.after("test_edit_each_kind_of_field_and_reload")
def test_handling_restricted_and_exclude(admin: WebDriver, base_url: str) -> None:
    """Section 2a, step 4: a document's handling, Restricted and Exclude change its status chip and the Public portal
    column."""
    editor = EditorPage(admin, base_url)
    editor.open(f"job/{made['fields']}")
    editor.wait_for_text(editor.status(1), FOUND, timeout=30)
    portal = editor.field(1, "portal")
    assert editor.text_of(portal) == "Public"
    editor.tick(editor.field(1, "restricted"), True)
    editor.wait_for_text(portal, "Hidden: image restricted")
    editor.tick(editor.field(1, "restricted"), False)
    editor.wait_for_text(portal, "Public")
    for handling, status in (("mediaonly", "Not linked"), ("create", "Needs fixing"), ("link", FOUND)):
        editor.set_handling(1, handling, status)  # "Create new object" can't make an object that exists
    editor.tick(editor.exclude(1), True)
    editor.wait_for_text(editor.status(1), "Excluded — ignored")
    editor.wait_for_text(editor.COUNTS, "(1 excluded)")
    assert not editor.is_enabled(editor.field(1, "restricted"))
    editor.tick(editor.exclude(1), False)
    editor.wait_for_text(editor.status(1), FOUND, timeout=30)


@pytest.mark.after("test_edit_each_kind_of_field_and_reload")
def test_delete_a_document(admin: WebDriver, base_url: str) -> None:
    """Section 2a, step 5: the trash can opens the confirmation under the row; Cancel closes it, Delete removes the
    document."""
    editor = EditorPage(admin, base_url)
    editor.open(f"job/{made['fields']}")
    editor.wait_for_text(editor.COUNTS, "1 document")
    editor.add_file("1-2345_a.jpg", FOUND)
    editor.wait_for_text(editor.COUNTS, "2 documents")
    editor.click(editor.delete(2))
    assert "nothing in CollectionSpace is touched" in editor.text_of((By.CSS_SELECTOR, "#document-2 .del-confirm"))
    editor.click(editor.field(2, "delete-cancel-btn"))
    editor.wait_until_gone(editor.delete_confirm(2))
    editor.click(editor.delete(2))
    editor.click(editor.delete_confirm(2))
    editor.wait_until_gone(editor.field(2, "file"))
    editor.wait_for_text(editor.COUNTS, "1 document ")
    editor.new_job()


def test_change_selected_documents(admin: WebDriver, base_url: str) -> None:
    """Section 2a, step 6: in "Change selected documents", Apply to selected, Apply to all, Exclude selected, Include
    selected and Delete selected (with its confirmation). Apply to all applies at once: it has no confirmation."""
    editor = EditorPage(admin, base_url)
    editor.make_draft("bmut bulk", {"3-1001_b.jpg": FOUND, "3-1002_b.jpg": FOUND, "16-4711_b.jpg": FOUND})

    def handling(n: int) -> str:
        return str(Select(editor.wait_for(editor.handling(n))).first_selected_option.get_attribute("value"))

    for n in (1, 2):
        editor.click(editor.field(n, "select"))
    Select(editor.wait_for(editor.BULK_HANDLING)).select_by_value("linkorcreate")
    editor.saving(lambda: editor.click(editor.BULK_APPLY_SELECTED))
    editor.wait_until(lambda d: [handling(n) for n in (1, 2, 3)] == ["linkorcreate", "linkorcreate", "link"])
    editor.click(editor.CLEAR_SELECTION)
    Select(editor.wait_for(editor.BULK_PUBLISH)).select_by_value("yes")
    editor.saving(lambda: editor.click(editor.BULK_APPLY_ALL))
    editor.wait_until(lambda d: all(d.find_element(*editor.field(n, "restricted")).is_selected() for n in (1, 2, 3)))
    editor.click(editor.field(3, "select"))
    editor.saving(lambda: editor.click(editor.BULK_EXCLUDE))
    editor.wait_for_text(editor.status(3), "Excluded — ignored")
    editor.saving(lambda: editor.click(editor.BULK_INCLUDE))
    editor.wait_until(lambda d: not d.find_element(*editor.exclude(3)).is_selected())
    editor.click(editor.field(1, "select"))
    editor.click(editor.BULK_DELETE)
    assert "Delete 2 selected documents" in editor.text_of(editor.BULK_DELETE_CONFIRM)
    editor.click(editor.BULK_DELETE_CONFIRM_BTN)
    editor.wait_until_gone(editor.field(3, "file"))
    editor.wait_until_gone(editor.field(1, "file"))
    editor.wait_for_text(editor.COUNTS, "1 document ")
    assert editor.text_of(editor.field(2, "file")) == "3-1002_b.jpg"
    editor.new_job()


def test_sort_page_and_show_problems(admin: WebDriver, base_url: str) -> None:
    """Section 2a, step 7: every column sorts (ascending, descending, then not at all), and by Document in name
    order; next page and page size; "Show documents with problems" shows only the document that needs fixing."""
    editor = EditorPage(admin, base_url)
    editor.new_job()
    LayoutPage(admin, base_url).wait_for_page("Create / edit job")
    editor.name_new_job("bmut paging")
    names = [f"12-5678_{i:02}.jpg" for i in range(1, 27)] + ["20-0994_1.jpg"]
    editor.choose_files(editor.FILE_INPUT, [jpeg(name) for name in names])
    editor.wait_for_text(editor.COUNTS, "27 documents · 1 needs fixing", timeout=120)
    editor.wait_for_text(editor.PAGE_COUNT, "1–25 of 27 documents")
    for column in ("file", "handling", "publish", "portal", "status", "include"):
        heading = (By.XPATH, f"//th[.//*[@id='sort-col-{column}-btn']]")
        for order in ("ascending", "descending", "none"):
            editor.click(by_sort(column))
            editor.wait_until(lambda d: d.find_element(*heading).get_attribute("aria-sort") == order)
            if column == "file" and order != "none":
                shown = editor.files_shown()
                assert shown == sorted(shown, reverse=order == "descending")
                assert shown[0] == ("12-5678_01.jpg" if order == "ascending" else "20-0994_1.jpg")
    editor.click(editor.NEXT_PAGE)
    editor.wait_for_text(editor.PAGE_COUNT, "26–27 of 27 documents")
    Select(editor.wait_for(editor.PAGE_SIZE)).select_by_value("50")
    editor.wait_for_text(editor.PAGE_COUNT, "1–27 of 27 documents")
    editor.click(editor.SHOW_PROBLEMS)
    editor.wait_until(lambda d: editor.value_of(editor.FILTER) == "problems")
    editor.wait_until(lambda d: "20-0994_1.jpg" in editor.files_shown())
    assert all(editor.text_of(editor.status(n)) != "Needs fixing" for n in range(1, 27)
               if editor.is_shown(editor.status(n)))
    Select(editor.wait_for(editor.FILTER)).select_by_value("block")
    editor.wait_until(lambda d: editor.files_shown() == ["20-0994_1.jpg"])
    assert "(filtered from 27)" in editor.text_of(editor.PAGE_COUNT)
    editor.new_job()


def by_sort(column: str) -> tuple[str, str]:
    return (By.ID, f"sort-col-{column}-btn")


def test_a_group(admin: WebDriver, base_url: str) -> None:
    """Section 2a, step 9: "Create a group" adds the Group column with each linked document in it; Submit waits for a
    title; a document's Group box takes it out and puts it back. Submitted, the job completes and its results name
    the group it created."""
    editor, queue = EditorPage(admin, base_url), QueuePage(admin, base_url)
    job_id = editor.make_draft("bmut group", {"15-1240_g.jpg": FOUND, "1-2345_g.jpg": FOUND})
    editor.saving(lambda: editor.click(editor.GROUP_ON), path=f"/api/jobs/{job_id}")
    for n in (1, 2):
        editor.wait_until(lambda d, n=n: d.find_element(*editor.group(n)).is_selected())
    editor.wait_until_enabled(editor.SUBMIT, False)
    assert editor.title_of((By.XPATH, "//span[.//*[@id='submit-job-btn']]")).startswith("Enter a group title")
    editor.saving(lambda: (editor.type(editor.GROUP_TITLE, "bmut group title"),
                           admin.execute_script("arguments[0].blur()", editor.wait_for(editor.GROUP_TITLE))),
                  path=f"/api/jobs/{job_id}")
    editor.tick(editor.group(2), False)
    editor.tick(editor.group(2), True)
    editor.wait_until_enabled(editor.SUBMIT, timeout=30)
    editor.click(editor.SUBMIT)
    queue.wait_for_url("/queue")
    assert queue.wait_for_outcome(job_id) == "Completed"
    queue.click(queue.button(job_id, "view-results"))
    assert "created in run 1" in queue.text_of((By.ID, "results-group"))


def test_a_failed_upload_and_retry(admin: WebDriver, base_url: str) -> None:
    """Section 2a, step 10, Retry: an upload that fails shows "Upload failed" with Retry, and Retry sends the file
    again. To make it fail, the browser is kept from reaching the stack's S3 (Chrome's own blocking of addresses):
    Demo tools only slow browser uploads down."""
    editor = EditorPage(admin, base_url)
    editor.make_draft("bmut retry", {})
    admin.execute_cdp_cmd("Network.enable", {})
    admin.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [S3_UPLOADS]})
    try:
        editor.add_file("16-4711_r.jpg", "Upload failed")
        editor.wait_for(editor.field(1, "retry-btn"))
    finally:
        admin.execute_cdp_cmd("Network.setBlockedURLs", {"urls": []})
    editor.click(editor.field(1, "retry-btn"))
    editor.wait_for_text(editor.status(1), FOUND, timeout=60)
    assert not editor.is_shown(editor.field(1, "retry-btn"))
    editor.new_job()


def test_locked_banner_and_take_over(admin: WebDriver, admin2: WebDriver, base_url: str) -> None:
    """Section 2a, step 11: a draft someone else is editing opens with the locked banner; Take over asks first, then
    opens it for editing. The first session's editor becomes read-only at its next change."""
    editor, editor2 = EditorPage(admin, base_url), EditorPage(admin2, base_url)
    job_id = editor.make_draft("bmut locked", {"3-1001_l.jpg": FOUND})
    editor2.open(f"job/{job_id}")
    assert "admin" in editor2.text_of(editor2.LOCKED)
    assert not editor2.is_enabled(editor2.JOB_NAME)  # a read-only preview
    editor2.click(editor2.TAKE_OVER)
    editor2.wait_for(editor2.TAKE_OVER_CONFIRM)
    editor2.click(editor2.TAKE_OVER_CONFIRM_BTN)
    editor2.wait_until_gone(editor2.LOCKED)
    editor2.wait_for(editor2.EDITING)
    editor2.wait_until_enabled(editor2.SUBMIT, timeout=30)
    editor.type(editor.JOB_NAME, "bmut locked, changed")  # the server refuses the change, and the page finds out
    admin.execute_script("arguments[0].blur()", editor.wait_for(editor.JOB_NAME))
    editor.wait_for(editor.LOCKED)
    editor2.new_job()
    editor.new_job()
