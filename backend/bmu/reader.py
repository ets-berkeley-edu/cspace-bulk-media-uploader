"""The read-only service account that checks an intern's drafts (design: Roles, The read-only service account).

An intern's CollectionSpace account has no permissions, so an intern can't sign in to CollectionSpace and browse
records or images. The lookups an intern's draft needs (is the object there, is it protected, does a Media record
with this identification number exist, authority terms, vocabularies, dates) are made with one dedicated
CollectionSpace account per tenant, whose role (BMU_Reader) can read and nothing else.

This is the one exception to the rule that the BMU uses only the signed-in user's own credentials and stores none:
- In AWS the account's user name and password are a secret in AWS Secrets Manager (BMU_READER_SECRET_ID), which
  only the web app's task role may read. They are fetched when needed and kept in memory for a few minutes, so a
  changed password takes effect without a restart. They are never written to a table, a file or a log.
- Locally they come from BMU_READER_USER and BMU_READER_PASSWORD (the simulator's "bmureader").
- It is used only for an intern's checks. Staff use their own sign-in for everything, and every write to
  CollectionSpace is made with the submitting staff member's credentials.
- Each intern's use is counted and logged, and limited per hour, so the BMU can't be used to trawl CollectionSpace.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from .config import Settings
from .cspace import CSpaceClient, CSpaceError

log = logging.getLogger("bmu.reader")

# The permission flags (Permissions.summary) that are about reading: for an intern they are the reader's
READ_FLAGS = ("readObjects", "readMedia", "readPersons", "readOrgs", "readDates", "authorities")


def ensure_logged() -> None:
    """Each intern's use of the account must reach the logs. Under uvicorn nothing below WARNING is written unless
    logging was configured, so this logger gets INFO and, if no handler would write it, one of its own."""
    log.setLevel(logging.INFO)
    if not log.handlers and not logging.getLogger().handlers:
        from . import logsafe
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
        logsafe.protect(handler)
        log.addHandler(handler)


class ReaderUnavailable(Exception):
    """The reader account can't be used now: its secret can't be read, or CollectionSpace refuses its sign-in."""


class ReaderLimit(Exception):
    """This intern has made more lookups in the past hour than the BMU allows."""


class Reader:
    def __init__(self, settings: Settings, client_factory: Callable[[str, str], CSpaceClient],
                 fetch_secret: Callable[[str], str] | None = None, clock: Callable[[], float] = time.time):
        self.settings = settings
        self.client_factory = client_factory
        self._fetch_secret = fetch_secret or self._from_secrets_manager
        self._clock = clock
        self._credentials: tuple[float, tuple[str, str]] | None = None
        self._perms: tuple[float, dict[str, bool]] | None = None
        self._used: dict[str, tuple[float, int]] = {}  # intern -> (start of their hour, lookups in it)

    # ---- the account ----------------------------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        s = self.settings
        return bool(s.reader_secret_id or (s.reader_user and s.reader_password))

    def _from_secrets_manager(self, secret_id: str) -> str:
        import boto3  # only where a secret is configured
        return boto3.client("secretsmanager", region_name=self.settings.aws_region).get_secret_value(SecretId=secret_id)["SecretString"]

    def _fresh(self, kept: tuple[float, Any] | None) -> bool:
        return kept is not None and self._clock() - kept[0] < self.settings.reader_cache_seconds

    def credentials(self) -> tuple[str, str]:
        """The account's user name and password, kept in memory for reader_cache_seconds."""
        if self._fresh(self._credentials):
            return self._credentials[1]  # type: ignore[index]
        s = self.settings
        if s.reader_secret_id:
            try:
                secret = json.loads(self._fetch_secret(s.reader_secret_id))
                pair = (str(secret["username"]), str(secret["password"]))
            except Exception as e:  # not found, not allowed, not JSON, a key missing: never the secret's text
                log.error("the reader account's secret can't be used (%s)", e.__class__.__name__)
                raise ReaderUnavailable("its secret can't be read") from None
            if not all(pair):
                raise ReaderUnavailable("its secret has no user name or password yet")
        elif s.reader_user and s.reader_password:
            pair = (s.reader_user, s.reader_password)
        else:
            raise ReaderUnavailable("it isn't set up")
        self._credentials = (self._clock(), pair)
        return pair

    def forget(self) -> None:
        """Drop what is kept in memory, so the next use fetches the secret again (after a refused sign-in)."""
        self._credentials = self._perms = None

    def perms(self) -> dict[str, bool]:
        """What the reader account may read, as Permissions.summary flags; kept like the credentials."""
        if self._fresh(self._perms):
            return self._perms[1]  # type: ignore[index]
        client = self.client_factory(*self.credentials())
        try:
            summary = client.account_permissions().summary
        except CSpaceError as e:
            raise self.refused(e) from None
        finally:
            client.close()
        self._perms = (self._clock(), {k: bool(summary.get(k)) for k in READ_FLAGS})
        return self._perms[1]

    def refused(self, e: CSpaceError) -> ReaderUnavailable:
        """What a failed request with the reader account means for the intern who is waiting."""
        if e.code in ("auth", "forbidden"):
            self.forget()  # the password may have been changed: read the secret again next time
            log.error("CollectionSpace refused the reader account (%s)", e.code)
            return ReaderUnavailable("CollectionSpace refused its sign-in")
        return ReaderUnavailable("CollectionSpace isn't responding")

    # ---- an intern's use of it --------------------------------------------------------------------------------
    def _count(self, user: str) -> None:
        t = self._clock()
        start, n = self._used.get(user, (t, 0))
        if t - start >= 3600:
            start, n = t, 0
        if n >= self.settings.reader_lookups_per_hour:
            log.warning("reader: %s reached the limit of %d lookups an hour", user, self.settings.reader_lookups_per_hour)
            raise ReaderLimit(user)
        self._used[user] = (start, n + 1)

    def client(self, user: str, what: str) -> CSpaceClient:
        """A CollectionSpace client signed in as the reader account, for this intern's request. Every request it
        makes counts toward the intern's hourly limit; closing it logs how many it made, and for what."""
        client = self.client_factory(*self.credentials())
        made = {"n": 0}

        def before(method: str, path: str) -> None:
            self._count(user)
            made["n"] += 1
        client.on_request = before
        close = client.close

        def closing() -> None:
            if made["n"]:
                log.info("reader: %s made %d lookups (%s)", user, made["n"], what)
            close()
        client.close = closing  # type: ignore[method-assign]
        return client


