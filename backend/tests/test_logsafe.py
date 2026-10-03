"""Sign-ins never reach the logs (design: Authentication, credentials and authorization), whatever is logged."""
import io
import logging

import pytest

from bmu import logsafe


@pytest.mark.parametrize("line,secret", [
    ("request failed: Authorization: Basic dXNlcjpodW50ZXIy", "dXNlcjpodW50ZXIy"),
    ("headers={'Authorization': 'Basic dXNlcjpodW50ZXIy', 'Accept': 'application/xml'}", "dXNlcjpodW50ZXIy"),
    ("retrying with Bearer abc.def-123456", "abc.def-123456"),
    ('body {"userid": "staff@museum.example", "password": "hunter2!"}', "hunter2!"),
    ("login(user='staff', password='hunter2!')", "hunter2!"),
    ("GET https://staff:hunter2@pahma.example/cspace-services/media", "hunter2@"),
])
def test_scrub_removes_credentials_and_keeps_the_rest(line, secret):
    out = logsafe.scrub(line)
    assert secret not in out and logsafe.REMOVED in out
    assert out.split()[0] == line.split()[0]  # the line is still readable


def test_ordinary_lines_are_untouched():
    for line in ("run 3 of job 4f2a: 12 done, 1 failed", "GET media?as=... 200 in 0.4s", "basic checks passed",
                 "Basic Authentication is the only sign-in CollectionSpace supports"):
        assert logsafe.scrub(line) == line


def test_a_traceback_is_scrubbed_too():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logsafe.protect(handler)
    logsafe.protect(handler)  # twice changes nothing
    log = logging.getLogger("bmu.test-logsafe")
    log.addHandler(handler)
    log.propagate = False
    try:
        try:
            raise RuntimeError("request <Request headers={'authorization': 'Basic dXNlcjpodW50ZXIy'}> failed")
        except RuntimeError:
            log.exception("job stopped, password=hunter2!")
    finally:
        log.removeHandler(handler)
    out = stream.getvalue()
    assert "dXNlcjpodW50ZXIy" not in out and "hunter2" not in out
    assert "ERROR bmu.test-logsafe job stopped" in out and "RuntimeError" in out and "Traceback" in out


def test_install_covers_the_handlers_in_use():
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        logsafe.install()
        assert isinstance(handler.formatter, logsafe.ScrubbingFormatter)
        assert isinstance(logging.lastResort.formatter, logsafe.ScrubbingFormatter)
    finally:
        root.removeHandler(handler)
