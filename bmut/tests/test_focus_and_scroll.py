"""Focus without a jump back to the heading (docs/testing-checklist.md section 36). Half a second after a page opens,
its heading takes the keyboard (stores/context.ts, loadingComplete), without scrolling the page (lib/utils.ts,
putFocusNextTick: focus({preventScroll: true})); the router opens each new page at the top instead (router.ts,
scrollBehavior). A document's Delete and Cancel scroll only when the button they focus is out of sight. As the
simulator's admin, on one draft of 24 documents, tall enough to scroll in a 1400 by 1000 window."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.conftest import signed_in_browser
from bmut.files import jpeg
from bmut.pages.drafts_page import DraftsPage
from bmut.pages.editor_page import EditorPage
from bmut.pages.layout_page import TABS, LayoutPage

ADMIN = ("admin", "admin")  # the simulator's synthetic account: its password is its username
DOCUMENTS = 24
# How far the editor may move by itself as it settles after opening (pixels): a line or so.
MOVES_AS_IT_SETTLES = 100
# The draft the first test made, for the tests after it.
made: dict[str, str] = {}

# Opens Create / edit job from its tab and, as soon as the editor shows (the browser tab's title is set as it does),
# scrolls down to 400 pixels above the bottom: well inside the half second before the heading takes the focus. Then
# waits 1.5 seconds and reports where the page is, whether the heading was out of sight and without the focus when it
# scrolled (so a focus that scrolled would have had to move the page), and what has the focus. The script runs in the
# page, because a Selenium round trip after the click can take longer than that half second, and the test would then
# scroll only after the focus had moved. Not to the very bottom: the editor can still get a line shorter as it settles
# (CI's slower runner did, by 28 pixels), and the browser then pulls a page scrolled to the bottom up with it.
SCROLL_AS_THE_EDITOR_OPENS = """
const done = arguments[arguments.length - 1]
const start = performance.now()
document.getElementById('tab-job').click()
const opened = setInterval(() => {
  if (!document.title.startsWith('Create / edit job')) return
  clearInterval(opened)
  requestAnimationFrame(() => {
    window.scrollTo(0, document.documentElement.scrollHeight - window.innerHeight - 400)
    const scrolledAt = performance.now() - start
    const scrolledTo = window.scrollY
    const heading = document.getElementById('page-title').getBoundingClientRect()
    const headingOutOfSight = heading.bottom < 0 || heading.top > window.innerHeight
    const focusWhenScrolled = document.activeElement?.id
    setTimeout(() => done({scrolledAt, scrolledTo, headingOutOfSight, focusWhenScrolled, after: window.scrollY,
                           focus: document.activeElement?.id}), 1500)
  })
}, 10)
"""


@pytest.fixture(scope="module")
def admin(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, ADMIN)
    yield browser
    browser.quit()


def scroll_y(driver: WebDriver) -> int:
    return int(driver.execute_script("return Math.round(window.scrollY)"))


def in_sight(driver: WebDriver, element_id: str) -> bool:
    """Whether the whole element is inside the window, below the app bar (to a pixel: scrolling can leave fractions)."""
    return bool(driver.execute_script(
        "const r = document.getElementById(arguments[0]).getBoundingClientRect();"
        "const bar = document.getElementById('app-bar').getBoundingClientRect().bottom;"
        "return r.top >= bar - 1 && r.bottom <= window.innerHeight + 1", element_id))


def test_scrolling_as_the_editor_opens_is_kept(admin: WebDriver, base_url: str) -> None:
    """Section 36, step 1: scrolling down just after the editor opens, the page stays where it was scrolled to, and
    the heading still gets the focus. Before 18 November 2026 the heading's focus scrolled the page back to the top."""
    editor = EditorPage(admin, base_url)
    editor.new_job()
    LayoutPage(admin, base_url).wait_for_page("Create / edit job")
    made["draft"] = editor.name_new_job("bmut focus and scroll")
    editor.choose_files(editor.FILE_INPUT, [jpeg(f"12-5678_s{i:02}.jpg") for i in range(1, DOCUMENTS + 1)])
    editor.wait_for_text(editor.COUNTS, f"{DOCUMENTS} documents", timeout=120)
    editor.wait_for_checks()
    drafts = DraftsPage(admin, base_url)
    drafts.open_tab()
    # Drafts' own focus first: its timer looks the heading up by id half a second after Drafts opens, so if it were
    # still waiting it could focus the editor's heading instead, before the scroll, and the editor's focus would then
    # find its heading already focused, which never scrolls.
    drafts.wait_for_focus("page-title")

    admin.set_script_timeout(15)
    seen: dict[str, Any] = admin.execute_async_script(SCROLL_AS_THE_EDITOR_OPENS)
    assert seen["scrolledAt"] < 450, f"scrolled too late to test anything: {seen}"
    assert seen["headingOutOfSight"], f"the heading was still in sight, so its focus wouldn't scroll: {seen}"
    assert seen["focusWhenScrolled"] != "page-title", f"the heading already had the focus: {seen}"
    # A focus that scrolls takes the page back to the heading, near the top (from about 2800 pixels to about 320);
    # the page settling as it opens moves it by a line at most.
    assert abs(seen["after"] - seen["scrolledTo"]) <= MOVES_AS_IT_SETTLES, f"the page moved: {seen}"
    assert seen["focus"] == "page-title", seen


