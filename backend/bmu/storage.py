"""DynamoDB and S3 access.

Tables (prefix configurable):
  <p>-jobs         PK=JOB#<id>, SK=META | ROW#<00001>; GSI "tenant" on (tenant, created) for job lists.
                   Also PK=LOCK#<tenant>, SK=LOCK: the one-job-per-tenant run lock.
  <p>-sessions     PK=<hash of session id>; TTL attribute "expires".
  <p>-credentials  PK=JOB#<id>; the job's encrypted password; TTL attribute "expires".
  <p>-audit        PK=TENANT#<tenant>, SK=<time>#<id>.
Rows are separate items so a 1,000-row job never approaches the 400 KB item limit.
"""
from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any, Iterator

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectionClosedError, EndpointConnectionError

from .config import Settings


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
        if not item or _clean(item).get("expires", 0) < now():
            return None
        return _clean(item)

    def update_session_perms(self, key: str, perms: dict) -> None:
        self.sessions.update_item(Key={"PK": key}, UpdateExpression="SET perms = :p",
                                  ExpressionAttributeValues={":p": perms}, ConditionExpression="attribute_exists(PK)")

    def delete_session(self, key: str) -> None:
        self.sessions.delete_item(Key={"PK": key})

    # ---- jobs and rows ------------------------------------------------------------------
    def create_job(self, tenant: str, user: str, name: str) -> dict:
        job = {"id": uuid.uuid4().hex[:12], "tenant": tenant, "name": name, "status": "Draft",
               "createdBy": user, "created": now(), "updated": now(), "rowCount": 0, "nextRow": 1, "run": 0}
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

    def add_rows(self, job_id: str, rows: list[dict]) -> list[dict]:
        """Append rows, numbering them after the job's existing rows."""
        r = self.jobs.update_item(Key={"PK": f"JOB#{job_id}", "SK": "META"},
                                  UpdateExpression="SET nextRow = nextRow + :n, rowCount = rowCount + :n",
                                  ExpressionAttributeValues={":n": len(rows)}, ReturnValues="UPDATED_OLD")
        first = int(r["Attributes"]["nextRow"])
        out = []
        with self.jobs.batch_writer() as bw:
            for i, row in enumerate(rows):
                row = {**row, "n": first + i}
                bw.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "SK": f"ROW#{row['n']:05d}", **row}))
                out.append(row)
        return out

    def get_rows(self, job_id: str) -> list[dict]:
        out: list[dict] = []
        kw: dict[str, Any] = dict(KeyConditionExpression=Key("PK").eq(f"JOB#{job_id}") & Key("SK").begins_with("ROW#"))
        while True:
            r = self.jobs.query(**kw)
            out += [_strip(_clean(i)) for i in r["Items"]]
            if "LastEvaluatedKey" not in r:
                return out
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def get_row(self, job_id: str, n: int) -> dict | None:
        item = self.jobs.get_item(Key={"PK": f"JOB#{job_id}", "SK": f"ROW#{n:05d}"}).get("Item")
        return _strip(_clean(item)) if item else None

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

    def save_checks(self, job_id: str, row: dict) -> bool:
        """Save a row's checks and lookups only if its data hasn't changed since they were computed (same
        "v"); otherwise a newer save has re-checked it already. Doesn't bump the version."""
        old = int(row.get("v", 0))
        try:
            self.jobs.update_item(
                Key={"PK": f"JOB#{job_id}", "SK": f"ROW#{row['n']:05d}"},
                UpdateExpression="SET checks = :c, lookups = :l",
                ConditionExpression=(Attr("PK").exists() & Attr("v").not_exists()) if old == 0 else Attr("v").eq(old),
                ExpressionAttributeValues=_dyn({":c": row.get("checks", []), ":l": row.get("lookups", {})}))
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

    def release_lock(self, tenant: str, owner: str) -> None:
        try:
            self.jobs.delete_item(Key={"PK": f"LOCK#{tenant}", "SK": "LOCK"}, ConditionExpression=Attr("owner").eq(owner))
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    # ---- job credentials ------------------------------------------------------------------
    def put_credential(self, job_id: str, user: str, token: str, expires: float) -> None:
        self.credentials.put_item(Item=_dyn({"PK": f"JOB#{job_id}", "user": user, "token": token, "expires": int(expires)}))

    def get_credential(self, job_id: str) -> dict | None:
        item = self.credentials.get_item(Key={"PK": f"JOB#{job_id}"}).get("Item")
        if not item or _clean(item)["expires"] < now():
            return None
        return _clean(item)

    def delete_credential(self, job_id: str) -> None:
        self.credentials.delete_item(Key={"PK": f"JOB#{job_id}"})

    # ---- audit ------------------------------------------------------------------------------
    def audit(self, tenant: str, type_: str, user: str, job_id: str, detail: str, csids: list[dict] | None = None) -> None:
        t = now()
        self.audit_table.put_item(Item=_dyn({
            "PK": f"TENANT#{tenant}", "SK": f"{t:.6f}#{uuid.uuid4().hex[:6]}", "type": type_, "user": user,
            "job": job_id, "detail": detail, "csids": csids or [], "expires": int(t + 365 * 86400)}))

    def list_audit(self, tenant: str) -> list[dict]:
        r = self.audit_table.query(KeyConditionExpression=Key("PK").eq(f"TENANT#{tenant}"), ScanIndexForward=False)
        return [_clean(i) for i in r["Items"]]

    # ---- S3 staging -------------------------------------------------------------------------
    def presign_upload(self, key: str, max_bytes: int) -> dict:
        return self.s3_public.generate_presigned_post(
            Bucket=self.s.s3_bucket, Key=key,
            Conditions=[["content-length-range", 1, max_bytes]], ExpiresIn=3600)

    def head_object(self, key: str) -> dict | None:
        try:
            return self.s3.head_object(Bucket=self.s.s3_bucket, Key=key)
        except ClientError:
            return None

    def open_object(self, key: str, version_id: str | None = None):
        kw: dict[str, Any] = {"Bucket": self.s.s3_bucket, "Key": key}
        if version_id:
            kw["VersionId"] = version_id
        return self.s3.get_object(**kw)["Body"]

    def delete_object(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.s.s3_bucket, Key=key)


def _strip(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in ("PK", "SK")}


def iter_chunks(body, size: int = 1024 * 1024) -> Iterator[bytes]:
    while chunk := body.read(size):
        yield chunk
