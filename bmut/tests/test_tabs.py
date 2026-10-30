"""Tabs as pages (docs/testing-checklist.md section 2: Tabs as pages; Dark mode). They only look."""
from __future__ import annotations

from selenium.webdriver.remote.webdriver import WebDriver

from bmut.pages.layout_page import TABS, LayoutPage
from bmut.pages.sign_in_page import SignInPage

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username


def signed_in(driver: WebDriver, base_url: str) -> LayoutPage:
    SignInPage(driver, base_url).sign_in(*ADMIN)
    page = LayoutPage(driver, base_url)
    page.wait_for(page.TENANT)
    return page


def test_a_reload_keeps_the_tab(driver: WebDriver, base_url: str) -> None:
    """Section 2, Tabs as pages, step 1."""
    page = signed_in(driver, base_url)
    for tab_id, title, path in TABS:
        page.click(page.tab(tab_id))
        page.wait_for_url(f"/{path}")
        driver.refresh()
        page.wait_for_page(title)
        assert page.selected_tab() == tab_id, title


def test_back_goes_back_through_the_tabs(driver: WebDriver, base_url: str) -> None:
    """Section 2, Tabs as pages, step 2."""
    page = signed_in(driver, base_url)
    for tab_id, _, path in TABS[1:]:
        page.click(page.tab(tab_id))
        page.wait_for_url(f"/{path}")
    for tab_id, title, _ in reversed(TABS[1:-1]):
        driver.back()
        page.wait_for_page(title)
        assert page.selected_tab() == tab_id


def test_the_browser_tabs_title_names_the_page(driver: WebDriver, base_url: str) -> None:
    """Section 2, Tabs as pages, step 3: for example "Drafts | BMU · Local · simulated CollectionSpace"."""
    page = signed_in(driver, base_url)
    for tab_id, title, _ in TABS[1:]:
        page.click(page.tab(tab_id))
        page.wait_for_page(title)


def test_page_not_found(driver: WebDriver, base_url: str) -> None:
    """Section 2, Tabs as pages, step 4."""
    page = signed_in(driver, base_url)
    page.open("nonsense")
    page.wait_for_text(page.TITLE, "Page not found")
    page.click(page.GO_TO_JOBS)
    page.wait_for_url("/job")
    assert page.selected_tab() == "job"


def test_dark_mode_and_back(driver: WebDriver, base_url: str) -> None:
    """Section 2, Dark mode, step 1: the menu item names the other mode, and the choice survives a reload. The page
    starts in the computer's own mode (headless Chrome follows the Mac's), so the test switches from whichever it is,
    and back (each test has its own browser, so nothing else would see the choice)."""
    page = signed_in(driver, base_url)
    page.click(page.MENU)
    first = page.text_of(page.DARK_MODE)
    assert first in ("Dark mode", "Light mode")
    page.click(page.DARK_MODE)
    driver.refresh()
    page.wait_for(page.TENANT)
    page.click(page.MENU)
    assert page.text_of(page.DARK_MODE) == ("Light mode" if first == "Dark mode" else "Dark mode")
    page.click(page.DARK_MODE)