# ---- what an intern is shown --------------------------------------------------------------------------------------
# Design (Roles): an intern gets minimal answers. Whether an object was found and whether a file is protected, yes;
# why it is protected, the object's access notes and the records' CSIDs, no: those come from records the intern
# has no permission to read. Rows are stored in full, for staff; an intern's copy is cut down as it is sent.
PROTECTED_REASON = "marked sensitive in CollectionSpace"
SOFT_SIGNAL = "a note about access in CollectionSpace"


def minimal(payload: Any) -> Any:
    """Cut every document row in an API answer down to what an intern may see, in place. A row is recognized by
    its number and its checks."""
    if isinstance(payload, list):
        for item in payload:
            minimal(item)
    elif isinstance(payload, dict):
        if "n" in payload and "checks" in payload:
            _minimal_row(payload)
        else:
            for value in payload.values():
                minimal(value)
    return payload


def _minimal_row(row: dict) -> None:
    swaps: list[tuple[str, str]] = []
    protected = row.get("protected")
    if isinstance(protected, dict) and protected.get("reason"):
        swaps.append((protected["reason"], PROTECTED_REASON))
        protected["reason"] = PROTECTED_REASON
    signals = row.get("softSignals") or []
    if signals:
        swaps.append((", ".join(signals), SOFT_SIGNAL))
        row["softSignals"] = [SOFT_SIGNAL]
    for check in row.get("checks") or []:
        for old, new in swaps:
            check["text"] = str(check.get("text", "")).replace(old, new)
    lookups = row.get("lookups")
    if isinstance(lookups, dict):
        lookups.pop("objectSensitivity", None)  # the Object's sensitivity fields, as read
        for found in lookups.values():
            if isinstance(found, dict) and "csids" in found:
                found["csids"] = ["" for _ in found["csids"]]  # how many were found, not which
