"""A job's line in Drafts, Job queue or Finished jobs (DraftsList.vue, QueueList.vue, FinishedJobs.vue): each puts the
job's id in its controls' ids. Drafts and Job queue share their buttons (JobActions.vue) and the full preview
(JobDetails.vue, JobPreview.vue)."""
from __future__ import annotations

from selenium.webdriver.remote.webdriver import WebDriver

from .layout_page import LayoutPage
from .page import Locator, Page, by_id


class JobsPage(Page):
    PREVIEW = by_id("job-preview")
    PREVIEW_TITLE = by_id("preview-title")
    PREVIEW_BACK = by_id("preview-back-btn")
    PREVIEW_CHECK_AGAIN = by_id("preview-check-again-btn")

    @staticmethod
    def job(job_id: str) -> Locator:
        return by_id(f"job-{job_id}")

    @staticmethod
    def name(job_id: str) -> Locator:
        return by_id(f"job-{job_id}-name")

    @staticmethod
    def outcome(job_id: str) -> Locator:
        """Finished jobs: "Completed", "Needs attention" or "Failed"."""
        return by_id(f"job-{job_id}-outcome")

    @staticmethod
    def counts(job_id: str) -> Locator:
        """Finished jobs: its documents by result ("2 done")."""
        return by_id(f"job-{job_id}-counts")

    @staticmethod
    def checks(job_id: str) -> Locator:
        """Drafts and Job queue: the checks chip ("nothing to fix · 1 new Object")."""
        return by_id(f"job-{job_id}-checks")

    @staticmethod
    def button(job_id: str, action: str) -> Locator:
        """One of the job's buttons: edit, delete, submit, access, hand-over (Submit for review), take-over,
        to-drafts, toggle (its details)."""
        return by_id(f"job-{job_id}-{action}-btn")

    @staticmethod
    def confirm(job_id: str, kind: str) -> Locator:
        """The confirmation a button opens under the job's row: delete, submit, handover, takeover, edit, todrafts."""
        return by_id(f"job-{job_id}-{kind}-confirm")

    @staticmethod
    def confirm_button(job_id: str, kind: str) -> Locator:
        return by_id(f"job-{job_id}-{kind}-confirm-btn")

    @staticmethod
    def cancel_button(job_id: str, kind: str) -> Locator:
        return by_id(f"job-{job_id}-{kind}-cancel-btn")

    @staticmethod
    def details(job_id: str) -> Locator:
        """The expanded job: its facts and documents, under "Open full preview"."""
        return by_id(f"job-{job_id}-details")

    def act(self, job_id: str, action: str, kind: str) -> None:
        """Clicks one of the job's buttons, then Confirm in what it opens."""
        self.click(self.button(job_id, action))
        self.wait_for(self.confirm(job_id, kind))
        self.click(self.confirm_button(job_id, kind))

    def wait_for_outcome(self, job_id: str, timeout: float = 120) -> str:
        """Waits until the job is in Finished jobs, and returns its outcome. Finished jobs reads the list when it
        opens, so it is opened again until the run has ended."""
        layout = LayoutPage(self.driver, self.base_url)

        def finished(driver: WebDriver) -> bool:
            self.open("finished")
            layout.wait_for_page("Finished jobs")
            return bool(driver.find_elements(*self.outcome(job_id)))

        self.wait_until(finished, timeout=timeout)
        return self.text_of(self.outcome(job_id))
