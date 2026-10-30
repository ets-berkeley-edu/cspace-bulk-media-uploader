"""Jobs that collide in the queue (docs/testing-checklist.md section 2g): two jobs for the same new object, refused at
Submit, then moved into an order that would fail one of them, reordered, and run. As the simulator's admin, and
intern for a second browser watching the Job queue (2g asks for limited, a user without the scheduler role, which
roles part 1 made staff: an intern is now the one without the Reorder button). The tests run in order and build on
each other's jobs.

20-0995 and 20-0996 are object numbers the simulator doesn't have (backend/fakecspace/app.py), so "Create new
object + link" and "Link to object (create if missing)" both create them. The queue is paused from the first test
(every moment is a run time on the test stack) and resumed by the last, which lets the jobs run."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from bmut.conftest import signed_in_browser
from bmut.pages.editor_page import EditorPage
from bmut.pages.finished_page import FinishedPage
from bmut.pages.queue_page import QueuePage

ADMIN = ("admin", "admin")     # staff with every permission (each password is its username)
INTERN = ("intern", "intern")
CREATE, EITHER = "Create new object + link", "Link to object (create if missing)"  # bmu/tenants/pahma.yaml
# The jobs the tests made, for the tests after them: A creates 20-0995, B links to it or creates it.
made: dict[str, str] = {}


@pytest.fixture(scope="module")
def admin(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, ADMIN)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def intern(request: pytest.FixtureRequest, base_url: str) -> Iterator[WebDriver]:
    browser = signed_in_browser(request.config, base_url, INTERN)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def paused(admin: WebDriver, base_url: str) -> Iterator[None]:
    """The queue paused from the first test; the last test resumes it, or this does if that test didn't get there."""
    queue = QueuePage(admin, base_url)
    queue.pause("bmut: jobs that collide")
    yield
    queue.open_tab()
    queue.wait_until(lambda d: queue.is_shown(queue.PAUSE) or queue.is_shown(queue.RESUME))
    if queue.is_shown(queue.RESUME):
        queue.resume()


def submit(editor: EditorPage) -> None:
    editor.wait_until_enabled(editor.SUBMIT, timeout=30)
    editor.click(editor.SUBMIT)
    editor.wait_for_url("/queue")


