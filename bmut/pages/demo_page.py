"""Demo tools (components/demo/DemoPane.vue), the pane under every page on a stack with BMU_DEMO=true, as the test
stack has: making CollectionSpace fail (its failures apply to job runs, and the simulator counts them down as they
happen), slowing runs down, changing terms, and the Reset box."""
from __future__ import annotations

from selenium.webdriver.support.select import Select

from .page import Page, by_id


class DemoPage(Page):
    PANE = by_id("demo-pane")
    TOGGLE = by_id("demo-toggle-btn")
    BODY = by_id("demo-body")
    SUMMARY = by_id("demo-summary")  # the one-line summary the collapsed pane shows
    MESSAGE = by_id("demo-message")  # what the last control did
    ERROR = by_id("demo-error")  # what the server refused, and why
    DELAY = by_id("demo-delay-select")  # added delay per create or upload in job runs, in seconds
    # Make CollectionSpace fail
    STEP = by_id("demo-fail-step-select")
    STATUS = by_id("demo-fail-status-select")
    COUNT = by_id("demo-fail-count-input")
    MATCH = by_id("demo-fail-match-input")
    ADD_FAILURE = by_id("demo-add-failure-btn")
    FAILURES_SET = by_id("demo-failures-set")  # "Failures set:" or "No failures set."
    FAILURES = by_id("demo-failure-list")
    CLEAR_FAILURES = by_id("demo-clear-failures-btn")
    # Change terms in CollectionSpace
    TERM = by_id("demo-term-select")
    TERM_CHANGE = by_id("demo-term-change-select")
    TERM_APPLY = by_id("demo-term-apply-btn")
    LANGUAGE = by_id("demo-language-select")
    LANGUAGE_CHANGE = by_id("demo-language-change-select")
    LANGUAGE_NAME = by_id("demo-language-name-input")
    LANGUAGE_APPLY = by_id("demo-language-apply-btn")
    TERM_CHANGES = by_id("demo-term-changes")
    # Reset
    RESET_SIM = by_id("demo-reset-sim-btn")
    DELETE_ALL = by_id("demo-delete-all-btn")
    DELETE_ALL_CONFIRM = by_id("demo-delete-all-confirm")
    DELETE_ALL_CONFIRM_BTN = by_id("demo-delete-all-confirm-btn")
    RESET_EVERYTHING = by_id("demo-reset-everything-btn")
    RESET_EVERYTHING_CONFIRM = by_id("demo-reset-everything-confirm")
    RESET_EVERYTHING_CONFIRM_BTN = by_id("demo-reset-everything-confirm-btn")
    CONFIRM_CANCEL = by_id("demo-confirm-cancel-btn")  # Cancel in either confirmation

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

    def set_delay(self, seconds: int) -> None:
        """Adds the delay to each create and upload in job runs (0: none), and waits until the pane says so."""
        self.open_pane()
        Select(self.wait_for(self.DELAY)).select_by_value(str(seconds))
        self.wait_for_text(self.MESSAGE, f"{seconds} s longer" if seconds else "No added delay")
