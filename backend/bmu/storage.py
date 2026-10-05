"""DynamoDB and S3 access.

Tables (prefix configurable):
  <p>-jobs         PK=JOB#<id>, SK=META | ROW#<00001> | RUN#<00001> (one per run: the run history) |
                   FIX#<00001> (a row as it was before a Fix and reschedule changed it, kept so an abandoned fix
                   can be reverted); GSI "tenant" on (tenant, created) for job lists.
                   Also PK=LOCK#<tenant>, SK=LOCK: the one-job-per-tenant run lock, and PK=TENANT#<tenant>,
                   SK=SCHEDULE: the tenant's job schedule and pause (design: Job scheduling; see bmu.schedule).
  <p>-sessions     PK=<hash of session id>; TTL attribute "expires".
  <p>-credentials  PK=JOB#<id>; the job's encrypted password; TTL attribute "expires".
  <p>-audit        PK=TENANT#<tenant>, SK=<time>#<id>, and PK=CSID#<csid>, SK=CSID (the CSID index); TTL
                   attribute "expires" (365 days).
Rows are separate items so a 1,000-row job never approaches the 400 KB item limit.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Any, Iterable, Iterator

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectionClosedError, EndpointConnectionError

from .config import Settings

log = logging.getLogger("bmu.storage")


def _clean(v: Any) -> Any:
    """Convert DynamoDB Decimals back to int/float."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _dyn(v: Any) -> Any:
    """Convert floats to Decimal and drop empty strings inside maps (DynamoDB accepts them, but keep items small)."""
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _dyn(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dyn(x) for x in v]
    return v


def draft_expiry(job: dict | None, at: float) -> dict:
    """The job-item fields that set a draft's expiry to `at`. A fix of a job that has run keeps it in
    draftExpiresAt, which only the sweeper reads (it reverts the fix); every other draft in expiresAt (design:
    State rules, Abandoned fixes; Retention). The sweeper expires drafts and Completed jobs at expiresAt, writing
    the audit entry before it deletes anything (Worker.sweep_expired_drafts, sweep_completed). expiresAt is not a
    DynamoDB TTL attribute: a TTL on the jobs table, if enabled later, is only a backstop, on its own attribute
    set well after expiresAt, so it never deletes a job before the sweeper has audited it. A fix never has an
    expiresAt, so nothing expires the job it must return to Needs attention or Failed."""
    if (job or {}).get("fixFrom"):
        return {"draftExpiresAt": at, "expiresAt": None}
    return {"expiresAt": at, "draftExpiresAt": None}


def expiry_of(job: dict) -> float | None:
    """When a draft expires: draftExpiresAt for a fix (expiresAt on items saved before it existed), else expiresAt."""
    if job.get("fixFrom"):
        return job.get("draftExpiresAt") or job.get("expiresAt")
    return job.get("expiresAt")


class RowChanged(Exception):
    """A row was saved by someone else after it was read."""

    def __init__(self, n: int):
        super().__init__(f"Document {n} changed in the meantime.")
        self.n = n


def now() -> float:
    return time.time()