def test_a_second_create_is_refused_at_submit(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2g, At Submit, steps 1 and 2: with job A queued to create object 20-0995, job B's "Create new object"
    for it needs fixing, naming A and offering "Link to object (create if missing)", and Submit is off. With that
    handling instead, only a warning about the same identification number stays, and B submits."""
    editor = EditorPage(admin, base_url)
    made["A"] = editor.make_draft("bmut collide A", {"20-0995_a.jpg": "Needs fixing"})
    editor.set_handling(1, "create", "Will create object")
    submit(editor)
    made["B"] = editor.make_draft("bmut collide B", {"20-0995_b.jpg": "Needs fixing"})
    editor.set_handling(1, "create", "Needs fixing")
    must_fix = [c for c in editor.checks_of(1) if c.startswith("Must fix")]
    assert len(must_fix) == 1 and "“bmut collide A”, ahead of this one in the job queue" in must_fix[0]
    assert EITHER in must_fix[0]
    assert not editor.is_enabled(editor.SUBMIT)
    editor.set_handling(1, "linkorcreate", "Will create object")
    checks = editor.checks_of(1)
    assert not [c for c in checks if c.startswith("Must fix")]
    assert any("also has a document with ID 20-0995" in c for c in checks)
    submit(editor)


@pytest.mark.after("test_a_second_create_is_refused_at_submit")
def test_create_after_create_if_missing_and_two_create_if_missing(admin: WebDriver, base_url: str,
                                                                  paused: None) -> None:
    """Section 2g, At Submit, steps 3 and 4: after job C, "create if missing" for 20-0996, a "Create new object" for
    it is refused at Submit; a second "create if missing" for it submits."""
    editor = EditorPage(admin, base_url)
    made["C"] = editor.make_draft("bmut collide C", {"20-0996_c.jpg": "Needs fixing"})
    editor.set_handling(1, "linkorcreate", "Will create object")
    submit(editor)
    editor.make_draft("bmut collide D", {"20-0996_d.jpg": "Needs fixing"})
    editor.set_handling(1, "create", "Needs fixing")
    assert any("“bmut collide C”, ahead of this one" in c for c in editor.checks_of(1))
    assert not editor.is_enabled(editor.SUBMIT)
    made["E"] = editor.make_draft("bmut collide E", {"20-0996_e.jpg": "Needs fixing"})
    editor.set_handling(1, "linkorcreate", "Will create object")
    submit(editor)


@pytest.mark.after("test_a_second_create_is_refused_at_submit")
def test_a_move_that_would_fail_asks_first(admin: WebDriver, intern: WebDriver, base_url: str, paused: None) -> None:
    """Section 2g, Changing the order, steps 1 to 4: moving B above A asks first, naming A's document; Cancel leaves
    the order alone. Run now on B and Hold on A ask the same. "Move anyway" marks A "needs fixing" at once, with a box
    above the list naming the document; a second browser with the Job queue open shows both within seconds, without a
    reload, and no Reorder button."""
    queue, theirs = QueuePage(admin, base_url), QueuePage(intern, base_url)
    a, b = made["A"], made["B"]
    theirs.open_tab()
    theirs.wait_for_text(theirs.status(a), "Queued")
    queue.open_tab()
    first = queue.text_of(queue.order(a))
    assert int(queue.text_of(queue.order(b))) == int(first) + 1
    for job_id, action, label in ((b, "move-up", "Move anyway"), (b, "run-now", "Run now anyway"),
                                  (a, "hold", "Hold anyway")):
        queue.click(queue.button(job_id, action))
        assert "20-0995_a.jpg" in queue.text_of(queue.confirm(job_id, "order"))
        assert queue.text_of(queue.confirm_button(job_id, "order")) == label
        queue.click(queue.cancel_button(job_id, "order"))
        queue.wait_until_gone(queue.confirm(job_id, "order"))
    assert queue.text_of(queue.order(a)) == first
    assert not queue.is_shown(queue.button(b, "undo-run-now"))
    queue.click(queue.button(b, "move-up"))
    queue.click(queue.confirm_button(b, "order"))
    queue.wait_for_text(queue.order(b), first)
    queue.wait_for_text(queue.checks(a), "1 needs fixing")
    assert "20-0995_a.jpg" in queue.text_of(queue.COLLISIONS)
    theirs.wait_for_text(theirs.checks(a), "1 needs fixing")
    assert "20-0995_a.jpg" in theirs.text_of(theirs.COLLISIONS)
    assert theirs.is_shown(theirs.REORDER_WHY)
    assert not theirs.is_shown(theirs.REORDER)


@pytest.mark.after("test_a_move_that_would_fail_asks_first")
def test_reorder_to_avoid_failures(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2g, Reorder to avoid failures, step 1: it says what it will move; Cancel does nothing; Reorder puts A
    first again, and the box and the flag go."""
    queue = QueuePage(admin, base_url)
    a, b = made["A"], made["B"]
    queue.open_tab()
    queue.click(queue.REORDER)
    assert queue.text_of(queue.REORDER_CONFIRM).startswith("This moves")
    queue.click(queue.REORDER_CANCEL)
    queue.wait_until_gone(queue.REORDER_CONFIRM)
    assert int(queue.text_of(queue.order(b))) < int(queue.text_of(queue.order(a)))
    queue.click(queue.REORDER)
    queue.click(queue.REORDER_CONFIRM_BTN)
    queue.wait_for_text(queue.MESSAGE, "Reordered the queue to avoid failures.")
    queue.wait_until_gone(queue.COLLISIONS)
    assert int(queue.text_of(queue.order(a))) < int(queue.text_of(queue.order(b)))
    queue.wait_until(lambda d: "needs fixing" not in queue.text_of(queue.checks(a)))


@pytest.mark.after("test_reorder_to_avoid_failures")
def test_run_now_anyway_and_the_run(admin: WebDriver, base_url: str, paused: None) -> None:
    """Section 2g, Reorder to avoid failures, steps 2 and 3: "Run now anyway" on B leaves a box saying a reorder
    can't fix it, naming the Run now, and B keeps its Run now. Left that way and run, B completes and A needs
    attention, its document Failed with "Object already exists"."""
    queue, finished = QueuePage(admin, base_url), FinishedPage(admin, base_url)
    a, b = made["A"], made["B"]
    queue.open_tab()
    queue.click(queue.button(b, "run-now"))
    queue.click(queue.confirm_button(b, "order"))
    queue.wait_for_text(queue.REMAINING, "Reordering the queue can’t fix this")
    assert "Run now" in queue.text_of(queue.REMAINING)
    queue.wait_for(queue.button(b, "undo-run-now"))
    queue.resume()
    assert finished.wait_for_outcome(b) == "Completed"
    assert finished.wait_for_outcome(a) == "Needs attention"
    finished.click(finished.button(a, "view-results"))
    assert finished.text_of(finished.result(1, "state")) == "Failed"
    assert "Object already exists" in finished.text_of(finished.result(1, "what"))
    for job_id in (made["C"], made["E"]):
        assert finished.wait_for_outcome(job_id) == "Completed"