@pytest.mark.after("test_scrolling_as_the_editor_opens_is_kept")
def test_a_new_page_opens_at_the_top(admin: WebDriver, base_url: str) -> None:
    """Section 36, step 2: from Drafts scrolled down (Expand all makes it long), the editor opens at the top. Without
    the router's scrollBehavior it would open where Drafts was scrolled to: the heading's focus no longer scrolls."""
    drafts = DraftsPage(admin, base_url)
    drafts.open_tab()
    drafts.click(drafts.EXPAND_ALL)
    drafts.wait_until(lambda d: d.find_element(*drafts.button(made["draft"], "toggle"))
                      .get_attribute("aria-expanded") == "true")
    admin.execute_script("window.scrollTo(0, document.documentElement.scrollHeight)")
    drafts.wait_until(lambda d: scroll_y(d) > 300)
    layout = LayoutPage(admin, base_url)
    layout.click(layout.tab("job"))
    layout.wait_for_page("Create / edit job")
    layout.wait_until(lambda d: scroll_y(d) == 0)
    drafts.open_tab()
    drafts.click(drafts.COLLAPSE_ALL)


def test_each_page_puts_the_focus_on_its_heading(admin: WebDriver, base_url: str) -> None:
    """Section 36, step 3, partly: each tab puts the keyboard on its heading, which names the page, as a screen reader
    reads it. Whether VoiceOver says it is still checked by hand."""
    layout = LayoutPage(admin, base_url)
    for tab_id, title, _ in reversed(TABS):
        layout.click(layout.tab(tab_id))
        layout.wait_for_page(title)
        layout.wait_for_focus("page-title")
        assert admin.switch_to.active_element.get_attribute("textContent").strip() == title


@pytest.mark.after("test_scrolling_as_the_editor_opens_is_kept")
def test_delete_brings_its_confirmation_into_sight(admin: WebDriver, base_url: str) -> None:
    """Section 36, step 4: with a document's Delete at the bottom of the window, pressing it with the keyboard opens
    the confirmation under the row, out of sight, and scrolls just enough to show Cancel, which has the focus.
    Cancel puts the focus back on Delete, which is in sight, so the page doesn't move."""
    n = DOCUMENTS // 2
    editor = EditorPage(admin, base_url)
    editor.open(f"job/{made['draft']}")
    editor.wait_for_text(editor.COUNTS, f"{DOCUMENTS} documents")
    editor.wait_for_checks()
    editor.wait_for_focus("page-title")  # the page's own focus move is over
    delete, cancel = f"document-{n}-delete-btn", f"document-{n}-delete-cancel-btn"
    admin.execute_script("const b = document.getElementById(arguments[0]);"
                         "b.scrollIntoView({block: 'end'}); b.focus({preventScroll: true})", delete)
    editor.wait_for_focus(delete)
    assert in_sight(admin, delete)

    admin.switch_to.active_element.send_keys(Keys.ENTER)
    editor.wait_for_focus(cancel)
    editor.wait_until(lambda d: in_sight(d, cancel))
    editor.wait_until(lambda d: in_sight(d, delete))  # 'nearest' scrolls no further than it needs to
    at = scroll_y(admin)

    admin.switch_to.active_element.send_keys(Keys.ENTER)
    editor.wait_until_gone(editor.field(n, "delete-cancel-btn"))
    editor.wait_for_focus(delete)
    assert in_sight(admin, delete)
    assert scroll_y(admin) == at
    editor.new_job()
