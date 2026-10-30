"""Signing in and out (docs/testing-checklist.md section 2: Sign-in; Sign out and session end), with the simulator's
synthetic accounts (backend/fakecspace/app.py, USERS: each password is its username). Each test has its own browser,
so its sign-in ends with the test. Nothing here changes a job."""
from __future__ import annotations

from selenium.webdriver.remote.webdriver import WebDriver

from bmut.pages.layout_page import LABEL, LayoutPage
from bmut.pages.sign_in_page import SignInPage

ADMIN = ("admin", "admin")      # staff with every permission
NEWSTAFF = ("newstaff", "newstaff")  # the staff role without the permissions: refused at sign-in
READER = ("reader", "reader")   # neither BMU role: refused at sign-in


def test_sign_in_returns_to_the_page_asked_for(driver: WebDriver, base_url: str) -> None:
    """Section 2, Sign-in, step 1: signed out, Job queue's address opens the sign-in page; signing in opens Job queue,
    not Create / edit job."""
    sign_in, page = SignInPage(driver, base_url), LayoutPage(driver, base_url)
    sign_in.open("queue")
    sign_in.wait_for(sign_in.BUTTON)
    assert "/login" in driver.current_url
    sign_in.fill_in(*ADMIN)
    page.wait_for_url("/queue")
    page.wait_for_page("Job queue")
    assert page.selected_tab() == "queue"


def test_a_wrong_password(driver: WebDriver, base_url: str) -> None:
    """Section 2, Sign-in, step 2: the reason under the fields, the password emptied, the username kept."""
    sign_in = SignInPage(driver, base_url)
    sign_in.sign_in("admin", "not-the-password")
    assert sign_in.text_of(sign_in.ERROR)
    assert sign_in.value_of(sign_in.PASSWORD) == ""
    assert sign_in.value_of(sign_in.USERNAME) == "admin"


def test_empty_fields_ask_without_a_request(driver: WebDriver, base_url: str) -> None:
    """Section 2, Sign-in, step 3."""
    sign_in = SignInPage(driver, base_url)
    sign_in.open("login")
    sign_in.click(sign_in.BUTTON)
    assert sign_in.text_of(sign_in.ERROR) == "Enter your CollectionSpace username and password."
    assert sign_in.requests_to("/api/login") == 0


def test_the_environment_label(driver: WebDriver, base_url: str) -> None:
    """Section 2, Sign-in, step 4: above the sign-in card and in the app bar."""
    sign_in, page = SignInPage(driver, base_url), LayoutPage(driver, base_url)
    sign_in.open("login")
    assert sign_in.text_of(sign_in.ENVIRONMENT) == LABEL
    sign_in.fill_in(*ADMIN)
    page.wait_for(page.TENANT)
    assert page.text_of(page.ENVIRONMENT) == LABEL


def test_accounts_without_the_role_or_the_permissions_are_refused(driver: WebDriver, base_url: str) -> None:
    """Section 2i (roles, part 1): newstaff has the staff role but only reads; reader has neither BMU role."""
    sign_in = SignInPage(driver, base_url)
    for account in (NEWSTAFF, READER):
        sign_in.sign_in(*account)
        assert sign_in.text_of(sign_in.ERROR), account[0]
        assert "/login" in driver.current_url


def test_sign_out(driver: WebDriver, base_url: str) -> None:
    """Section 2, Sign out and session end: the menu under the username signs out, and the tabs then need a
    sign-in again."""
    sign_in, page = SignInPage(driver, base_url), LayoutPage(driver, base_url)
    sign_in.sign_in(*ADMIN)
    page.wait_for(page.TENANT)
    page.sign_out()
    sign_in.wait_for(sign_in.BUTTON)
    page.open("drafts")
    sign_in.wait_for(sign_in.BUTTON)
    assert "/login" in driver.current_url


def test_a_session_that_ended_returns_to_the_tab(driver: WebDriver, base_url: str) -> None:
    """Section 2, Sign out and session end, step 2: with the session cookie gone, the next click opens the sign-in
    page with the reason in a yellow box; signing in returns to the tab you were on."""
    sign_in, page = SignInPage(driver, base_url), LayoutPage(driver, base_url)
    sign_in.sign_in(*ADMIN)
    page.wait_for(page.TENANT)
    page.click(page.tab("drafts"))
    page.wait_for_page("Drafts")
    driver.delete_cookie("bmu_session_test")  # BMU_COOKIE_NAME of ./bmu test's stack
    page.click(page.tab("finished"))
    assert sign_in.text_of(sign_in.NOTICE)
    sign_in.fill_in(*ADMIN)
    page.wait_for(page.TENANT)
    page.wait_for_page("Finished jobs")  # where the click was going
