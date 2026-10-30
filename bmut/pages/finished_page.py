"""Finished jobs (views/Finished.vue, components/job/FinishedJobs.vue, FinishedJobActions.vue and JobResults.vue): the
jobs that have run, and a job's results."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .jobs_page import JobsPage
from .layout_page import LayoutPage
from .page import Locator, by_id


class FinishedPage(JobsPage):
    LIST = by_id("finished-list")
    MESSAGE = by_id("finished-message")  # the blue message after Delete
    EXPAND_ALL = by_id("finished-expand-all-btn")
    COLLAPSE_ALL = by_id("finished-collapse-all-btn")
    # A job's results (View results)
    RESULTS_TITLE = by_id("results-title")
    RESULTS_OUTCOME = by_id("results-outcome")
    RESULTS_BACK = by_id("results-back-btn")
    RUN_HISTORY = by_id("run-history")
    RESULTS_FILTER = by_id("results-filter-select")
    RESULTS_TABLE = by_id("results-table")

    @staticmethod
    def sort(column: str) -> Locator:
        """A column heading's sort button: name, outcome, docs, finished."""
        return by_id(f"finished-sort-col-{column}-btn")

    @staticmethod
    def results_sort(column: str) -> Locator:
        """A results column's sort button: n, file, result, steps, what."""
        return by_id(f"results-sort-col-{column}-btn")

    @staticmethod
    def removed_on(job_id: str) -> Locator:
        """A completed job's "Removed Nov 28", in place of Fix and Delete."""
        return by_id(f"job-{job_id}-removed-on")

    @staticmethod
    def result(n: int, part: str) -> Locator:
        """A document's line in the results: state ("Done", "Failed"), steps (with CSIDs) or what (what happened)."""
        return by_id(f"result-{n}-{part}")

    def open_tab(self) -> None:
        """Opens Finished jobs from its tab, at the list: the tab keeps a job's results open."""
        layout = LayoutPage(self.driver, self.base_url)
        layout.click(layout.tab("finished"))
        layout.wait_for_page("Finished jobs")
        if self.is_shown(self.RESULTS_BACK):
            self.click(self.RESULTS_BACK)
        self.wait_for(self.LIST)

    def heading(self, column: str) -> Locator:
        """The column heading around a sort button, which carries aria-sort."""
        return (By.XPATH, f"//th[.//*[@id='finished-sort-col-{column}-btn']]")
