"""Demo tools (docs/testing-checklist.md sections 2e and 2h), as the simulator's admin in one browser signed in once:
the pane opening, collapsing and remembering it; a failure counted down as a run uses it, and cleared; changed terms
listed in the pane and in a draft's checks; Delete all jobs…; Reset simulated CollectionSpace; and Reset everything…,
refused while a job runs, then putting the BMU back to how it starts. The tests run in order and build on each other.

This file runs last (conftest.FILE_ORDER): Delete all jobs and Reset everything delete every other file's jobs, and
Reset simulated CollectionSpace forgets the sample Objects until Reset everything seeds them again."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.select import Select

from bmut.conftest import signed_in_browser
from bmut.pages.demo_page import DemoPage
from bmut.pages.drafts_page import DraftsPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.finished_page import FinishedPage
from bmut.pages.layout_page import LayoutPage
from bmut.pages.page import by_id
from bmut.pages.queue_page import QueuePage

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
FOUND = "Found — will link"
DEFAULT_SCHEDULE = "Jobs run every day at 7:00 PM (Pacific time)."
SCHEDULE_BANNER = by_id("schedule-banner")
SCHEDULE_START = by_id("schedule-start")
SCHEDULE_SAVE = by_id("schedule-save-btn")
# The lists' empty lines
NO_DRAFTS, NO_QUEUED, NO_FINISHED = by_id("drafts-empty"), by_id("queue-empty"), by_id("finished-empty")
# The jobs the tests made, for the tests after them.
made: dict[str, str] = {}


@pytest.fixture(scope="module")
def admin(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, ADMIN)
    yield browser
    browser.quit()


def submit(editor: EditorPage) -> None:
    """Submit job on the draft open in the editor; lands on Job queue."""
    editor.wait_until_enabled(editor.SUBMIT, timeout=30)
    editor.click(editor.SUBMIT)
    editor.wait_for_url("/queue")


def assert_no_jobs(driver: WebDriver, base_url: str) -> None:
    """Drafts, Job queue and Finished jobs are all empty."""
    layout = LayoutPage(driver, base_url)
    for path, title, empty in (("drafts", "Drafts", NO_DRAFTS), ("queue", "Job queue", NO_QUEUED),
                               ("finished", "Finished jobs", NO_FINISHED)):
        layout.open(path)
        layout.wait_for_page(title)
        layout.wait_for(empty)


def test_the_pane_opens_collapses_and_remembers(admin: WebDriver, base_url: str) -> None:
    """Section 2e, step 1: the pane opens and collapses with its triangle; collapsed, it shows the one-line summary;
    the state survives a reload."""
    demo = DemoPage(admin, base_url)
    demo.open_pane()
    demo.click(demo.TOGGLE)
    demo.wait_until_gone(demo.BODY)
    assert demo.text_of(demo.SUMMARY).startswith("Browser uploads: ")
    admin.refresh()
    demo.wait_for_text(demo.SUMMARY, "Browser uploads: ")
    assert not demo.is_shown(demo.BODY)
    demo.click(demo.TOGGLE)
    demo.wait_for(demo.STEP)
    admin.refresh()
    demo.wait_for(demo.STEP)
    assert not demo.is_shown(demo.SUMMARY)


def test_a_failure_is_counted_down_and_cleared(admin: WebDriver, base_url: str) -> None:
    """Section 2e, step 3: a failure for the upload step makes the document fail in a run; the failure's "left"
    count goes down; Clear failures removes it. It's set for two requests, so one is left after the run."""
    editor, demo, finished = EditorPage(admin, base_url), DemoPage(admin, base_url), FinishedPage(admin, base_url)
    job = editor.make_draft("bmut demo failure", {"3-1001_d.jpg": FOUND})
    demo.add_failure("upload", "413 file too large", "3-1001_d", count=2)
    assert "2 of 2 left" in demo.text_of(demo.FAILURES)
    submit(editor)
    assert finished.wait_for_outcome(job) == "Needs attention"
    demo.open_pane()
    demo.wait_for_text(demo.FAILURES, "1 of 2 left")
    demo.click(demo.CLEAR_FAILURES)
    demo.wait_for_text(demo.FAILURES_SET, "No failures set.")
    assert not demo.is_shown(demo.FAILURES)


