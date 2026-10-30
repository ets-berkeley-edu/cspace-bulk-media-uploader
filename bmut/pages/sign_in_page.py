"""The sign-in page (views/Login.vue). The test stack serves one museum, so there is no museum list."""
from __future__ import annotations

from .page import Page, by_id


class SignInPage(Page):
    TITLE = by_id("page-title")
    USERNAME = by_id("username")
    PASSWORD = by_id("password")
    BUTTON = by_id("btn-sign-in")
    ERROR = by_id("sign-in-error")
    NOTICE = by_id("sign-in-notice")  # why the app sent you here (your session ended)
    ENVIRONMENT = by_id("environment-label")

    def sign_in(self, username: str, password: str) -> None:
        self.open("login")
        self.fill_in(username, password)

    def fill_in(self, username: str, password: str) -> None:
        """Signs in from the page as it is (where the app sent you, say)."""
        self.type(self.USERNAME, username)
        self.type(self.PASSWORD, password)
        self.click(self.BUTTON)
