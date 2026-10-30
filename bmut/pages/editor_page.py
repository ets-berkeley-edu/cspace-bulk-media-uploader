"""Create / edit job (components/job/JobEditor.vue and DocumentRow.vue)."""
from __future__ import annotations

import re

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

    def protected_reason(self, n: int) -> str:
        """Why the document is a protected file, from its Protected chip's tooltip ("Protected file: <reason>")."""
        chip = self.wait_for((By.CSS_SELECTOR, f"#document-{n} .v-chip[title^='Protected file: ']"))
        return str(chip.get_attribute("title")).removeprefix("Protected file: ")
