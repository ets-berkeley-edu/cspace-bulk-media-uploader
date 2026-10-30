"""Finished jobs (docs/testing-checklist.md section 2d), with 2a's Replace file: four jobs run, three of them with a
failure set in Demo tools ("Make CollectionSpace fail"): two need attention (one needs a change, one only another
run), and one failed (CollectionSpace refused the sign-in, so the run stopped and created nothing); the fourth
completes. As the simulator's admin, and intern for what an intern can't do, each in a browser of its own
signed in once. The tests run in order and build on the first one's jobs.

Each failure names one file, so it fails only that document; it applies to one request of the job's run. The files
are named for the simulator's sample Objects (the fakecspace package's BMU set), so every document is found and links."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.select import Select

from bmut.conftest import signed_in_browser
from bmut.files import jpeg
from bmut.pages.demo_page import DemoPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.finished_page import FinishedPage
from bmut.pages.layout_page import LayoutPage

ADMIN = ("admin", "admin")     # staff with every permission (each password is its username)
INTERN = ("intern", "intern")
FOUND = "Found — will link"
# Each job: its name, its files, and the failure Demo tools sets for its run (step, status, the file it names).
JOBS = {
    "attention": ("bmut finished attention", ["3-1001_f.jpg", "1-2345_f.jpg"], ("upload", "413 file too large", "1-2345_f")),
    "rerun": ("bmut finished rerun", ["16-4711_f.jpg"], ("upload", "500 server error", "16-4711_f")),
    "failed": ("bmut finished failed", ["12-5678_f.jpg"], ("media", "401 sign-in", "12-5678_f")),
    "completed": ("bmut finished completed", ["15-1240_f.jpg"], None),
}
# The jobs the first test ran, for the tests after it.
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


def test_jobs_that_need_attention_fail_and_complete(admin: WebDriver, base_url: str) -> None:
    """Section 2d, preparation ("Use Demo tools to make a job need attention and one fail"): each job is submitted
    with its failure set, and ends with the outcome it gives."""
    editor, demo, finished = EditorPage(admin, base_url), DemoPage(admin, base_url), FinishedPage(admin, base_url)
    outcomes = {}
    for key, (name, files, failure) in JOBS.items():
        made[key] = editor.make_draft(name, {file: FOUND for file in files})
        if failure:
            demo.add_failure(*failure)
        editor.wait_until_enabled(editor.SUBMIT, timeout=30)
        editor.click(editor.SUBMIT)
        editor.wait_for_url("/queue")
        outcomes[key] = finished.wait_for_outcome(made[key])
    assert outcomes == {"attention": "Needs attention", "rerun": "Needs attention", "failed": "Failed",
                        "completed": "Completed"}


@pytest.mark.after("test_jobs_that_need_attention_fail_and_complete")
def test_the_list(admin: WebDriver, base_url: str) -> None:
    """Section 2d, step 1: each job's outcome chip, its documents by result, when it finished and who ran it; every
    column sorts; Expand all and Collapse all."""
    finished = FinishedPage(admin, base_url)
    finished.open_tab()
    finished.wait_for(finished.job(made["attention"]))
    assert finished.text_of(finished.counts(made["attention"])) == "1 done · 1 partial"
    assert finished.text_of(finished.counts(made["completed"])) == "1 done"
    assert "by admin" in finished.text_of(finished.job(made["attention"]))
    for column in ("name", "outcome", "docs", "finished"):
        for order in ("ascending", "descending", "none"):
            finished.click(finished.sort(column))
            finished.wait_until(lambda d: d.find_element(*finished.heading(column)).get_attribute("aria-sort") == order)
    toggle = finished.button(made["attention"], "toggle")
    for button, expanded in ((finished.EXPAND_ALL, "true"), (finished.COLLAPSE_ALL, "false")):
        finished.click(button)
        finished.wait_until(lambda d: d.find_element(*toggle).get_attribute("aria-expanded") == expanded)


@pytest.mark.after("test_jobs_that_need_attention_fail_and_complete")
def test_a_jobs_details_and_results(admin: WebDriver, base_url: str) -> None:
    """Section 2d, steps 2 and 3: expanded, the job shows its run line and documents, with "View all N documents'
    results". The results: the run history, each document's steps with CSIDs, the failure with "Show technical
    details", the Show filter and sorting, and "Back to finished jobs"."""
    finished = FinishedPage(admin, base_url)
    job_id = made["attention"]
    finished.open_tab()
    finished.click(finished.button(job_id, "toggle"))
    assert "1-2345_f.jpg" in finished.text_of(finished.details(job_id))
    finished.click(finished.button(job_id, "all-results"))
    finished.wait_for_text(finished.RESULTS_TITLE, JOBS["attention"][0])
    assert finished.text_of(finished.RESULTS_OUTCOME) == "Needs attention"
    assert "Run 1: Needs attention" in finished.text_of(finished.RUN_HISTORY)
    assert finished.text_of(finished.result(1, "state")) == "Done"
    assert admin.find_elements(By.CSS_SELECTOR, "#result-1-steps code")  # each step's CSID
    assert finished.text_of(finished.result(2, "state")) == "Partial"  # its Media record exists, without the file
    what = finished.result(2, "what")
    assert "File too large for CollectionSpace" in finished.text_of(what)
    details = (By.XPATH, "//*[@id='result-2-what']//button[contains(., 'technical details')]")
    finished.click(details)
    finished.wait_for_text(what, "upload_too_large")
    finished.wait_until(lambda d: d.find_element(*details).get_attribute("aria-expanded") == "true")
    finished.click(finished.results_sort("result"))
    finished.wait_until(lambda d: d.find_element(By.XPATH, "//th[.//*[@id='results-sort-col-result-btn']]")
                        .get_attribute("aria-sort") == "ascending")
    filters = [str(o.get_attribute("value")) for o in admin.find_elements(By.CSS_SELECTOR, "#results-filter-select option")]
    assert len(filters) > 1
    Select(finished.wait_for(finished.RESULTS_FILTER)).select_by_value(filters[1])
    finished.wait_until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "#results-table tbody tr[id^='result-']")) < 2)
    finished.click(finished.RESULTS_BACK)
    finished.wait_for(finished.job(job_id))