class Storage:
    def __init__(self, settings: Settings, dynamodb=None, s3=None, s3_public=None):
        self.s = settings
        cfg = Config(retries={"max_attempts": 5, "mode": "standard"})
        self.dynamodb = dynamodb or boto3.resource("dynamodb", region_name=settings.aws_region,
                                                   endpoint_url=settings.dynamodb_endpoint, config=cfg)
        self.s3 = s3 or boto3.client("s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint,
                                     config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        self.s3_public = s3_public or boto3.client(
            "s3", region_name=settings.aws_region,
            endpoint_url=settings.s3_public_endpoint or settings.s3_endpoint,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        p = settings.table_prefix
        self.jobs = self.dynamodb.Table(f"{p}-jobs")
        self.sessions = self.dynamodb.Table(f"{p}-sessions")
        self.credentials = self.dynamodb.Table(f"{p}-credentials")
        self.audit_table = self.dynamodb.Table(f"{p}-audit")

    # ---- setup (local development and tests) ------------------------------------------
    def create_tables(self, wait_seconds: float = 60) -> None:
        """Create the tables and bucket if missing. In docker compose the web app and the worker start
        together, possibly before DynamoDB Local and S3 accept connections, so keep retrying until then."""
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                return self._create_tables()
            except (EndpointConnectionError, ConnectionClosedError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)

    def _create_tables(self) -> None:
        p = self.s.table_prefix
        existing = {t.name for t in self.dynamodb.tables.all()}
        specs = [
            (f"{p}-jobs", [("PK", "S"), ("SK", "S"), ("tenant", "S"), ("created", "N")], [("PK", "HASH"), ("SK", "RANGE")],
             [{"IndexName": "tenant", "KeySchema": [{"AttributeName": "tenant", "KeyType": "HASH"},
                                                    {"AttributeName": "created", "KeyType": "RANGE"}],
               "Projection": {"ProjectionType": "ALL"}}]),
            (f"{p}-sessions", [("PK", "S")], [("PK", "HASH")], None),
            (f"{p}-credentials", [("PK", "S")], [("PK", "HASH")], None),
            (f"{p}-audit", [("PK", "S"), ("SK", "S")], [("PK", "HASH"), ("SK", "RANGE")], None),
        ]
        for name, attrs, keys, gsis in specs:
            if name in existing:
                continue
            kw: dict[str, Any] = dict(
                TableName=name, BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[{"AttributeName": a, "AttributeType": t} for a, t in attrs],
                KeySchema=[{"AttributeName": a, "KeyType": k} for a, k in keys])
            if gsis:
                kw["GlobalSecondaryIndexes"] = gsis
            try:
                self.dynamodb.create_table(**kw)
            except ClientError as e:  # the web app and the worker may both be creating it
                if e.response["Error"]["Code"] != "ResourceInUseException":
                    raise
            self.dynamodb.Table(name).wait_until_exists()
        # Sessions and saved sign-ins also expire through DynamoDB's TTL, a backstop to the worker's sweep. Audit
        # entries and the CSID index are kept 365 days by TTL alone (design: Retention and audit; _audit_item).
        for name in (f"{p}-sessions", f"{p}-credentials", f"{p}-audit"):
            try:
                self.dynamodb.meta.client.update_time_to_live(
                    TableName=name, TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires"})
            except ClientError:
                pass  # already enabled, or a local stand-in without TTL
        try:
            self.s3.head_bucket(Bucket=self.s.s3_bucket)
        except ClientError:
            kw = {"Bucket": self.s.s3_bucket}
            if self.s.aws_region != "us-east-1":
                kw["CreateBucketConfiguration"] = {"LocationConstraint": self.s.aws_region}
            try:
                self.s3.create_bucket(**kw)
            except ClientError as e:
                if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise
        # versioning lets the worker pin the exact version of each staged file
        try:
            self.s3.put_bucket_versioning(Bucket=self.s.s3_bucket, VersioningConfiguration={"Status": "Enabled"})
        except ClientError:
            pass  # some local S3 stand-ins don't support versioning; the worker then reads the latest version

    # ---- sessions -----------------------------------------------------------------------
    def put_session(self, key: str, item: dict) -> None:
        self.sessions.put_item(Item=_dyn({"PK": key, **item}))

    def get_session(self, key: str) -> dict | None:
        item = self.sessions.get_item(Key={"PK": key}).get("Item")
        if not item:
            return None
        if _clean(item).get("expires", 0) < now():
            self.end_session(key, _clean(item).get("tenant"))  # past the absolute limit: the encrypted password goes with it
            return None
        return _clean(item)

    def end_session(self, key: str, tenant: str | None) -> None:
        """Remove a session, however it ends (Sign out, the idle or absolute limit, the sweep), and stop its editing
        of any draft, so others can edit it without taking over (design: Drafts, Closing)."""
        if tenant:
            for job in self.list_jobs(tenant):
                if job.get("editingSession") == key:
                    self.close_draft(job["id"], key)
        self.delete_session(key)

    def sweep_sessions(self, idle_seconds: float) -> int:
        """Delete sessions past their absolute limit or idle too long, with their encrypted passwords (design:
        Sessions): an abandoned browser tab never comes back to trigger the check itself."""
        t, gone = now(), 0
        kw: dict[str, Any] = {"ProjectionExpression": "PK, expires, lastSeen, tenant"}
        while True:
            page = self.sessions.scan(**kw)
            for item in page.get("Items", []):
                it = _clean(item)
                last = it.get("lastSeen") or 0
                if it.get("expires", 0) < t or (last and t - last > idle_seconds):
                    self.end_session(it["PK"], it.get("tenant"))
                    gone += 1
            if "LastEvaluatedKey" not in page:
                return gone
            kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def update_session_perms(self, key: str, perms: dict) -> None:
        self.sessions.update_item(Key={"PK": key}, UpdateExpression="SET perms = :p",
                                  ExpressionAttributeValues={":p": perms}, ConditionExpression="attribute_exists(PK)")

    def update_session_role(self, key: str, role: str) -> None:
        """The session's BMU role, after the roles were read again (design: Roles)."""
        try:
            self.sessions.update_item(Key={"PK": key}, UpdateExpression="SET #r = :r", ExpressionAttributeNames={"#r": "role"},
                                      ExpressionAttributeValues={":r": role}, ConditionExpression="attribute_exists(PK)")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def touch_session(self, key: str, t: float) -> None:
        try:
            self.sessions.update_item(Key={"PK": key}, UpdateExpression="SET lastSeen = :t", ExpressionAttributeValues={":t": _dyn(t)},
                                      ConditionExpression=Attr("PK").exists())
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def delete_session(self, key: str) -> None:
        self.sessions.delete_item(Key={"PK": key})

    # ---- jobs and rows ------------------------------------------------------------------
    def create_job(self, tenant: str, user: str, name: str, session: str = "", draft_days: int = 30,
                   role: str = "staff") -> dict:
        """A new job is a draft, open for editing by the session that created it. It keeps who created it and
        their BMU role then, and starts open to interns only if an intern created it (design: Roles)."""
        t = now()
        job = {"id": uuid.uuid4().hex[:12], "tenant": tenant, "name": name, "status": "Draft",
               "createdBy": user, "createdByRole": role, "internOpen": role == "intern",
               "created": t, "updated": t, "rowCount": 0, "nextRow": 1, "run": 0,
               "lastSavedBy": user, "lastSavedAt": t, "expiresAt": t + draft_days * 86400}
        if session:
            job.update(editingBy=user, editingSession=session, editingSince=t, editingRole=role)
        self.jobs.put_item(Item=_dyn({"PK": f"JOB#{job['id']}", "SK": "META", **job}))
        return job

    def get_job(self, job_id: str) -> dict | None:
        item = self.jobs.get_item(Key={"PK": f"JOB#{job_id}", "SK": "META"}).get("Item")
        return _strip(_clean(item)) if item else None

    def list_jobs(self, tenant: str) -> list[dict]:
        out: list[dict] = []
        kw: dict[str, Any] = dict(IndexName="tenant", KeyConditionExpression=Key("tenant").eq(tenant), ScanIndexForward=False)
        while True:
            r = self.jobs.query(**kw)
            out += [_strip(_clean(i)) for i in r["Items"] if i["SK"] == "META"]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    # ---- drafts: one editor at a time (design: Drafts, scheduling and the job queue) ------------
    def open_draft(self, job_id: str, user: str, session: str, take_over_since: float | None = None,
                   role: str = "staff") -> bool:
        """Become the draft's editor: if nobody is editing it, if this session already is, or (take-over) if
        the editor is still the one the user was warned about (same editingSince). The editor's BMU role is kept
        beside their name, to tell whether an intern may take the draft over (design: Roles)."""
        cond = Attr("status").eq("Draft") & (Attr("editingSession").not_exists() | Attr("editingSession").eq(session))
        if take_over_since is not None:
            cond = Attr("status").eq("Draft") & (cond | Attr("editingSince").eq(_dyn(take_over_since)))
        try:
            self.jobs.update_item(
                Key={"PK": f"JOB#{job_id}", "SK": "META"}, ConditionExpression=cond,
                UpdateExpression="SET editingBy = :u, editingSession = :s, editingSince = :t, editingRole = :r",
                ExpressionAttributeValues=_dyn({":u": user, ":s": session, ":t": now(), ":r": role}))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def close_draft(self, job_id: str, session: str) -> None:
        """Stop editing (only the session that is editing can)."""
        try:
            self.jobs.update_item(Key={"PK": f"JOB#{job_id}", "SK": "META"}, ConditionExpression=Attr("editingSession").eq(session),
                                  UpdateExpression="REMOVE editingBy, editingSession, editingSince")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def mark_saved(self, job_id: str, user: str, session: str, draft_days: int, fix: bool = False) -> bool:
        """Every change to a draft is saved at once; this records who saved it last and restarts its expiry
        (a fix's in draftExpiresAt, see draft_expiry). Only for the session that is editing it."""
        t = now()
        field, other = ("draftExpiresAt", "expiresAt") if fix else ("expiresAt", "draftExpiresAt")
        try:
            self.jobs.update_item(Key={"PK": f"JOB#{job_id}", "SK": "META"}, ConditionExpression=Attr("editingSession").eq(session),
                                  UpdateExpression=f"SET lastSavedBy = :u, lastSavedAt = :t, {field} = :e, updated = :t REMOVE {other}",
                                  ExpressionAttributeValues=_dyn({":u": user, ":t": t, ":e": t + draft_days * 86400}))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def delete_job_and_files(self, job_id: str) -> list[dict]:
        """Delete a job with its rows, run history, fix copies and staged files. Returns the rows that were deleted."""
        rows = self.get_rows(job_id)
        keys = {r.get("s3Key") for r in rows} | {r.get("supersededKey") for r in rows} | {r.get("thumbKey") for r in rows}
        keys |= {r.get("s3Key") for r in self._items(job_id, "FIX#")}
        for k in keys - {None, ""}:
            self.delete_object(k)
        for prefix in ("ROW#", "RUN#", "FIX#"):
            for sk in self._keys(job_id, prefix):
                self.jobs.delete_item(Key={"PK": f"JOB#{job_id}", "SK": sk})
        self.delete_credential(job_id)
        self.jobs.delete_item(Key={"PK": f"JOB#{job_id}", "SK": "META"})
        return rows

    def _items(self, job_id: str, prefix: str) -> list[dict]:
        out: list[dict] = []
        kw: dict[str, Any] = dict(KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}") & Key("SK").begins_with(prefix))
        while True:
            r = self.jobs.query(**kw)
            out += [_strip(_clean(i)) for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def _keys(self, job_id: str, prefix: str) -> list[str]:
        out: list[str] = []
        kw: dict[str, Any] = dict(KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}") & Key("SK").begins_with(prefix),
                                  ProjectionExpression="SK")
        while True:
            r = self.jobs.query(**kw)
            out += [i["SK"] for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    # ---- run history (design: Job data model, Run items) --------------------------------------
    def put_run(self, job_id: str, run: dict) -> None:
        self.jobs.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "SK": f"RUN#{int(run['run']):05d}", **run}))

    def finish_run(self, tenant: str, job_id: str, run_item: dict, user: str, detail: str, csids: list[dict] | None,
                   **extra: Any) -> str:
        """Design (Job data model, Run items: "a pointer to the run's audit entry"): the finished run item and its
        "Run" audit entry are written in one DynamoDB transaction, the entry's key (SK) stored on the run item as
        auditKey. So a run is never finished without its entry, whatever stops the worker. A large run's per-row
        detail is written to S3 first (put_audit_detail) and the entry points to it. Raises if the transaction
        fails: the run then stays unfinished and the job Running, and the heartbeat check finishes it later.
        Returns the entry's key."""
        entry = self._audit_item(tenant, "Run", user, job_id, detail, csids, startedAt=run_item.get("startedAt"),
                                 endedAt=run_item.get("endedAt"), **extra)  # the entry outlives the run item
        item = _dyn({**run_item, "PK": f"JOB#{job_id}", "SK": f"RUN#{int(run_item['run']):05d}", "auditKey": entry["SK"]})
        self.dynamodb.meta.client.transact_write_items(TransactItems=[
            {"Put": {"TableName": self.jobs.name, "Item": item}},
            {"Put": {"TableName": self.audit_table.name, "Item": entry}}])
        return entry["SK"]

    def get_runs(self, job_id: str) -> list[dict]:
        """The job's runs, oldest first."""
        return self._items(job_id, "RUN#")

    # ---- fixing a job after a run: the rows as they were, so an abandoned fix can be reverted --------
    def save_fix_original(self, job_id: str, row: dict) -> None:
        """Keep a row as it was before a fix first changed it (only the first time; later changes keep it)."""
        try:
            self.jobs.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "SK": f"FIX#{row['n']:05d}", **row}),
                               ConditionExpression=Attr("PK").not_exists())
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def fix_originals(self, job_id: str) -> list[dict]:
        return self._items(job_id, "FIX#")

    def drop_fix_original(self, job_id: str, n: int) -> None:
        self.jobs.delete_item(Key={"PK": f"JOB#{job_id}", "SK": f"FIX#{n:05d}"})

    def drop_fix_originals(self, job_id: str) -> None:
        for sk in self._keys(job_id, "FIX#"):
            self.jobs.delete_item(Key={"PK": f"JOB#{job_id}", "SK": sk})

    def restore_row(self, job_id: str, row: dict) -> None:
        """Put back a row as it was (an abandoned fix), with a new version so no stale copy overwrites it."""
        current = self.get_row(job_id, row["n"])
        row = {**row, "v": int((current or row).get("v", 0)) + 1}
        self.jobs.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "SK": f"ROW#{row['n']:05d}", **row}))

    def heartbeat(self, job_id: str) -> None:
        """Mark a running job alive. Uses the low-level client, which is safe to call from the heartbeat thread."""
        self.jobs.meta.client.update_item(
            TableName=self.jobs.name, Key={"PK": {"S": f"JOB#{job_id}"}, "SK": {"S": "META"}},
            UpdateExpression="SET heartbeatAt = :t", ExpressionAttributeValues={":t": {"N": f"{now():.3f}"}})

    def update_job(self, job_id: str, fields: dict, expect_status: str | list[str] | None = None) -> bool:
        """Set fields on a job. With expect_status, only if the job is in that status (returns False otherwise)."""
        fields = {**fields, "updated": now()}
        names = {f"#{k}": k for k in fields}
        values = {f":{k}": _dyn(v) for k, v in fields.items()}
        kw: dict[str, Any] = dict(Key={"PK": f"JOB#{job_id}", "SK": "META"},
                                  UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                                  ExpressionAttributeNames=names, ExpressionAttributeValues=values)
        if expect_status is not None:
            allowed = [expect_status] if isinstance(expect_status, str) else expect_status
            kw["ConditionExpression"] = Attr("status").is_in(allowed)
        try:
            self.jobs.update_item(**kw)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def staging_key(self, job_id: str, n: int | str) -> str:
        """Design (Browser uploads): staging/<tenant>/<job-id>/<row>/<random-id>; the filename is never in the key."""
        part = f"{n:05d}" if isinstance(n, int) else n
        return f"staging/{self.s.tenant}/{job_id}/{part}/{uuid.uuid4().hex}"

    def add_rows(self, job_id: str, rows: list[dict]) -> list[dict]:
        """Append rows, numbering them after the job's existing rows, each with its staging key."""
        r = self.jobs.update_item(Key={"PK": f"JOB#{job_id}", "SK": "META"},
                                  UpdateExpression="SET nextRow = nextRow + :n, rowCount = rowCount + :n",
                                  ExpressionAttributeValues={":n": len(rows)}, ReturnValues="UPDATED_OLD")
        first = int(r["Attributes"]["nextRow"])
        out = []
        with self.jobs.batch_writer() as bw:
            for i, row in enumerate(rows):
                row = {**row, "n": first + i}
                row["s3Key"] = self.staging_key(job_id, row["n"])
                bw.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "SK": f"ROW#{row['n']:05d}", **row}))
                out.append(row)
        return out

    @staticmethod
    def _upgrade(row: dict) -> dict:
        """Rows saved before media type was repeating hold one string; it is now a list."""
        if isinstance(row.get("type"), str):
            row["type"] = [row["type"]] if row["type"] else []
        return row

    def get_rows(self, job_id: str) -> list[dict]:
        out: list[dict] = []
        kw: dict[str, Any] = dict(KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}") & Key("SK").begins_with("ROW#"))
        while True:
            r = self.jobs.query(**kw)
            out += [self._upgrade(_strip(_clean(i))) for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def get_row(self, job_id: str, n: int) -> dict | None:
        item = self.jobs.get_item(Key={"PK": f"JOB#{job_id}", "SK": f"ROW#{n:05d}"}).get("Item")
        return self._upgrade(_strip(_clean(item))) if item else None

    def put_row(self, job_id: str, row: dict, guard: bool = True) -> None:
        """Save a row's data and bump its version "v". Guarded: only if nobody saved it since it was read
        (RowChanged otherwise), so a stale copy never overwrites newer data. The worker, the only writer
        while a job runs, saves unguarded."""
        old = int(row.get("v", 0))
        row["v"] = old + 1
        kw: dict[str, Any] = {}
        if guard:
            kw["ConditionExpression"] = Attr("v").not_exists() if old == 0 else Attr("v").eq(old)
        try:
            self.jobs.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "SK": f"ROW#{row['n']:05d}", **row}), **kw)
        except ClientError as e:
            row["v"] = old
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise RowChanged(row["n"]) from None
            raise

    def put_rows_all_or_none(self, job_id: str, rows: list[dict], originals: list[dict]) -> None:
        """Save several edited rows, each guarded like put_row. If one changed since it was read, the rows
        already saved are put back as they were (originals, read with the rows) and RowChanged is raised,
        so a bulk change is never left half applied."""
        done: list[tuple[dict, dict]] = []
        try:
            for row, orig in zip(rows, originals):
                self.put_row(job_id, row)
                done.append((row, orig))
        except RowChanged:
            for row, orig in reversed(done):
                back = {**orig, "v": row["v"]}  # guarded on the version just written
                try:
                    self.put_row(job_id, back)
                except RowChanged:
                    pass  # changed again in the meantime: the newer save stands
            raise

    def clear_thumbnail(self, job_id: str, n: int) -> None:
        """Forget a row's stored thumbnail (already deleted from S3), whatever the job's state."""
        self.jobs.update_item(Key={"PK": f"JOB#{job_id}", "SK": f"ROW#{n:05d}"}, UpdateExpression="REMOVE thumbKey",
                              ConditionExpression=Attr("PK").exists())

    def save_checks(self, job_id: str, row: dict) -> bool:
        """Save a row's checks and lookups, and what they set automatically (the protected-file flag and the
        publish default it implies, and a renamed term's current refName), only if its data hasn't changed since they were computed (same "v");
        otherwise a newer save has re-checked it already. Doesn't bump the version."""
        old = int(row.get("v", 0))
        try:
            self.jobs.update_item(
                Key={"PK": f"JOB#{job_id}", "SK": f"ROW#{row['n']:05d}"},
                UpdateExpression="SET checks = :c, lookups = :l, #p = :p, softSignals = :w, restricted = :r, restrictedAuto = :a, thumbKey = :t, "
                                 "creator = :cr, contributor = :co, rightsHolder = :rh, #lg = :lg",
                ConditionExpression=(Attr("PK").exists() & Attr("v").not_exists()) if old == 0 else Attr("v").eq(old),
                ExpressionAttributeNames={"#p": "protected", "#lg": "language"},
                ExpressionAttributeValues=_dyn({":c": row.get("checks", []), ":l": row.get("lookups", {}), ":p": row.get("protected"),
                                                ":w": row.get("softSignals") or [], ":r": bool(row.get("restricted")),
                                                ":a": bool(row.get("restrictedAuto")), ":t": row.get("thumbKey"),
                                                ":cr": row.get("creator") or "", ":co": row.get("contributor") or "",
                                                ":rh": row.get("rightsHolder") or "", ":lg": row.get("language") or []}))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def delete_row(self, job_id: str, n: int) -> None:
        self.jobs.delete_item(Key={"PK": f"JOB#{job_id}", "SK": f"ROW#{n:05d}"})
        self.jobs.update_item(Key={"PK": f"JOB#{job_id}", "SK": "META"},
                              UpdateExpression="SET rowCount = rowCount - :one", ExpressionAttributeValues={":one": 1})

    # ---- one job per tenant: run lock with expiry (renewed by the worker's heartbeat) ----
    def acquire_lock(self, tenant: str, owner: str, seconds: int) -> bool:
        t = now()
        try:
            self.jobs.put_item(
                Item=_dyn({"PK": f"LOCK#{tenant}", "SK": "LOCK", "owner": owner, "until": t + seconds}),
                ConditionExpression=Attr("PK").not_exists() | Attr("until").lt(_dyn(t)) | Attr("owner").eq(owner))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def renew_lock(self, tenant: str, owner: str, seconds: int) -> None:
        """Extend the run lock this worker holds, from the heartbeat thread (low-level client: thread-safe)."""
        try:
            self.jobs.meta.client.put_item(
                TableName=self.jobs.name,
                Item={"PK": {"S": f"LOCK#{tenant}"}, "SK": {"S": "LOCK"}, "owner": {"S": owner}, "until": {"N": f"{now() + seconds:.3f}"}},
                ConditionExpression="attribute_not_exists(PK) OR #o = :o",
                ExpressionAttributeNames={"#o": "owner"}, ExpressionAttributeValues={":o": {"S": owner}})
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def clear_editing(self, job_id: str) -> None:
        """Nobody is editing the job any more (it left Drafts other than by scheduling)."""
        self.jobs.update_item(Key={"PK": f"JOB#{job_id}", "SK": "META"},
                              UpdateExpression="REMOVE editingBy, editingSession, editingSince")

    def release_lock(self, tenant: str, owner: str) -> None:
        try:
            self.jobs.delete_item(Key={"PK": f"LOCK#{tenant}", "SK": "LOCK"}, ConditionExpression=Attr("owner").eq(owner))
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    # ---- job credentials ------------------------------------------------------------------
    # ---- writes that must happen together (design: State rules; Deleting a row) ------------------------
    def _transact(self, items: list[dict]) -> bool:
        """Run a DynamoDB transaction: all of it or none. False if a condition failed. The resource's client
        takes plain Python values (it converts them itself), like the Table methods."""
        try:
            self.dynamodb.meta.client.transact_write_items(TransactItems=items)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("TransactionCanceledException", "ConditionalCheckFailedException"):
                return False
            raise

    def _job_update(self, job_id: str, fields: dict, condition: str, cond_values: dict, cond_names: dict | None = None) -> dict:
        fields = {**fields, "updated": now()}
        return {"Update": {
            "TableName": self.jobs.name, "Key": _dyn({"PK": f"JOB#{job_id}", "SK": "META"}),
            "UpdateExpression": "SET " + ", ".join(f"#f_{k} = :f_{k}" for k in fields),
            "ConditionExpression": condition,
            "ExpressionAttributeNames": {**{f"#f_{k}": k for k in fields}, **(cond_names or {})},
            "ExpressionAttributeValues": _dyn({**{f":f_{k}": v for k, v in fields.items()}, **cond_values})}}

    def queue_with_credential(self, job_id: str, user: str, token: str, expires: float, fields: dict,
                              statuses: list[str], session: str) -> bool:
        """Scheduling: store the job's encrypted sign-in and set it to Queued in one write, only if it is still in
        one of these statuses and still being edited by this session (design: State rules)."""
        allowed = ", ".join(f":c_s{i}" for i in range(len(statuses)))
        update = self._job_update(job_id, fields, f"#c_status IN ({allowed}) AND #c_ed = :c_ed",
                                  {**{f":c_s{i}": st for i, st in enumerate(statuses)}, ":c_ed": session},
                                  {"#c_status": "status", "#c_ed": "editingSession"})
        put = {"Put": {"TableName": self.credentials.name,
                       "Item": _dyn({"PK": f"JOB#{job_id}", "user": user, "token": token, "expires": int(expires)})}}
        return self._transact([put, update])

    def begin_delete(self, job_id: str, statuses: list[str], session: str, user: str = "") -> bool:
        """Start deleting a job (design: Deleting a job): in one write, set it to Deleting, only if it is still in
        one of these statuses and no other session is editing it, and delete its saved sign-in. From then on the
        worker can't claim it (claim_job needs Queued and a sign-in), so its files are never used by a run.
        deletedBy: who deleted it, for the audit entry if the sweep has to finish the deletion."""
        allowed = ", ".join(f":c_s{i}" for i in range(len(statuses)))
        update = self._job_update(job_id, {"status": "Deleting", "deletingSince": now(), "deletedBy": user},
                                  f"#c_status IN ({allowed}) AND (attribute_not_exists(#c_ed) OR #c_ed = :c_ed)",
                                  {**{f":c_s{i}": st for i, st in enumerate(statuses)}, ":c_ed": session},
                                  {"#c_status": "status", "#c_ed": "editingSession"})
        delete = {"Delete": {"TableName": self.credentials.name, "Key": _dyn({"PK": f"JOB#{job_id}"})}}
        return self._transact([update, delete])

    def claim_job(self, job_id: str, fields: dict) -> bool:
        """The worker claims a queued job, only if it is still Queued and not held (a staff member may have held it
        since the worker chose it; design: Job scheduling), and its sign-in is still stored and valid."""
        check = {"ConditionCheck": {"TableName": self.credentials.name, "Key": _dyn({"PK": f"JOB#{job_id}"}),
                                    "ConditionExpression": "attribute_exists(PK) AND #e > :now",
                                    "ExpressionAttributeNames": {"#e": "expires"}, "ExpressionAttributeValues": _dyn({":now": int(now())})}}
        update = self._job_update(job_id, fields, "#c_status = :c_q AND (attribute_not_exists(#c_h) OR attribute_type(#c_h, :c_null))",
                                  {":c_q": "Queued", ":c_null": "NULL"}, {"#c_status": "status", "#c_h": "held"})
        return self._transact([check, update])

    def delete_row_if_unchanged(self, job_id: str, row: dict, session: str, audit: dict | None = None) -> bool:
        """Delete a row that was checked as deletable, only if it hasn't changed since (same version) and the
        job is still a draft this session is editing (design: Deleting a row). audit: the entry that records the
        deletion ({"tenant", "type", "user", "detail"}), written in the same transaction, so there is one request
        per row and never a deletion without its entry."""
        v = int(row.get("v", 0))
        cond = "attribute_exists(PK) AND " + ("attribute_not_exists(#v)" if v == 0 else "#v = :v")
        delete = {"Delete": {"TableName": self.jobs.name, "Key": _dyn({"PK": f"JOB#{job_id}", "SK": f"ROW#{row['n']:05d}"}),
                             "ConditionExpression": cond, "ExpressionAttributeNames": {"#v": "v"},
                             **({"ExpressionAttributeValues": _dyn({":v": v})} if v else {})}}
        update = {"Update": {"TableName": self.jobs.name, "Key": _dyn({"PK": f"JOB#{job_id}", "SK": "META"}),
                             "UpdateExpression": "SET rowCount = rowCount - :one, #u = :t",
                             "ConditionExpression": "#s = :draft AND editingSession = :ed",
                             "ExpressionAttributeNames": {"#u": "updated", "#s": "status"},
                             "ExpressionAttributeValues": _dyn({":one": 1, ":t": now(), ":draft": "Draft", ":ed": session})}}
        entry = [{"Put": {"TableName": self.audit_table.name,
                          "Item": self._audit_item(audit["tenant"], audit["type"], audit["user"], job_id, audit["detail"], None)}}] if audit else []
        return self._transact([delete, update, *entry])

    def put_credential(self, job_id: str, user: str, token: str, expires: float) -> None:
        self.credentials.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "user": user, "token": token, "expires": int(expires)}))

    def get_credential(self, job_id: str) -> dict | None:
        item = self.credentials.get_item(Key={"PK": f"JOB#{job_id}"}).get("Item")
        if not item or _clean(item)["expires"] < now():
            return None
        return _clean(item)

    def delete_credential(self, job_id: str) -> None:
        self.credentials.delete_item(Key={"PK": f"JOB#{job_id}"})

    # ---- the tenant's job schedule (design: Job scheduling) -----------------------------------------
    def get_schedule(self, tenant: str) -> dict | None:
        """The stored schedule item, or None if it was never saved (bmu.schedule.normalize adds the defaults)."""
        item = self.jobs.get_item(Key={"PK": f"TENANT#{tenant}", "SK": "SCHEDULE"}).get("Item")
        return _strip(_clean(item)) if item else None

    def save_schedule(self, tenant: str, fields: dict, user: str) -> None:
        """Save the run days and times (validated by bmu.schedule.validate); the pause is kept as it is."""
        fields = {**fields, "updatedBy": user, "updatedAt": now()}
        self.jobs.update_item(Key={"PK": f"TENANT#{tenant}", "SK": "SCHEDULE"},
                              UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                              ExpressionAttributeNames={f"#{k}": k for k in fields},
                              ExpressionAttributeValues={f":{k}": _dyn(v) for k, v in fields.items()})

    def pause_queue(self, tenant: str, user: str, reason: str) -> bool:
        """Pause the tenant's queue, only if it isn't paused already (False then)."""
        try:
            self.jobs.update_item(Key={"PK": f"TENANT#{tenant}", "SK": "SCHEDULE"},
                                  UpdateExpression="SET #p = :p",
                                  ConditionExpression="attribute_not_exists(#p) OR attribute_type(#p, :null)",
                                  ExpressionAttributeNames={"#p": "paused"},
                                  ExpressionAttributeValues=_dyn({":p": {"by": user, "at": now(), "reason": reason}, ":null": "NULL"}))
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def resume_queue(self, tenant: str) -> dict | None:
        """Resume the tenant's queue; returns the pause it ended, or None if it wasn't paused."""
        try:
            r = self.jobs.update_item(Key={"PK": f"TENANT#{tenant}", "SK": "SCHEDULE"}, UpdateExpression="REMOVE #p",
                                      ConditionExpression="attribute_type(#p, :m)", ExpressionAttributeNames={"#p": "paused"},
                                      ExpressionAttributeValues={":m": "M"}, ReturnValues="UPDATED_OLD")
            return _clean(r["Attributes"]["paused"])
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    # ---- audit ------------------------------------------------------------------------------
    def _audit_item(self, tenant: str, type_: str, user: str, job_id: str, detail: str, csids: list[dict] | None,
                    **extra: Any) -> dict:
        t = now()
        return _dyn({"PK": f"TENANT#{tenant}", "SK": f"{t:.6f}#{uuid.uuid4().hex[:6]}", "type": type_, "user": user,
                     "job": job_id, "detail": detail, "csids": csids or [], "expires": int(t + 365 * 86400), **extra})

    def audit(self, tenant: str, type_: str, user: str, job_id: str, detail: str, csids: list[dict] | None = None,
              **extra: Any) -> None:
        self.audit_table.put_item(Item=self._audit_item(tenant, type_, user, job_id, detail, csids, **extra))

    def audit_once(self, tenant: str, job_id: str, status: str, flag: str, type_: str, user: str, detail: str,
                   csids: list[dict] | None = None, **extra: Any) -> bool:
        """An audit entry that must be written exactly once for a job in a temporary state (Deleting, Expiring),
        before the job is deleted: one transaction writes the entry and sets the job's flag, only if the job is
        still in that status and the flag isn't set. So an interrupted deletion that the sweep redoes, or the sweep
        and the web app overlapping, never writes it twice. False if it was written already."""
        put = {"Put": {"TableName": self.audit_table.name,
                       "Item": self._audit_item(tenant, type_, user, job_id, detail, csids, **extra)}}
        mark = self._job_update(job_id, {flag: True}, "#c_status = :c_st AND attribute_not_exists(#c_flag)",
                                {":c_st": status}, {"#c_status": "status", "#c_flag": flag})
        return self._transact([put, mark])

    def audit_job_deleted(self, tenant: str, job_id: str, user: str, detail: str, created: dict, **extra: Any) -> bool:
        """The "Job deleted" entry of a job being deleted (status Deleting), written before anything is deleted,
        with every CSID its runs created (created_records), or for a big job a pointer to them in S3. Written once
        (flag deleteAudited, see audit_once)."""
        csids = created["csids"]
        big = len(csids) > 500  # a 1,000-row job's CSIDs go in S3, the entry points to them
        if big:
            extra["detailKey"] = self.put_audit_detail(tenant, job_id, 0, csids)
        return self.audit_once(tenant, job_id, "Deleting", "deleteAudited", "Job deleted", user, detail,
                               [] if big else csids, counts=created["counts"], **extra)

    # ---- the CSID index (design: Job data model, CSID index entry; Reading the audit log) ------------
    def index_csid(self, tenant: str, csid: str, **entry: Any) -> None:
        """One item per record the BMU creates, written when it is created: which job, run, row and step made
        it. Answers "which BMU job created this record?" with one lookup, also after the job is deleted."""
        self.audit_table.put_item(Item=_dyn({"PK": f"CSID#{csid}", "SK": "CSID", "tenant": tenant, "at": now(),
                                             "expires": int(now() + 365 * 86400), **entry}))

    def find_csid(self, csid: str) -> dict | None:
        item = self.audit_table.get_item(Key={"PK": f"CSID#{csid}", "SK": "CSID"}).get("Item")
        return _strip(_clean(item)) if item else None

    def put_audit_detail(self, tenant: str, job_id: str, run: int, detail: Any) -> str:
        """Per-row detail of a large run, as a JSON object in S3 (a one-year lifecycle rule in AWS)."""
        import json
        key = f"audit/{tenant}/{job_id}/run-{run:03d}-{int(now())}.json"
        self.put_bytes(key, json.dumps(detail, default=str).encode(), "application/json")
        return key

    def list_audit(self, tenant: str) -> list[dict]:
        r = self.audit_table.query(KeyConditionExpression=Key("PK").eq(f"TENANT#{tenant}"), ScanIndexForward=False)
        return [_clean(i) for i in r["Items"]]

    # ---- S3 staging -------------------------------------------------------------------------
    def presign_upload(self, key: str, max_bytes: int, content_type: str = "") -> dict:
        """A write-only presigned POST for one key (design: Browser uploads, Sign): the exact key, a size range,
        the file's content type, SSE-KMS with the staging key when one is configured, about 15 minutes."""
        fields: dict[str, str] = {}
        conditions: list[Any] = [["content-length-range", 1, max_bytes]]
        if content_type:
            fields["Content-Type"] = content_type
            conditions.append({"Content-Type": content_type})
        if self.s.s3_kms_key_id:
            fields.update({"x-amz-server-side-encryption": "aws:kms", "x-amz-server-side-encryption-aws-kms-key-id": self.s.s3_kms_key_id})
            conditions += [{"x-amz-server-side-encryption": "aws:kms"},
                           {"x-amz-server-side-encryption-aws-kms-key-id": self.s.s3_kms_key_id}]
        return self.s3_public.generate_presigned_post(Bucket=self.s.s3_bucket, Key=key, Fields=fields, Conditions=conditions,
                                                      ExpiresIn=self.s.upload_url_seconds)

    def list_staged(self, prefix: str):
        """(key, last modified epoch) of every staged object under a prefix."""
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.s.s3_bucket, Prefix=prefix):
            for o in page.get("Contents", []):
                yield o["Key"], o["LastModified"].timestamp()

    def head_object(self, key: str) -> dict | None:
        try:
            return self.s3.head_object(Bucket=self.s.s3_bucket, Key=key)
        except ClientError:
            return None

    def read_head(self, key: str, version_id: str | None, n: int) -> bytes:
        """The first n bytes of a staged file (a ranged GET)."""
        kw: dict[str, Any] = {"Bucket": self.s.s3_bucket, "Key": key, "Range": f"bytes=0-{n - 1}"}
        if version_id:
            kw["VersionId"] = version_id
        return self.s3.get_object(**kw)["Body"].read()

    def open_object(self, key: str, version_id: str | None = None):
        kw: dict[str, Any] = {"Bucket": self.s.s3_bucket, "Key": key}
        if version_id:
            kw["VersionId"] = version_id
        return self.s3.get_object(**kw)["Body"]

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.s3.put_object(Bucket=self.s.s3_bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.s.s3_bucket, Key=key)["Body"].read()
        except ClientError:
            return None

    def store_thumbnail(self, job_id: str, n: int, jpeg: bytes, attempts: int = 5) -> bool:
        """Store a row's thumbnail and record its key on the row (re-reading the row if it changed meanwhile).
        Never for a protected row. Returns False if the row is gone or protected."""
        from .thumbnails import thumb_key
        key = thumb_key(self.s.tenant, job_id, n)
        self.put_bytes(key, jpeg, "image/jpeg")
        for _ in range(attempts):
            row = self.get_row(job_id, n)
            if not row or row.get("protected"):
                break
            old = row.get("thumbKey")
            row["thumbKey"] = key
            try:
                self.put_row(job_id, row)
            except RowChanged:
                continue
            if old:
                self.delete_object(old)
            return True
        self.delete_object(key)
        return False

    def delete_object(self, key: str) -> None:
        """Delete an object for good (design: Protected files, Cleanup). The bucket is versioned, so a plain delete
        would only hide the file behind a delete marker; this removes every version and marker of the key. If the
        versions can't be listed, it falls back to the plain delete, and the bucket's lifecycle rule removes the
        hidden version within a day."""
        try:
            pages = self.s3.get_paginator("list_object_versions").paginate(Bucket=self.s.s3_bucket, Prefix=key)
            versions = [v["VersionId"] for page in pages for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
                        if v["Key"] == key]
        except ClientError:
            log.warning("could not list the versions of a staged object; deleting its current version only")
            versions = []
        if not versions:
            self.s3.delete_object(Bucket=self.s.s3_bucket, Key=key)
        for version in versions:
            self.s3.delete_object(Bucket=self.s.s3_bucket, Key=key, VersionId=version)

    def delete_objects(self, keys: Iterable[str | None]) -> None:
        """Delete several objects of one job for good, in a few requests whatever their number (deleting many
        documents at once): one listing of the versions under the keys' common prefix, then S3's batch delete, 1,000
        versions at a time. A handful of keys, or keys without a job's prefix in common, go one by one (delete_object),
        and so does anything the listing or the batch delete couldn't do."""
        wanted = sorted({k for k in keys if k})
        prefix = os.path.commonprefix(wanted)
        if len(wanted) <= 3 or prefix.count("/") < 3:  # staging/<tenant>/<job-id>/
            for key in wanted:
                self.delete_object(key)
            return
        try:
            pages = self.s3.get_paginator("list_object_versions").paginate(Bucket=self.s.s3_bucket, Prefix=prefix)
            found = [(v["Key"], v["VersionId"]) for page in pages for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
                     if v["Key"] in set(wanted)]
        except ClientError:
            log.warning("could not list the versions of staged objects; deleting them one by one")
            for key in wanted:
                self.delete_object(key)
            return
        targets = [{"Key": k, "VersionId": v} for k, v in found]
        targets += [{"Key": k} for k in set(wanted) - {k for k, _ in found}]  # none listed: a plain delete, as delete_object
        for i in range(0, len(targets), 1000):
            r = self.s3.delete_objects(Bucket=self.s.s3_bucket, Delete={"Objects": targets[i:i + 1000], "Quiet": True})
            for failed in {e["Key"] for e in r.get("Errors", [])}:
                self.delete_object(failed)  # raises if it really can't be deleted


    # ---- Demo tools only (bmu.demo): never called in production ------------------------------------------
    def wipe_everything(self) -> dict:
        """Delete everything the BMU holds except who is signed in: every job with its documents and runs, the
        saved sign-ins of queued jobs, the job schedule (which returns to its defaults), the audit log with its
        CSID index, and every object in the bucket (staged files, thumbnails, audit files; all versions). Nothing
        in CollectionSpace is touched. Returns how many items and objects were deleted."""
        counts = {"items": 0, "objects": 0}
        for table, keys in ((self.jobs, ("PK", "SK")), (self.credentials, ("PK",)), (self.audit_table, ("PK", "SK"))):
            kw: dict[str, Any] = {"ProjectionExpression": ", ".join(keys)}
            with table.batch_writer() as batch:
                while True:
                    page = table.scan(**kw)
                    for item in page["Items"]:
                        batch.delete_item(Key={k: item[k] for k in keys})
                        counts["items"] += 1
                    if "LastEvaluatedKey" not in page:
                        break
                    kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        pages = self.s3.get_paginator("list_object_versions").paginate(Bucket=self.s.s3_bucket)
        found = [{"Key": v["Key"], "VersionId": v["VersionId"]} for page in pages
                 for v in page.get("Versions", []) + page.get("DeleteMarkers", [])]
        for i in range(0, len(found), 1000):
            self.s3.delete_objects(Bucket=self.s.s3_bucket, Delete={"Objects": found[i:i + 1000], "Quiet": True})
        counts["objects"] = len(found)
        return counts


def _strip(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("PK", "SK")}


def iter_chunks(body, size: int = 1024 * 1024) -> Iterator[bytes]:
    while chunk := body.read(size):
        yield chunk
