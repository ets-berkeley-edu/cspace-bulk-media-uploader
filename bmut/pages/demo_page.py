"""Demo tools (components/demo/DemoPane.vue), the pane under every page on a stack with BMU_DEMO=true, as the test
stack has. Only "Make CollectionSpace fail" is used: its failures apply to job runs, and the simulator counts them
down as they happen."""
from __future__ import annotations

from selenium.webdriver.support.select import Select

from .page import Page, by_id


class DemoPage(Page):
    PANE = by_id("demo-pane")
    TOGGLE = by_id("demo-toggle-btn")
    BODY = by_id("demo-body")
    STEP = by_id("demo-fail-step-select")
    STATUS = by_id("demo-fail-status-select")
    COUNT = by_id("demo-fail-count-input")
    MATCH = by_id("demo-fail-match-input")
    ADD_FAILURE = by_id("demo-add-failure-btn")
    FAILURES = by_id("demo-failure-list")
    CLEAR_FAILURES = by_id("demo-clear-failures-btn")

    def open_pane(self) -> None:
        """Opens the pane if it is collapsed (it remembers its state in the browser)."""
        self.wait_for(self.PANE)
        if not self.is_shown(self.BODY):
            self.click(self.TOGGLE)
        self.wait_for(self.STEP)

    def add_failure(self, step: str, status: str, match: str, count: int = 1) -> None:
        """Makes CollectionSpace fail the job runs' requests at the step (media, upload…), with the status (its label
        in the list: "413 file too large"), for documents whose filename or number mentions the match."""
        self.open_pane()
        Select(self.wait_for(self.STEP)).select_by_value(step)
        Select(self.wait_for(self.STATUS)).select_by_visible_text(status)
        self.type(self.COUNT, str(count))
        self.type(self.MATCH, match)
        self.click(self.ADD_FAILURE)
        self.wait_for_text(self.FAILURES, match)
