"""Job queue (views/Queue.vue, components/job/QueueList.vue and QueueSchedule.vue). On the test stack every moment is
a run time, so a submitted job waits in the queue only while the queue is paused (pause, resume)."""
from __future__ import annotations

from .jobs_page import JobsPage
from .layout_page import LayoutPage
from .page import Locator, by_id


class QueuePage(JobsPage):
    MESSAGE = by_id("queue-message")
    PAUSED = by_id("queue-paused")  # the yellow banner, with the reason
    STAFF_ONLY = by_id("schedule-scheduler-only")  # what an intern reads in place of the schedule's buttons
    SETTINGS = by_id("schedule-settings-btn")
    PAUSE = by_id("pause-queue-btn")
    PAUSE_REASON = by_id("pause-reason")
    PAUSE_CONFIRM = by_id("pause-queue-confirm-btn")
    RESUME = by_id("resume-queue-btn")
    # Jobs that collide (design: Jobs that collide in the queue): the box above the list
    COLLISIONS = by_id("queue-collisions")
    REMAINING = by_id("queue-collisions-remaining")  # what a reorder can't fix
    REORDER = by_id("queue-reorder-btn")
    REORDER_WHY = by_id("queue-reorder-why")  # an intern's line in its place
    REORDER_CONFIRM = by_id("queue-reorder-confirm")
    REORDER_CONFIRM_BTN = by_id("queue-reorder-confirm-btn")
    REORDER_CANCEL = by_id("queue-reorder-cancel-btn")

    @staticmethod
    def order(job_id: str) -> Locator:
        """The job's place in the queue, counting from 1."""
        return by_id(f"job-{job_id}-order")

    @staticmethod
    def status(job_id: str) -> Locator:
        return by_id(f"job-{job_id}-status")

    @staticmethod
    def runs_at(job_id: str) -> Locator:
        return by_id(f"job-{job_id}-runs-at")

    @staticmethod
    def run_at(job_id: str) -> Locator:
        """Set run time's field."""
        return by_id(f"job-{job_id}-run-at")

    def open_tab(self) -> None:
        """Opens Job queue from its tab, and waits until it has loaded."""
        layout = LayoutPage(self.driver, self.base_url)
        layout.click(layout.tab("queue"))
        layout.wait_for_page("Job queue")

    def pause(self, reason: str) -> None:
        """Staff: pauses the queue, so jobs submitted afterwards stay queued."""
        self.open("queue")
        LayoutPage(self.driver, self.base_url).wait_for_page("Job queue")
        self.wait_until(lambda d: self.is_shown(self.PAUSE) or self.is_shown(self.RESUME))
        if self.is_shown(self.RESUME):
            return
        self.click(self.PAUSE)
        self.type(self.PAUSE_REASON, reason)
        self.click(self.PAUSE_CONFIRM)
        self.wait_for_text(self.PAUSED, reason)

    def resume(self) -> None:
        self.open("queue")
        LayoutPage(self.driver, self.base_url).wait_for_page("Job queue")
        self.click(self.RESUME)
        self.wait_until_gone(self.PAUSED)
