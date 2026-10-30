"""Drafts and Job queue (docs/testing-checklist.md section 2c), with Move to Drafts (2j) and what an intern may do in
the queue (2i, 2j). With the simulator's admin, a second admin session (two browsers signed in as the same user each
have their own session, so the second finds the first's draft held) and intern, each in a browser of its own signed
in once. The tests run in order and build on each other's jobs.

Every moment is a run time on the test stack, so the queue tests pause the queue first (the paused fixture) and
resume it at the end; their jobs then run. Each job's files are named for different sample Objects
(backend/fakecspace/app.py), so no two queued jobs share an Object and nothing asks before a move."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.conftest import signed_in_browser
from bmut.pages.drafts_page import DraftsPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.layout_page import LayoutPage
from bmut.pages.queue_page import QueuePage

ADMIN = ("admin", "admin")     # staff with every permission (each password is its username)
INTERN = ("intern", "intern")
STAFF_ONLY_WHY = "Only staff can do this."  # lib/roles.ts
NAME = "bmut drafts list"
# The jobs the tests made, for the tests after them.
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


@pytest.fixture(scope="module")
def intern(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, INTERN)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def paused(admin: WebDriver, base_url: str) -> Iterator[None]:
    """The queue paused, from the first test that asks for it to the end of the file."""
    queue = QueuePage(admin, base_url)
    queue.pause("bmut: Drafts and Job queue")
    yield
    queue.resume()


def test_a_drafts_line_details_and_preview(admin: WebDriver, base_url: str) -> None:
    """Section 2c, Drafts, steps 1 and 5: the draft's line shows its checks, who is editing and when it expires.
    Expanded, its facts appear; "Open full preview" opens the preview, where Check again and Back to Drafts work,
    and Continue editing opens Create / edit job."""
    editor, drafts = EditorPage(admin, base_url), DraftsPage(admin, base_url)
    made["draft"] = job_id = editor.make_draft(NAME, {"15-1240.jpg": "Found — will link",
                                                      "1-2345.jpg": "Found — will link"})
    drafts.open_tab()
    drafts.wait_for_checks(job_id, "nothing to fix")
    assert drafts.text_of(drafts.editing(job_id)) == "You"
    assert drafts.text_of(drafts.expires(job_id)).endswith("days)")
    toggle = drafts.button(job_id, "toggle")
    drafts.click(toggle)
    drafts.wait_for(drafts.details(job_id))
    assert drafts.wait_for(toggle).get_attribute("aria-expanded") == "true"
    drafts.click(drafts.button(job_id, "full-preview"))
    drafts.wait_for_text(drafts.PREVIEW_TITLE, NAME)
    drafts.click(drafts.PREVIEW_CHECK_AGAIN)
    drafts.wait_until_enabled(drafts.PREVIEW_CHECK_AGAIN)
    assert drafts.text_of(drafts.PREVIEW_BACK).endswith("Back to Drafts")
    drafts.click(drafts.PREVIEW_BACK)
    drafts.wait_for_text(drafts.name(job_id), NAME)
    drafts.click(drafts.button(job_id, "toggle"))
    drafts.click(drafts.button(job_id, "full-preview"))
    drafts.wait_for(drafts.PREVIEW_TITLE)
    drafts.click(drafts.button(job_id, "edit"))  # "Continue editing": the draft is open in this browser
    editor.wait_for_url(f"/job/{job_id}")
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == NAME)


@pytest.mark.after("test_a_drafts_line_details_and_preview")
def test_expand_all_collapse_all_and_sort(admin: WebDriver, base_url: str) -> None:
    """Section 2c, Drafts, step 2: Expand all and Collapse all; a column heading sorts ascending, descending, then
    not at all."""
    drafts = DraftsPage(admin, base_url)
    drafts.open_tab()
    toggle = drafts.button(made["draft"], "toggle")
    for button, expanded in ((drafts.EXPAND_ALL, "true"), (drafts.COLLAPSE_ALL, "false")):
        drafts.click(button)
        drafts.wait_until(lambda d: d.find_element(*toggle).get_attribute("aria-expanded") == expanded)
    heading = (By.XPATH, "//th[.//*[@id='drafts-sort-col-name-btn']]")
    for order in ("ascending", "descending", "none"):
        drafts.click(drafts.sort("name"))
        drafts.wait_until(lambda d: d.find_element(*heading).get_attribute("aria-sort") == order)


@pytest.mark.after("test_a_drafts_line_details_and_preview")
def test_take_over_a_draft(admin: WebDriver, admin2: WebDriver, base_url: str) -> None:
    """Section 2c, Drafts, step 4: in another session, the draft the first is editing has Take over…, which warns
    first; Take over and edit opens it. The first session's editor becomes a read-only preview at its next change."""
    theirs, editor2 = DraftsPage(admin2, base_url), EditorPage(admin2, base_url)
    theirs.open_tab()
    theirs.click(theirs.button(made["draft"], "take-over"))
    assert "admin has been editing this draft since" in theirs.text_of(theirs.confirm(made["draft"], "takeover"))
    theirs.click(theirs.confirm_button(made["draft"], "takeover"))
    editor2.wait_for_url(f"/job/{made['draft']}")
    editor2.wait_until(lambda d: editor2.value_of(editor2.JOB_NAME) == NAME)
    editor2.wait_for(editor2.EDITING)
    editor = EditorPage(admin, base_url)
    LayoutPage(admin, base_url).click(LayoutPage.tab("job"))
    editor.type(editor.JOB_NAME, f"{NAME}, changed")  # the server refuses the change, and the page finds out
    editor.driver.execute_script("arguments[0].blur()", editor.wait_for(editor.JOB_NAME))
    editor.wait_for(editor.LOCKED)
    editor2.new_job()
    editor.new_job()


