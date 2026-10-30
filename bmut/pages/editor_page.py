"""Create / edit job (components/job/JobEditor.vue and DocumentRow.vue)."""
from __future__ import annotations

import re

from .page import Locator, Page, by_id


class EditorPage(Page):
    JOB_NAME = by_id("job-name")
    FILE_INPUT = by_id("file-input")
    COUNTS = by_id("document-counts")  # "2 documents · nothing to fix"
    SAVE = by_id("save-draft-btn")
    SUBMIT = by_id("submit-job-btn")
    SAVED = by_id("saved-note")
    MESSAGE = by_id("editor-message")

    @staticmethod
    def status(n: int) -> Locator:
        """A document's status chip, by its number in the job (1 for the first file added)."""
        return by_id(f"document-{n}-status")

    def name_new_job(self, name: str) -> str:
        """Names the empty editor's job, which creates it (on the field's change, when it loses focus); returns its
        id, from the address."""
        self.type(self.JOB_NAME, name)
        self.driver.execute_script("arguments[0].blur()", self.wait_for(self.JOB_NAME))
        self.wait_until(lambda d: re.search(r"/job/[^/?#]+$", d.current_url))
        return str(self.driver.current_url.rstrip("/").rsplit("/", 1)[1])
