"""Drafts (views/Drafts.vue, components/job/DraftsList.vue): every draft, with its checks run again each time the
list is shown."""
from __future__ import annotations

from selenium.webdriver.common.by import By

from .jobs_page import JobsPage
from .layout_page import LayoutPage
from .page import Locator, by_id


class DraftsPage(JobsPage):
    MESSAGE = by_id("drafts-message")  # what a job's action just did ("… is now staff only.")
    ERROR = by_id("drafts-error")
    EXPAND_ALL = by_id("drafts-expand-all-btn")
    COLLAPSE_ALL = by_id("drafts-collapse-all-btn")

    @staticmethod
    def access(job_id: str) -> Locator:
        """"Open to interns" or "Staff only", under the draft's name."""
        return by_id(f"job-{job_id}-access")

    @staticmethod
    def review(job_id: str) -> Locator:
        """The blue "Needs review · sent by intern, <time>" mark."""
        return by_id(f"job-{job_id}-review")

    @staticmethod
    def editing(job_id: str) -> Locator:
        """Who has the draft open ("You", or their username)."""
        return by_id(f"job-{job_id}-editing")

    @staticmethod
    def expires(job_id: str) -> Locator:
        """When the draft is deleted: "Nov 28 (in 30 days)"."""
        return by_id(f"job-{job_id}-expires")

    @staticmethod
    def sort(column: str) -> Locator:
        """A column heading's sort button: name, docs, checks, saved, editing, expires."""
        return by_id(f"drafts-sort-col-{column}-btn")

    def open_tab(self) -> None:
        """Opens Drafts from its tab, and waits until it has loaded."""
        layout = LayoutPage(self.driver, self.base_url)
        layout.click(layout.tab("drafts"))
        layout.wait_for_page("Drafts")

    def wait_for_checks(self, job_id: str, text: str) -> None:
        """Waits for the draft's checks chip to read the text (it reads "Checking…" while they run)."""
        self.wait_for_text(self.checks(job_id), text, timeout=30)

    def job_ids(self) -> list[str]:
        """The drafts' ids, in the order the list shows them."""
        return [str(e.get_attribute("id")).removeprefix("job-")
                for e in self.driver.find_elements(By.CSS_SELECTOR, "#drafts-table tbody[id^='job-']")]