def test_delete_a_draft(admin: WebDriver, base_url: str) -> None:
    """Section 2c, Drafts, step 3: the confirmation opens under the draft with its buttons off meanwhile; Cancel
    closes it, and Delete draft removes the draft."""
    editor, drafts = EditorPage(admin, base_url), DraftsPage(admin, base_url)
    job_id = editor.make_draft("bmut to delete", {"16-4711.jpg": "Found — will link"})
    editor.new_job()
    drafts.open_tab()
    drafts.click(drafts.button(job_id, "delete"))
    drafts.wait_for(drafts.confirm(job_id, "delete"))
    assert not drafts.is_enabled(drafts.button(job_id, "edit"))
    drafts.click(drafts.cancel_button(job_id, "delete"))
    drafts.wait_until_gone(drafts.confirm(job_id, "delete"))
    drafts.wait_until_enabled(drafts.button(job_id, "edit"))
    drafts.act(job_id, "delete", "delete")
    drafts.wait_until_gone(drafts.job(job_id))


def test_submitted_jobs_wait_in_a_paused_queue(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2c, Job queue, steps 1 and 2 (Pause queue with a reason): two submitted jobs are Queued, in order,
    each with when it runs, under the paused banner."""
    editor, queue = EditorPage(admin, base_url), QueuePage(admin, base_url)
    for key, name, file in (("one", "bmut queue one", "3-1002.jpg"), ("two", "bmut queue two", "3-1003.1_a.jpg")):
        made[key] = editor.make_draft(name, {file: "Found — will link"})
        editor.click(editor.SUBMIT)
        queue.wait_for_url("/queue")
        queue.wait_for_text(queue.status(made[key]), "Queued")
    assert queue.text_of(queue.PAUSED)
    assert "bmut: Drafts and Job queue" in queue.text_of(queue.PAUSED)
    assert int(queue.text_of(queue.order(made["two"]))) == int(queue.text_of(queue.order(made["one"]))) + 1
    for key in ("one", "two"):
        assert queue.text_of(queue.runs_at(made[key]))


@pytest.mark.after("test_submitted_jobs_wait_in_a_paused_queue")
def test_run_now_hold_and_set_run_time(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2c, Job queue, step 3: Run now and Undo Run now, Hold and Release, Set run time and Cancel."""
    queue = QueuePage(admin, base_url)
    job_id = made["one"]
    for on, off in (("run-now", "undo-run-now"), ("hold", "release")):
        queue.click(queue.button(job_id, on))
        queue.click(queue.button(job_id, off))
        queue.wait_for(queue.button(job_id, on))
    queue.click(queue.button(job_id, "set-run-time"))
    queue.wait_for(queue.run_at(job_id))
    queue.click(queue.button(job_id, "run-at-cancel"))
    queue.wait_until_gone(queue.run_at(job_id))


@pytest.mark.after("test_submitted_jobs_wait_in_a_paused_queue")
def test_reorder_with_the_arrows(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2c, Job queue, step 4 (the arrows): the second job moves up, then back down."""
    queue = QueuePage(admin, base_url)
    first = queue.text_of(queue.order(made["one"]))
    queue.click(queue.button(made["two"], "move-up"))
    queue.wait_for_text(queue.MESSAGE, f"Moved “bmut queue two” to position {first}.")
    queue.wait_for_text(queue.order(made["two"]), first)
    queue.click(queue.button(made["two"], "move-down"))
    queue.wait_for_text(queue.order(made["one"]), first)


@pytest.mark.after("test_submitted_jobs_wait_in_a_paused_queue")
def test_an_intern_in_the_job_queue(intern: WebDriver, base_url: str, paused: None) -> None:
    """Section 2i, step 10; 2j, step 9; 2c, Job queue, last step: no arrows or run controls, and Edit, Move to
    Drafts… and Delete off with "Only staff can do this.\""""
    queue = QueuePage(intern, base_url)
    queue.open_tab()
    queue.wait_for_text(queue.status(made["one"]), "Queued")
    assert queue.is_shown(queue.STAFF_ONLY)
    for control in ("move-up", "move-down", "run-now", "hold", "set-run-time"):
        assert not queue.is_shown(queue.button(made["one"], control)), control
    for action in ("edit", "to-drafts", "delete"):
        button = queue.button(made["one"], action)
        assert not queue.is_enabled(button), action
        assert queue.title_of(button) == STAFF_ONLY_WHY
    LayoutPage(intern, base_url).click(LayoutPage.tab("job"))


@pytest.mark.after("test_submitted_jobs_wait_in_a_paused_queue")
def test_move_to_drafts(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2j, step 8: "Move to Drafts…" asks first; then the job is in Drafts with nobody editing it."""
    queue, drafts = QueuePage(admin, base_url), DraftsPage(admin, base_url)
    queue.open_tab()
    queue.click(queue.button(made["two"], "to-drafts"))
    assert "Moving takes this job out of the queue" in queue.text_of(queue.confirm(made["two"], "todrafts"))
    queue.click(queue.confirm_button(made["two"], "todrafts"))
    queue.wait_for_text(queue.MESSAGE, "Moved “bmut queue two” to Drafts.")
    queue.wait_until_gone(queue.job(made["two"]))
    drafts.open_tab()
    drafts.wait_for(drafts.access(made["two"]))
    assert not drafts.is_shown(drafts.editing(made["two"]))


@pytest.mark.after("test_submitted_jobs_wait_in_a_paused_queue")
def test_edit_a_queued_job(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2c, Job queue, step 5: Edit on a queued job warns first; Edit anyway moves it to Drafts and opens
    it."""
    queue, editor = QueuePage(admin, base_url), EditorPage(admin, base_url)
    queue.open_tab()
    queue.act(made["one"], "edit", "edit")
    editor.wait_for_url(f"/job/{made['one']}")
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == "bmut queue one")
    editor.wait_for(editor.EDITING)
    editor.new_job()
