"""What every page object shares, as in the team's other Selenium suites (serenade's pages/page.py): waits, clicks and
typing by locator."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

Locator = tuple[str, str]
TIMEOUT = 10


class Page:
    def __init__(self, driver: WebDriver, base_url: str):
        self.driver = driver
        self.base_url = base_url

    def open(self, path: str = "") -> None:
        self.driver.get(self.base_url + path)

    def wait_for(self, locator: Locator, timeout: float = TIMEOUT) -> WebElement:
        element: WebElement = WebDriverWait(self.driver, timeout).until(ec.visibility_of_element_located(locator))
        return element

    def wait_for_text(self, locator: Locator, text: str, timeout: float = TIMEOUT) -> WebElement:
        """Waits until the element shows the text (pages fill in after their data arrives)."""
        WebDriverWait(self.driver, timeout, ignored_exceptions=(StaleElementReferenceException,)).until(
            ec.text_to_be_present_in_element(locator, text))
        return self.wait_for(locator)

    def wait_until(self, check: Callable[[WebDriver], Any], timeout: float = TIMEOUT) -> Any:
        return WebDriverWait(self.driver, timeout, ignored_exceptions=(StaleElementReferenceException,)).until(check)

    def wait_until_gone(self, locator: Locator, timeout: float = TIMEOUT) -> None:
        WebDriverWait(self.driver, timeout, ignored_exceptions=(StaleElementReferenceException,)).until(
            ec.invisibility_of_element_located(locator))

    def click(self, locator: Locator) -> None:
        """Clicks the element once it can take the click: just after a page opens its layout is still settling, and
        Chrome refuses a click that would land on another element. A refused click clicks nothing, so trying again
        is safe; each try after a refused one first brings the element to the middle of the window."""
        refused = False

        def clicked(driver: WebDriver) -> bool:
            nonlocal refused
            element = ec.element_to_be_clickable(locator)(driver)
            if not element:
                return False
            if refused:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", element)
            try:
                element.click()
            except ElementClickInterceptedException:
                refused = True
                raise
            return True

        WebDriverWait(self.driver, TIMEOUT, ignored_exceptions=(ElementClickInterceptedException,
                                                                 StaleElementReferenceException)).until(clicked)

    def type(self, locator: Locator, text: str) -> None:
        """Replaces what the field holds with the text. A page moves focus itself half a second after it loads
        (lib/utils.ts: putFocusNextTick, to its heading or first field), and keys typed after that go where the focus
        went: so the field is checked, and typed in again if it didn't get them all."""
        def typed(driver: WebDriver) -> bool:
            element = self.wait_for(locator)
            self._empty(element)
            element.send_keys(text)
            return element.get_attribute("value") == text

        WebDriverWait(self.driver, TIMEOUT, poll_frequency=0.6,
                      ignored_exceptions=(StaleElementReferenceException,)).until(typed)

    def _empty(self, element: WebElement) -> None:
        """Empties a field so the page sees it: Selenium's clear() changes the value without the input event Vue's
        v-model listens for, so the page would keep the old text (and typing would add to it)."""
        self.driver.execute_script(
            "arguments[0].value = ''; arguments[0].dispatchEvent(new Event('input', {bubbles: true}))", element)

    def choose_files(self, locator: Locator, paths: list[str]) -> None:
        """Gives a file input its files (the input itself is hidden, so it's found, not waited for)."""
        WebDriverWait(self.driver, TIMEOUT).until(ec.presence_of_element_located(locator)).send_keys("\n".join(paths))

    def text_of(self, locator: Locator) -> str:
        return self.wait_for(locator).text

    def title_of(self, locator: Locator) -> str:
        """The element's tooltip: a switched-off control's says why it is off (lib/roles.ts)."""
        return str(self.wait_for(locator).get_attribute("title") or "")

    def is_shown(self, locator: Locator) -> bool:
        """Whether the element is on the page and visible now, without waiting for it."""
        return any(e.is_displayed() for e in self.driver.find_elements(*locator))

    def is_enabled(self, locator: Locator) -> bool:
        return self.wait_for(locator).is_enabled()

    def wait_until_enabled(self, locator: Locator, enabled: bool = True, timeout: float = TIMEOUT) -> None:
        """Waits until the control is on (or off): many wait for checks against CollectionSpace."""
        self.wait_until(lambda d: d.find_element(*locator).is_enabled() == enabled, timeout)

    def value_of(self, locator: Locator) -> str:
        return str(self.wait_for(locator).get_attribute("value"))

    def wait_for_url(self, ending: str, timeout: float = TIMEOUT) -> None:
        WebDriverWait(self.driver, timeout).until(lambda d: d.current_url.endswith(ending))

    def wait_for_focus(self, element_id: str) -> None:
        """Waits until the element has the focus (where a page puts it once it has loaded)."""
        WebDriverWait(self.driver, TIMEOUT).until(
            lambda d: d.switch_to.active_element.get_attribute("id") == element_id)

    def wait_for_title(self, title: str) -> None:
        """Waits for the browser tab's title (the page sets it once its data has loaded)."""
        WebDriverWait(self.driver, TIMEOUT).until(lambda d: d.title == title)

    def requests_to(self, path: str) -> int:
        """How many requests this page has made to the path since it loaded (the browser's resource timings)."""
        return int(self.driver.execute_script(
            "return performance.getEntriesByType('resource').filter(e => e.name.includes(arguments[0])).length", path))


def by_id(element_id: str) -> Locator:
    return (By.ID, element_id)
