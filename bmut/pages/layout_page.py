"""What every signed-in page shares: the app bar, its menu and the four tabs (views/BaseView.vue)."""
from __future__ import annotations

from .page import Locator, Page, by_id

# The tabs, by their ids (tab-<id>), titles and addresses, in order.
TABS = [("job", "Create / edit job", "job"), ("drafts", "Drafts", "drafts"), ("queue", "Job queue", "queue"),
        ("finished", "Finished jobs", "finished")]
LABEL = "Local · test stack"  # BMU_ENV_LABEL of ./bmu test's stack


class LayoutPage(Page):
    # Each tab's heading is for screen readers only (never visible), and Create / edit job's stays in the page behind
    # the other tabs, so a page is known by the browser tab's title instead (wait_for_page). Page not found's heading
    # shows.
    TITLE = by_id("page-title")
    TENANT = by_id("tenant-name")
    ENVIRONMENT = by_id("environment-label")
    ROLE = by_id("user-role")  # the "Intern" chip; staff have none
    MENU = by_id("btn-main-menu")
    DARK_MODE = by_id("menu-item-dark-mode")
    SIGN_OUT = by_id("menu-item-sign-out")
    NOTICE = by_id("notice")  # the blue message after Submit
    NEW_JOB = by_id("btn-new-job")
    GO_TO_JOBS = by_id("btn-go-to-jobs")  # Page not found's button

    @staticmethod
    def tab(tab_id: str) -> Locator:
        return by_id(f"tab-{tab_id}")

    def wait_for_page(self, title: str) -> None:
        """Waits until the page has loaded: the app then sets the browser tab's title, "Drafts | BMU · <label>"."""
        self.wait_for_title(f"{title} | BMU · {LABEL}")

    def selected_tab(self) -> str:
        """The id of the tab that is selected (Vuetify marks it with aria-selected)."""
        for tab_id, _, _ in TABS:
            if self.wait_for(self.tab(tab_id)).get_attribute("aria-selected") == "true":
                return tab_id
        return ""

    def sign_out(self) -> None:
        self.click(self.MENU)
        self.click(self.SIGN_OUT)
