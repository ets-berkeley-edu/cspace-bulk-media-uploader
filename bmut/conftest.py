"""The browser, the address the tests use, and what the suite does around each test (as serenade does for Serena).

BMUT_BASE_URL points at the BMU (default: the test stack's Vite dev server); BMUT_HEADED=1 or --headed shows the
browser. `./bmu test` sets the test stack's addresses."""
from __future__ import annotations

import os
import re
from collections.abc import Generator, Iterator
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.pages.layout_page import LayoutPage
from bmut.pages.sign_in_page import SignInPage

BASE_URL = os.environ.get("BMUT_BASE_URL", "http://localhost:5573/")
# Set only by ./bmu test: the tests change the stack's data, so they never run against a tester's ./bmu up sim.
ON_TEST_STACK = os.environ.get("BMUT_STACK") == "test"
# Screenshots and page HTML of failed browser tests (synthetic data only: the test stack never holds real data).
FAILURES = Path(__file__).parent / ".run" / "failures"

# Each test's outcome so far, for @pytest.mark.after.
_outcomes: dict[str, str] = {}

# The test files in the order they run (the rest after them, alphabetically): what only looks first, then what
# changes the stack's data (README: The order the tests run in).
FILE_ORDER = ["test_sign_in.py", "test_tabs.py", "test_job_flow.py", "test_roles.py", "test_three_kinds_of_result.py",
              "test_submit_for_review.py", "test_drafts_and_queue.py", "test_editor.py", "test_finished_jobs.py",
              "test_queue_collisions.py"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--headed", action="store_true", help="show the browser")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "after(*tests): run only if these earlier tests passed; otherwise skip")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    def rank(item: pytest.Item) -> int:
        name = item.path.name
        return FILE_ORDER.index(name) if name in FILE_ORDER else len(FILE_ORDER)

    items.sort(key=rank)  # a stable sort: each file's tests keep their own order


def pytest_runtest_setup(item: pytest.Item) -> None:
    # A test that builds on an earlier test's change is skipped, not failed, when that test didn't pass: its own
    # failure would only repeat the first one.
    for marker in item.iter_markers("after"):
        for name in marker.args:
            if _outcomes.get(name) != "passed":
                pytest.skip(f"needs {name}, which didn't pass")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None, pytest.TestReport,
                                                                                           pytest.TestReport]:
    report = yield
    if report.when == "call":
        _outcomes[item.name] = report.outcome
    elif report.outcome != "passed":
        _outcomes[item.name] = "skipped" if report.skipped else "failed"
    # Every browser the test used: "driver", or one per user ("admin", "intern") in the files that need several.
    browsers = {arg: value for arg, value in getattr(item, "funcargs", {}).items() if isinstance(value, WebDriver)}
    if report.when == "call" and report.failed and browsers:
        FAILURES.mkdir(parents=True, exist_ok=True)
        for arg, browser in browsers.items():
            name = re.sub(r"[^A-Za-z0-9_.-]", "_", item.name if arg == "driver" else f"{item.name}-{arg}")
            browser.save_screenshot(str(FAILURES / f"{name}.png"))
            (FAILURES / f"{name}.html").write_text(browser.page_source)
            report.sections.append(("bmut", f"Screenshot and page HTML in {FAILURES}/{name}.*"))
    return report


@pytest.fixture(scope="session")
def base_url() -> str:
    if not BASE_URL.startswith(("http://localhost", "http://127.0.0.1")):
        pytest.exit("bmut runs only against the local test stack (BMUT_BASE_URL on localhost).", returncode=2)
    if not ON_TEST_STACK:
        pytest.exit("bmut changes the stack's data, so it runs only on the test stack: ./bmu test", returncode=2)
    return BASE_URL


@pytest.fixture
def driver(request: pytest.FixtureRequest) -> Iterator[webdriver.Chrome]:
    browser = new_browser(request.config)
    yield browser
    browser.quit()


def new_browser(config: pytest.Config) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    if not (config.getoption("--headed") or os.environ.get("BMUT_HEADED") == "1"):
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    # No password manager: after a sign-in whose password is on a list of leaked ones (the simulator's intern / intern),
    # Chrome opens its "Change your password" bubble, and the page then gets none of the test's keys or clicks.
    options.add_experimental_option("prefs", {"credentials_enable_service": False,
                                              "profile.password_manager_enabled": False,
                                              "profile.password_manager_leak_detection": False})
    browser = webdriver.Chrome(options=options)
    browser.implicitly_wait(0)
    return browser


def signed_in_browser(config: pytest.Config, base_url: str, account: tuple[str, str]) -> webdriver.Chrome:
    """A browser signed in as the account, on Create / edit job: for a file that works through drafts as several
    users at once, each in a browser of their own (a second sign-in as the same user would find its drafts held)."""
    browser = new_browser(config)
    SignInPage(browser, base_url).sign_in(*account)
    LayoutPage(browser, base_url).wait_for(LayoutPage.TENANT)
    return browser