def test_changed_terms_are_listed_and_checked(admin: WebDriver, base_url: str) -> None:
    """Section 2e, step 4: a person deleted and a language renamed are listed in the pane; at Submit, the deleted
    person shows in the checks of a draft that uses it, and Submit is refused."""
    editor, demo = EditorPage(admin, base_url), DemoPage(admin, base_url)
    job = editor.make_draft("bmut demo terms", {"12-5678_d.jpg": FOUND})
    editor.expand(1)
    creator = editor.field(1, "creator")
    editor.type(creator, "Fre")
    editor.wait_for_text(editor.field(1, "creator-option-0"), "Leslie Freund", timeout=20)
    editor.saving(lambda: editor.click(editor.field(1, "creator-option-0")))
    editor.wait_until(lambda d: editor.value_of(creator) == "Leslie Freund")

    demo.open_pane()
    Select(demo.wait_for(demo.TERM)).select_by_visible_text("Leslie Freund")
    Select(demo.wait_for(demo.TERM_CHANGE)).select_by_value("deleted")
    demo.click(demo.TERM_APPLY)
    demo.wait_for_text(demo.TERM_CHANGES, "Leslie Freund: deleted")
    Select(demo.wait_for(demo.LANGUAGE_CHANGE)).select_by_value("rename")
    demo.type(demo.LANGUAGE_NAME, "bmut renamed")
    demo.click(demo.LANGUAGE_APPLY)
    demo.wait_for_text(demo.TERM_CHANGES, "renamed “bmut renamed”")

    # The editor and Drafts reuse a term's lookup for 10 minutes (rows.LOOKUP_TTL_SECONDS); Submit checks every term
    # afresh, and is refused.
    editor.click(editor.SUBMIT)
    editor.wait_for_text(editor.status(1), "Needs fixing", timeout=30)
    assert job in admin.current_url
    assert any("“Leslie Freund” no longer exists in CollectionSpace" in check for check in editor.checks_of(1))


def test_delete_all_jobs_asks_first(admin: WebDriver, base_url: str) -> None:
    """Section 2e, step 5: Delete all jobs… asks first, Cancel closes it, Delete all jobs empties the lists and the
    message appears."""
    demo, drafts, layout = DemoPage(admin, base_url), DraftsPage(admin, base_url), LayoutPage(admin, base_url)
    drafts.open("drafts")
    layout.wait_for_page("Drafts")
    drafts.wait_until(lambda d: drafts.job_ids())
    demo.open_pane()
    demo.click(demo.DELETE_ALL)
    assert demo.text_of(demo.DELETE_ALL_CONFIRM).startswith("Delete every job in this tenant")
    demo.click(demo.CONFIRM_CANCEL)
    demo.wait_until_gone(demo.DELETE_ALL_CONFIRM)
    assert drafts.job_ids()
    demo.click(demo.DELETE_ALL)
    demo.click(demo.DELETE_ALL_CONFIRM_BTN)
    layout.wait_for_text(layout.NOTICE, "Demo tools deleted")
    assert_no_jobs(admin, base_url)


def test_reset_everything_is_refused_while_a_job_runs(admin: WebDriver, base_url: str) -> None:
    """Section 2h, step 3: while a job is running (the run slowed down first), Reset everything is refused with a
    message naming the job."""
    editor, demo, queue = EditorPage(admin, base_url), DemoPage(admin, base_url), QueuePage(admin, base_url)
    layout = LayoutPage(admin, base_url)
    demo.set_delay(5)
    made["finished"] = job = editor.make_draft("bmut demo running", {"15-1240_d.jpg": FOUND})
    submit(editor)

    def running(driver: WebDriver) -> bool:
        queue.open("queue")
        layout.wait_for_page("Job queue")
        return any(e.text == "Running" for e in driver.find_elements(*queue.status(job)))

    queue.wait_until(running, timeout=30)
    demo.open_pane()
    demo.click(demo.RESET_EVERYTHING)
    demo.click(demo.RESET_EVERYTHING_CONFIRM_BTN)
    demo.wait_for_text(demo.ERROR, "“bmut demo running” is running")
    demo.set_delay(0)
    assert FinishedPage(admin, base_url).wait_for_outcome(job) == "Completed"


