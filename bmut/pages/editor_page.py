"""Create / edit job (components/job/JobEditor.vue and DocumentRow.vue)."""
from __future__ import annotations

import re
from collections.abc import Callable

from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select

from bmut.files import jpeg
from .layout_page import LayoutPage
from .page import Locator, Page, by_id


class EditorPage(Page):
    JOB_NAME = by_id("job-name")
    FILE_INPUT = by_id("file-input")
    COUNTS = by_id("document-counts")  # "2 documents · nothing to fix"
    SAVE = by_id("save-draft-btn")
    SUBMIT = by_id("submit-job-btn")
    SAVED = by_id("saved-note")
    MESSAGE = by_id("editor-message")
    EDITING = by_id("editor-editing")  # "Editing draft <name>", the name as the server has it
    LOCKED = by_id("editor-locked")  # the read-only preview of a draft someone else is editing
    # An intern's Submit for review (its ids date from "Hand over to staff", which it replaced: CLAUDE.md, Roles)
    REVIEW = by_id("hand-over-btn")
    REVIEW_CONFIRM = by_id("hand-over-confirm")
    REVIEW_CONFIRM_BTN = by_id("hand-over-confirm-btn")
    REVIEW_NOTE = by_id("review-note")  # who sent the draft for review, and when
    INTERN_OPEN = by_id("intern-open")  # staff: the "Open to interns" checkbox under the job name
    CREATOR_NOTE = by_id("creator-note")  # the purple line: documents that need an Object creator
    GROUP_ON = by_id("group-on")
    GROUP_TITLE = by_id("group-title")
    GROUP_PROBLEM = by_id("group-account-problem")
    FIXING = by_id("editor-fixing")  # "Fixing after run 1 (it needed attention…)"
    TAKE_OVER = by_id("take-over-btn")  # in the locked banner
    TAKE_OVER_CONFIRM = by_id("take-over-confirm")
    TAKE_OVER_CONFIRM_BTN = by_id("take-over-confirm-btn")
    SHOW_PROBLEMS = by_id("show-problems-btn")
    FILTER = by_id("filter-select")  # Show: All documents, With problems…
    PAGE_SIZE = by_id("page-size-select")
    PAGE_COUNT = by_id("pagination-count")  # "1–25 of 27 documents"
    NEXT_PAGE = by_id("page-next-btn")
    SELECT_PAGE = by_id("select-page-checkbox")
    CLEAR_SELECTION = by_id("clear-selection-btn")
    RETRY_INPUT = by_id("retry-file-input")
    # Change selected documents (BulkPanel.vue)
    BULK_HANDLING = by_id("bulk-handling-select")
    BULK_PUBLISH = by_id("bulk-publish-select")
    BULK_TYPE = by_id("bulk-type-select")
    BULK_APPLY_SELECTED = by_id("bulk-apply-selected-btn")
    BULK_APPLY_ALL = by_id("bulk-apply-all-btn")
    BULK_EXCLUDE = by_id("bulk-exclude-btn")
    BULK_INCLUDE = by_id("bulk-include-btn")
    BULK_DELETE = by_id("bulk-delete-btn")
    BULK_DELETE_CONFIRM = by_id("bulk-delete-confirm")
    BULK_DELETE_CONFIRM_BTN = by_id("bulk-delete-confirm-btn")

    @staticmethod
    def status(n: int) -> Locator:
        """A document's status chip, by its number in the job (1 for the first file added)."""
        return by_id(f"document-{n}-status")

    @staticmethod
    def handling(n: int) -> Locator:
        return by_id(f"document-{n}-handling")

    @staticmethod
    def exclude(n: int) -> Locator:
        return by_id(f"document-{n}-exclude")

    @staticmethod
    def group(n: int) -> Locator:
        return by_id(f"document-{n}-group")

    @staticmethod
    def delete(n: int) -> Locator:
        return by_id(f"document-{n}-delete-btn")

    @staticmethod
    def delete_confirm(n: int) -> Locator:
        return by_id(f"document-{n}-delete-confirm-btn")

    def name_new_job(self, name: str) -> str:
        """Names the empty editor's job, which creates it (on the field's change, when it loses focus); returns its
        id, from the address."""
        self.type(self.JOB_NAME, name)
        self.driver.execute_script("arguments[0].blur()", self.wait_for(self.JOB_NAME))
        self.wait_until(lambda d: re.search(r"/job/[^/?#]+$", d.current_url))
        return str(self.driver.current_url.rstrip("/").rsplit("/", 1)[1])

    def new_job(self) -> None:
        """New job: closes the draft open in the editor, so others can edit or submit it, and waits for the empty
        job."""
        layout = LayoutPage(self.driver, self.base_url)
        layout.click(layout.NEW_JOB)
        layout.wait_for_url("/job")
        self.wait_until(lambda d: self.value_of(self.JOB_NAME) == "")

    def add_file(self, name: str, status: str) -> None:
        """Adds the sample JPEG under the name, as the job's next document, and waits for its checks to give the
        status. One file at a time, so each document's number is the order the test added it in."""
        n = len(self.driver.find_elements(By.CSS_SELECTOR, "tbody.document")) + 1
        self.choose_files(self.FILE_INPUT, [jpeg(name)])
        self.wait_for_text(self.status(n), status, timeout=60)

    def make_draft(self, name: str, files: dict[str, str]) -> str:
        """A new job (New job first, so a draft left open by an earlier test is closed, not renamed), with the files
        (each name to the status its checks give); returns its id. It stays open."""
        self.new_job()
        LayoutPage(self.driver, self.base_url).wait_for_page("Create / edit job")
        job_id = self.name_new_job(name)
        for file, status in files.items():
            self.add_file(file, status)
        return job_id

    def set_handling(self, n: int, handling: str, status: str) -> None:
        """Chooses the document's handling (an id in bmu/tenants/pahma.yaml) and waits for the status the checks then
        give."""
        Select(self.wait_for(self.handling(n))).select_by_value(handling)
        self.wait_for_text(self.status(n), status, timeout=30)

    def handling_option(self, n: int, handling: str) -> str:
        """What the document's handling list says of an option ("… (needs an Object creator)")."""
        return str(self.wait_for((By.CSS_SELECTOR, f"#document-{n}-handling option[value='{handling}']"))
                   .get_attribute("textContent")).strip()

    def checks_of(self, n: int) -> list[str]:
        """The document's checks ("Must fix: No object …"), from its details, which this opens."""
        toggle = by_id(f"document-{n}-toggle-btn")
        if self.wait_for(toggle).get_attribute("aria-expanded") != "true":
            self.click(toggle)
        # The details are drawn once they come into view (DocumentRow.vue, v-lazy)
        detail = self.wait_for(by_id(f"document-{n}-detail"))
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", detail)
        self.wait_for((By.CSS_SELECTOR, f"#document-{n}-detail .dense-fields"))
        return [str(e.get_attribute("textContent")).strip()
                for e in self.driver.find_elements(By.CSS_SELECTOR, f"#document-{n}-detail .check")]

    @staticmethod
    def field(n: int, name: str) -> Locator:
        """One of the document's controls: filename, idnum, obj, date, type-0, creator, description, language-0,
        restricted, portal, select, file, toggle-btn, replace-btn, retry-btn…"""
        return by_id(f"document-{n}-{name}")

    def expand(self, n: int) -> None:
        """Opens the document's details and waits for its fields (drawn once they come into view)."""
        toggle = self.field(n, "toggle-btn")
        if self.wait_for(toggle).get_attribute("aria-expanded") != "true":
            self.click(toggle)
        detail = self.wait_for(self.field(n, "detail"))
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", detail)
        self.wait_for((By.CSS_SELECTOR, f"#document-{n}-detail .dense-fields"))

    def saving(self, change: Callable[[], None], path: str = "/rows/") -> None:
        """Makes a change and waits until its request to the server has been answered (the browser's resource timings
        list a request once its answer is in; they are emptied first, so a full list can't hide it)."""
        self.driver.execute_script("performance.clearResourceTimings()")
        change()
        self.wait_until(lambda d: self.requests_to(path) > 0, timeout=20)

    def edit_text(self, locator: Locator, text: str) -> None:
        """Types in a document's text field and leaves it: the field saves on its change event."""
        def change() -> None:
            self.type(locator, text)
            self.driver.execute_script("arguments[0].blur()", self.wait_for(locator))

        self.saving(change)

    def choose(self, locator: Locator, label: str) -> None:
        """Picks an option of a native list by its text, and waits for the change to be saved."""
        self.saving(lambda: Select(self.wait_for(locator)).select_by_visible_text(label))

    def tick(self, locator: Locator, on: bool) -> None:
        """Ticks or unticks a checkbox, and waits for the change to be saved."""
        if self.wait_for(locator).is_selected() != on:
            self.saving(lambda: self.click(locator))

    def selected_label(self, locator: Locator) -> str:
        return str(Select(self.wait_for(locator)).first_selected_option.text).strip()

    def files_shown(self) -> list[str]:
        """The documents' filenames, in the order the table shows them (this page only)."""
        return [e.text for e in self.driver.find_elements(By.CSS_SELECTOR, "tbody.document span[id$='-file']")]

    def protected_reason(self, n: int) -> str:
        """Why the document is a protected file, from its Protected chip's tooltip ("Protected file: <reason>")."""
        chip = self.wait_for((By.CSS_SELECTOR, f"#document-{n} .v-chip[title^='Protected file: ']"))
        return str(chip.get_attribute("title")).removeprefix("Protected file: ")
