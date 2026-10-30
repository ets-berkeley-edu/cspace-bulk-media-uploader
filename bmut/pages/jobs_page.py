"""A job's line in Drafts, Job queue or Finished jobs (DraftsList.vue, QueueList.vue, FinishedJobs.vue): each puts the
job's id in its controls' ids."""
from __future__ import annotations

from .page import Locator, Page, by_id


class JobsPage(Page):
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