@pytest.mark.after("test_reset_everything_is_refused_while_a_job_runs")
def test_reset_everything_asks_first(admin: WebDriver, base_url: str) -> None:
    """Section 2h, steps 1 and 2, preparation: a draft, a queued job and a finished job (the last test's), and the
    schedule changed. Cancel in the confirmation changes nothing."""
    editor, demo, queue = EditorPage(admin, base_url), DemoPage(admin, base_url), QueuePage(admin, base_url)
    made["draft"] = editor.make_draft("bmut demo draft", {"16-4711_d.jpg": FOUND})
    queue.pause("bmut: reset everything")
    made["queued"] = editor.make_draft("bmut demo queued", {"1-2345_d.jpg": FOUND})
    submit(editor)
    queue.click(queue.SETTINGS)
    start = queue.wait_for(SCHEDULE_START)
    admin.execute_script("arguments[0].value = '08:00'; arguments[0].dispatchEvent(new Event('input', {bubbles: true}))",
                         start)
    queue.click(SCHEDULE_SAVE)
    queue.wait_for_text(SCHEDULE_BANNER, "Jobs run every day at 8:00 AM (Pacific time).")

    demo.open_pane()
    demo.click(demo.RESET_EVERYTHING)
    assert "This can't be undone. You stay signed in." in demo.text_of(demo.RESET_EVERYTHING_CONFIRM)
    demo.click(demo.CONFIRM_CANCEL)
    demo.wait_until_gone(demo.RESET_EVERYTHING_CONFIRM)
    admin.refresh()
    LayoutPage(admin, base_url).wait_for_page("Job queue")
    queue.wait_for(queue.job(made["queued"]))
    assert "8:00 AM" in queue.text_of(SCHEDULE_BANNER)


@pytest.mark.after("test_reset_everything_asks_first")
def test_reset_the_simulated_collectionspace(admin: WebDriver, base_url: str) -> None:
    """Section 2e, step 5: Reset simulated CollectionSpace puts its failures, terms and speeds back to the start (here:
    a failure set beforehand is gone)."""
    demo = DemoPage(admin, base_url)
    demo.add_failure("media", "500 server error", "bmut-reset-sim")
    demo.click(demo.RESET_SIM)
    demo.wait_for_text(demo.MESSAGE, "The simulated CollectionSpace is reset")
    demo.wait_for_text(demo.FAILURES_SET, "No failures set.")


@pytest.mark.after("test_reset_everything_asks_first")
def test_reset_everything(admin: WebDriver, base_url: str) -> None:
    """Section 2h, step 1: Reset everything…, confirmed, empties Drafts, Job queue and Finished jobs, puts the schedule
    back to every day at 7:00 PM, and leaves you signed in."""
    demo, layout, queue = DemoPage(admin, base_url), LayoutPage(admin, base_url), QueuePage(admin, base_url)
    demo.open_pane()
    demo.click(demo.RESET_EVERYTHING)
    demo.click(demo.RESET_EVERYTHING_CONFIRM_BTN)
    layout.wait_for_text(layout.NOTICE, "Demo tools reset everything")
    assert_no_jobs(admin, base_url)
    queue.open("queue")
    layout.wait_for_page("Job queue")
    assert queue.text_of(SCHEDULE_BANNER).startswith(DEFAULT_SCHEDULE)
    assert not queue.is_shown(queue.PAUSED)
    assert layout.text_of(layout.TENANT)  # still signed in


@pytest.mark.after("test_reset_everything")
def test_a_new_job_after_a_reset(admin: WebDriver, base_url: str) -> None:
    """Section 2h, step 4: after a reset, a new job is made and runs as on a fresh start (the sample Objects are
    there again)."""
    editor = EditorPage(admin, base_url)
    job = editor.make_draft("bmut demo after reset", {"15-1234_d.jpg": FOUND})
    submit(editor)
    assert FinishedPage(admin, base_url).wait_for_outcome(job) == "Completed"