@pytest.mark.after("test_jobs_that_need_attention_fail_and_complete")
def test_fix_labels_and_a_completed_job(admin: WebDriver, base_url: str) -> None:
    """Section 2d, steps 4 and 7: a job whose failure needs a change reads Fix and reschedule, one whose failure only
    needs another run reads Reschedule; a completed job shows "Removed" and a date, and no Fix or Delete."""
    finished = FinishedPage(admin, base_url)
    finished.open_tab()
    finished.wait_for_text(finished.button(made["attention"], "fix"), "Fix and reschedule")
    finished.wait_for_text(finished.button(made["rerun"], "fix"), "Reschedule")
    assert finished.text_of(finished.button(made["rerun"], "fix")) == "Reschedule"
    assert finished.text_of(finished.removed_on(made["completed"])).startswith("Removed ")
    for action in ("fix", "delete"):
        assert not finished.is_shown(finished.button(made["completed"], action))


@pytest.mark.after("test_jobs_that_need_attention_fail_and_complete")
def test_an_intern_cant_fix_or_delete(intern: WebDriver, base_url: str) -> None:
    """Section 2d, step 8: as intern, Fix and Delete are off, with the reason on hover."""
    finished = FinishedPage(intern, base_url)
    finished.open_tab()
    for action in ("fix", "delete"):
        button = finished.button(made["attention"], action)
        assert not finished.is_enabled(button), action
        assert finished.title_of(button), action
    LayoutPage(intern, base_url).click(LayoutPage.tab("job"))


@pytest.mark.after("test_jobs_that_need_attention_fail_and_complete")
def test_delete_from_the_list(admin: WebDriver, base_url: str) -> None:
    """Section 2d, step 5: Delete opens the confirmation under the job, saying what stays in CollectionSpace; Cancel
    closes it; Delete job removes the job and shows the blue message."""
    finished = FinishedPage(admin, base_url)
    job_id = made["rerun"]
    finished.open_tab()
    finished.click(finished.button(job_id, "delete"))
    assert "They stay in CollectionSpace" in finished.text_of(finished.confirm(job_id, "delete"))
    finished.click(finished.cancel_button(job_id, "delete"))
    finished.wait_until_gone(finished.confirm(job_id, "delete"))
    finished.act(job_id, "delete", "delete")
    finished.wait_for_text(finished.MESSAGE, f"Deleted “{JOBS['rerun'][0]}” from the BMU.")
    finished.wait_until_gone(finished.job(job_id))


@pytest.mark.after("test_jobs_that_need_attention_fail_and_complete")
def test_delete_from_the_results(admin: WebDriver, base_url: str) -> None:
    """Section 2d, step 6: in a job's results the confirmation takes the place of the buttons; after deleting, the
    list is back, without the job."""
    finished = FinishedPage(admin, base_url)
    job_id = made["failed"]
    finished.open_tab()
    finished.click(finished.button(job_id, "view-results"))
    finished.wait_for_text(finished.RESULTS_TITLE, JOBS["failed"][0])
    finished.click(finished.button(job_id, "delete"))
    assert "it created nothing in CollectionSpace" in finished.text_of(finished.confirm(job_id, "delete"))
    assert not finished.is_shown(finished.button(job_id, "fix"))
    finished.click(finished.confirm_button(job_id, "delete"))
    finished.wait_for_text(finished.MESSAGE, f"Deleted “{JOBS['failed'][0]}” from the BMU.")
    finished.wait_until_gone(finished.job(job_id))


@pytest.mark.after("test_jobs_that_need_attention_fail_and_complete")
def test_fix_and_reschedule_with_a_replacement_file(admin: WebDriver, base_url: str) -> None:
    """Section 2d, step 4, and 2a, step 10 (Replace file): Fix and reschedule opens the job in Create / edit job,
    fixing after run 1; the document whose file was too large takes a replacement file, and the rerun completes the
    job."""
    finished, editor = FinishedPage(admin, base_url), EditorPage(admin, base_url)
    job_id = made["attention"]
    finished.open_tab()
    finished.click(finished.button(job_id, "fix"))
    editor.wait_for_url(f"/job/{job_id}")
    assert "Fixing after run 1" in editor.text_of(editor.FIXING)
    assert editor.text_of(editor.status(1)) == "Done in last run"
    editor.expand(2)
    # The button opens the file picker; Chrome is told to leave the picker closed, and the file goes to its input
    admin.execute_cdp_cmd("Page.setInterceptFileChooserDialog", {"enabled": True})
    try:
        editor.click(editor.field(2, "replace-btn"))
        editor.saving(lambda: editor.choose_files((By.CSS_SELECTOR, "#document-2-detail input[type=file]"),
                                                  [jpeg("1-2345_f.jpg")]))
    finally:
        admin.execute_cdp_cmd("Page.setInterceptFileChooserDialog", {"enabled": False})
    editor.wait_for_text(editor.field(2, "detail"), "Replacement file: 1-2345_f.jpg", timeout=30)
    editor.wait_until_enabled(editor.SUBMIT, timeout=60)
    editor.click(editor.SUBMIT)
    editor.wait_for_url("/queue")
    finished.wait_until(lambda d: finished.wait_for_outcome(job_id) == "Completed", timeout=120)
    assert finished.text_of(finished.counts(job_id)) == "2 done"
