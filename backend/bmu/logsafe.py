"""Keeps sign-ins out of the logs (design: Authentication, credentials and authorization: "Logs scrub Authorization
headers and request objects in tracebacks"). The code never hands a password to anything that logs it; this is the
backstop for the mistake nobody has made yet. It works on the finished log line, so tracebacks are covered too."""
import logging
import re

REMOVED = "[removed]"
_VALUE = r"[^\s'\",)}\]]+"
_PATTERNS = [
    # Authorization: Basic dXNlcjpwYXNz   'Authorization': 'Basic dXNlcjpwYXNz'   authorization=Bearer abc
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(?:(?:basic|bearer)\s+)?" + _VALUE), r"\1" + REMOVED),
    # a bare "Basic <token>": only when the next word looks like a token (a digit, =, + or /, or a capital letter
    # after its first character), so "basic checks" and "Basic Authentication" are left alone
    (re.compile(r"\b([Bb]asic|[Bb]earer)\s+(?=\S[A-Za-z0-9+/=_.-]*[A-Z0-9+/=])[A-Za-z0-9+/=_.-]{8,}"), r"\1 " + REMOVED),
    # password=..., "password": "...", passwd: ...
    (re.compile(r"(?i)((?:password|passwd|pwd)['\"]?\s*[:=]\s*['\"]?)" + _VALUE), r"\1" + REMOVED),
    # https://user:secret@host
    (re.compile(r"(?i)(https?://[^/\s:@]+:)[^@\s/]+@"), r"\1" + REMOVED + "@"),
]


def scrub(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class ScrubbingFormatter(logging.Formatter):
    """Formats a record with the handler's own formatter, then scrubs the whole line, traceback included."""

    def __init__(self, inner: logging.Formatter | None = None):
        super().__init__()
        self.inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return scrub(self.inner.format(record))


def protect(handler: logging.Handler) -> None:
    if not isinstance(handler.formatter, ScrubbingFormatter):
        handler.setFormatter(ScrubbingFormatter(handler.formatter))


def install() -> None:
    """Scrub every handler in use: the root logger's, uvicorn's own, and the one Python falls back to when a logger
    has none. Call it after logging is configured (the worker's main, the web app's creation)."""
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            protect(handler)
    if logging.lastResort is not None:
        protect(logging.lastResort)
