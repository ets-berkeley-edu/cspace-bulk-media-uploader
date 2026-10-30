"""One job from start to finish (docs/testing-checklist.md sections 2a, 2b and 2: The job being worked on, across
tabs): name a job, add files, see them checked, find it in Drafts, submit it, and see it in Job queue and then
Finished jobs.

The test stack has every moment a run time (BMU_ALWAYS_RUN_TIME in ./bmu), so a submitted job runs at once. The files
are named for the simulator's sample Objects (the fakecspace package's BMU set, seeds.py), so each document links to
an Object that exists and nothing needs fixing. The tests run in order, each building on the one before, in one
browser signed in once, as one person would work: a second sign-in would find the draft held by the first."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.conftest import new_browser
from bmut.files import jpeg
from bmut.pages.editor_page import EditorPage
from bmut.pages.jobs_page import JobsPage
from bmut.pages.layout_page import LayoutPage
from bmut.pages.sign_in_page import SignInPage

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
NAME = "bmut job flow"
FILES = ["12-5678.jpg", "3-1001.jpg"]
# The job the first test made, for the tests after it.
made: dict[str, str] = {}


@pytest.fixture(scope="module")
def driver(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    """This file's one browser (in place of conftest.py's browser per test), signed in once."""
    browser = new_browser(request.config)
    SignInPage(browser, base_url).sign_in(*ADMIN)
    yield browser
    browser.quit()


@pytest.fixture
def editor(driver: WebDriver, base_url: str) -> EditorPage:
    page = EditorPage(driver, base_url)
    page.wait_for(page.JOB_NAME)
    return page


def test_name_a_job_and_add_files(editor: EditorPage, driver: WebDriver) -> None:
    """Section 2b, step 2 (naming a job gives the address its id); section 2a, step 2 (rows appear and their uploads
    finish); each document is checked against CollectionSpace and found."""
    made["id"] = editor.name_new_job(NAME)
    editor.choose_files(editor.FILE_INPUT, [jpeg(name) for name in FILES])
    for n in range(1, len(FILES) + 1):
        editor.wait_for_text(editor.status(n), "Found — will link", timeout=60)
    editor.wait_for_text(editor.COUNTS, f"{len(FILES)} documents")
    assert "nothing to fix" in editor.text_of(editor.COUNTS)
    driver.refresh()  # section 2b, step 1: the same draft after a reload
    editor.wait_for_url(f"/job/{made['id']}")
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == NAME)  # filled in once the draft has loaded
    editor.wait_for_text(editor.COUNTS, f"{len(FILES)} documents")


@pytest.mark.after("test_name_a_job_and_add_files")
def test_the_draft_in_drafts_and_back(editor: EditorPage, base_url: str) -> None:
    """Section 2, The job being worked on, step 1: Drafts lists the job; back in Create / edit job, the editor is as
    it was."""
    layout, jobs = LayoutPage(editor.driver, base_url), JobsPage(editor.driver, base_url)
    editor.open(f"job/{made['id']}")
    editor.wait_for_text(editor.COUNTS, f"{len(FILES)} documents")
    layout.click(layout.tab("drafts"))
    jobs.wait_for_text(jobs.name(made["id"]), NAME)
    layout.click(layout.tab("job"))
    editor.wait_for_url(f"/job/{made['id']}")
    editor.wait_until(lambda d: editor.value_of(editor.JOB_NAME) == NAME)  # filled in once the draft has loaded
    editor.wait_for_text(editor.COUNTS, f"{len(FILES)} documents")


@pytest.mark.after("test_the_draft_in_drafts_and_back")
def test_submit_and_the_run(editor: EditorPage, base_url: str) -> None:
    """Section 2, The job being worked on, step 5: Submit lands on Job queue with the message saying when it runs.
    The job then runs (every moment is a run time here) and is in Finished jobs, Completed, both documents done."""
    layout, jobs = LayoutPage(editor.driver, base_url), JobsPage(editor.driver, base_url)
    editor.open(f"job/{made['id']}")
    editor.wait_for_text(editor.COUNTS, f"{len(FILES)} documents")
    editor.click(editor.SUBMIT)
    layout.wait_for_url("/queue")
    assert f"“{NAME}” was submitted" in layout.text_of(layout.NOTICE)
    assert jobs.wait_for_outcome(made["id"]) == "Completed"
    assert jobs.text_of(jobs.counts(made["id"])) == f"{len(FILES)} done"
