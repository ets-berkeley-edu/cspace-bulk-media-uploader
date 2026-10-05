"""The AWS deployment (deploy/) agrees with the app: the Terraform configuration creates the tables the app uses
(the same keys, index and TTL as Storage.create_tables makes locally), sets only settings that exist, keeps Demo
tools off, and runs the web app and the worker the way the image expects. Terraform's own checks (terraform validate,
terraform test) cover the configuration itself (deploy/README.md)."""
import re
from pathlib import Path

import boto3
import hcl2
import pytest
from moto import mock_aws

from bmu import app as appmod
from bmu.config import Settings
from bmu.storage import Storage

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
APP = DEPLOY / "terraform" / "app"


def _plain(v):
    """python-hcl2 keeps string literals in their quotes ('"PK"'); strip them, through lists and maps."""
    if isinstance(v, str):
        return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {_plain(k): _plain(x) for k, x in v.items() if not str(k).startswith("__")}
    return v


def _tf(name: str) -> dict:
    return _plain(hcl2.loads((APP / name).read_text()))


def _local(name: str, key: str):
    return next(block[key] for block in _tf(name)["locals"] if key in block)


def _blocks(name: str, kind: str, type_: str) -> dict:
    """{resource name: body} for every `kind "type_" "name"` block in the file."""
    return {n: body for block in _tf(name).get(kind, []) for t, named in block.items() if t == type_ for n, body in named.items()}


def test_terraform_creates_the_tables_the_app_uses():
    with mock_aws():
        storage = Storage(Settings(table_prefix="bmu-dev", s3_bucket="bmu-x", aws_region="us-west-2", _env_file=None))
        storage.create_tables()
        client = boto3.client("dynamodb", region_name="us-west-2")
        local = {}
        for name in client.list_tables()["TableNames"]:
            t = client.describe_table(TableName=name)["Table"]
            keys = {k["KeyType"]: k["AttributeName"] for k in t["KeySchema"]}
            gsis = t.get("GlobalSecondaryIndexes", [])
            ttl = client.describe_time_to_live(TableName=name)["TimeToLiveDescription"]
            local[name.removeprefix("bmu-dev-")] = {
                "hash_key": keys["HASH"], "range_key": keys.get("RANGE"),
                "attributes": {a["AttributeName"]: a["AttributeType"] for a in t["AttributeDefinitions"]},
                "gsi": {"name": gsis[0]["IndexName"], **{("hash_key" if k["KeyType"] == "HASH" else "range_key"): k["AttributeName"]
                                                         for k in gsis[0]["KeySchema"]}} if gsis else None,
                "ttl": ttl.get("TimeToLiveStatus") == "ENABLED" and ttl.get("AttributeName") == "expires",
            }
    tables = _local("dynamodb.tf", "tables")
    assert {name: {k: v for k, v in t.items() if k != "pitr"} for name, t in tables.items()} == local
    # design: no backups of passwords, even encrypted
    assert {name: t["pitr"] for name, t in tables.items()} == {"jobs": True, "audit": True, "sessions": False, "credentials": False}
    resource = _blocks("dynamodb.tf", "resource", "aws_dynamodb_table")["main"]
    assert resource["name"] == "${local.name}-${each.key}" and resource["billing_mode"] == "PAY_PER_REQUEST"
    assert 'attribute_name = "expires"' in (APP / "dynamodb.tf").read_text()  # the attribute Storage sets


def test_containers_set_only_real_settings_and_never_demo():
    env = _local("ecs.tf", "app_environment")
    fields = set(Settings.model_fields)
    for name in env:
        assert name.startswith("BMU_") and name[4:].lower() in fields, name
    assert env["BMU_DEMO"] == "false" and env["BMU_CRYPTO_MODE"] == "kms" and env["BMU_COOKIE_SECURE"] == "true"
    assert {"BMU_KMS_SESSION_KEY_ID", "BMU_KMS_JOB_KEY_ID", "BMU_S3_KMS_KEY_ID", "BMU_S3_BUCKET"} <= set(env)
    assert "BMU_CREATE_TABLES" not in env and "BMU_SESSION_KEY_B64" not in env  # tables and keys come from Terraform
    assert env["BMU_TABLE_PREFIX"] == "${local.name}"  # the tables are named ${local.name}-<table>
    source = (APP / "ecs.tf").read_text()
    web, worker = (source[source.index(f'resource "aws_ecs_task_definition" "{n}"'):] for n in ("web", "worker"))
    web = web[:web.index('resource "aws_ecs_task_definition" "worker"')]
    assert 'command     = ["python", "-m", "bmu.worker"]' in worker and "command" not in web.split("container_definitions")[1]
    assert "containerPort = 8000" in web  # the image's CMD: uvicorn on port 8000
    assert web.count("environment  = local.container_environment") == 1 and "environment = local.container_environment" in worker


def test_the_load_balancer_checks_a_route_the_app_has():
    path = _blocks("alb.tf", "resource", "aws_lb_target_group")["web"]["health_check"][0]["path"]
    assert path == "/api/health" and f'@app.get("{path}")' in Path(appmod.__file__).read_text()


def test_key_policies_follow_the_design():
    docs = _blocks("kms.tf", "data", "aws_iam_policy_document")

    def grants(doc):
        return {s["principals"][0]["identifiers"][0]: (s["actions"], s["condition"][0]["values"])
                for s in docs[doc]["statement"] if s["sid"] != "AccountManagesTheKeyButCannotUseIt"}
    assert grants("session_key") == {"${aws_iam_role.web.arn}": (["kms:GenerateDataKey", "kms:Decrypt"], ["session"])}
    assert grants("job_key") == {"${aws_iam_role.web.arn}": (["kms:GenerateDataKey"], ["job"]),
                                 "${aws_iam_role.worker.arn}": (["kms:Decrypt"], ["job"])}
    # the account manages these two keys but can't use them, or grant their use
    admin = set(_local("kms.tf", "key_admin_actions"))
    assert not {"kms:Decrypt", "kms:GenerateDataKey", "kms:Encrypt", "kms:CreateGrant", "kms:*", "kms:Create*"} & admin
    for doc in ("session_key", "job_key"):
        assert docs[doc]["statement"][0]["actions"] == "${local.key_admin_actions}"


def test_the_image_builds_the_production_app():
    dockerfile = (DEPLOY / "Dockerfile").read_text()
    assert "RUN npm run build\n" in dockerfile  # not build:demo: the Demo tools pane is left out of the bundle
    assert "BMU_STATIC_DIR=/app/static" in dockerfile and "USER bmu" in dockerfile
    ignore = (DEPLOY.parent / ".dockerignore").read_text()
    assert "**/.env" in ignore and "deploy/environments/*.local.conf" in ignore and "**/.terraform" in ignore


def test_state_and_local_settings_are_never_committed():
    ignore = (DEPLOY.parent / ".gitignore").read_text()
    for pattern in (".terraform/", "*.tfstate", "deploy/environments/*.local.conf"):
        assert pattern in ignore, pattern
    for part in ("registry", "app"):  # state lives in S3, configured by ./bmu aws; nothing account-specific in the code
        text = "".join(p.read_text() for p in (DEPLOY / "terraform" / part).glob("*.tf"))
        assert 'backend "s3" {}' in text and not re.search(r"\b\d{12}\b", text)


# ---- the two task roles (design: Concurrency, IAM and security) ---------------------------------------------------
def _statements(doc: str) -> dict:
    docs = _blocks("iam.tf", "data", "aws_iam_policy_document")
    return {s["sid"]: (set(s["actions"]), s["resources"]) for s in docs[doc]["statement"]}


SESSIONS, CREDENTIALS = '${aws_dynamodb_table.main["sessions"].arn}', '${aws_dynamodb_table.main["credentials"].arn}'


def test_each_role_has_only_what_its_code_uses():
    web, worker = _statements("web"), _statements("worker")
    assert web["Sessions"] == ({"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"}, [SESSIONS])
    assert web["CredentialsPutAndDelete"] == ({"dynamodb:PutItem", "dynamodb:DeleteItem"}, [CREDENTIALS])  # never read
    assert worker["SessionsSweep"] == ({"dynamodb:Scan", "dynamodb:DeleteItem"}, [SESSIONS])
    assert worker["CredentialsReadAndDelete"] == ({"dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem"}, [CREDENTIALS])
    assert "s3:PutObject" in web["StagedFiles"][0] and "s3:PutObject" not in worker["StagedFiles"][0]  # only the web app adds files
    # the read-only CollectionSpace account's secret: the web app reads that one secret, and nothing else may
    assert web["ReaderSecret"] == ({"secretsmanager:GetSecretValue"}, ["${aws_secretsmanager_secret.reader.arn}"])
    others = {**_statements("task_common"), **worker}
    assert not any(a.startswith("secretsmanager:") for actions, _ in others.values() for a in actions)
    roles = _blocks("iam.tf", "resource", "aws_iam_role_policy")
    assert roles["web"]["policy"] == "${data.aws_iam_policy_document.web.json}" and roles["web"]["role"] == "${aws_iam_role.web.id}"
    assert roles["worker"]["policy"] == "${data.aws_iam_policy_document.worker.json}" and roles["worker"]["role"] == "${aws_iam_role.worker.id}"
    for doc in ("web", "worker"):
        source = _blocks("iam.tf", "data", "aws_iam_policy_document")[doc]["source_policy_documents"]
        assert source == ["${data.aws_iam_policy_document.task_common.json}"]


def test_the_roles_match_what_the_code_calls():
    """The policy lists above are what the code needs: the web app never reads a job's sign-in, and the worker never
    reads or writes a session or saves a sign-in. If this fails, the code changed and iam.tf must follow."""
    package = Path(appmod.__file__).parent
    web_code = (package / "app.py").read_text() + (package / "thumbnails.py").read_text()
    worker_code = (package / "worker.py").read_text()
    assert "get_credential(" not in web_code and "claim_job(" not in web_code
    for call in ("put_session(", "get_session(", "update_session", "touch_session(", "put_credential(", "queue_with_credential(",
                 "presign_upload(", "store_thumbnail(", "put_bytes("):
        assert call not in worker_code, call


def test_no_role_can_delete_read_or_replace_audit_records():
    everything = {**{f"common:{k}": v for k, v in _statements("task_common").items()},
                  **{f"web:{k}": v for k, v in _statements("web").items()},
                  **{f"worker:{k}": v for k, v in _statements("worker").items()}}
    for sid, (actions, resources) in everything.items():
        assert not any(a.endswith("*") for a in actions), sid  # no wildcards
        if actions & {"s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject", "s3:DeleteObjectVersion"}:
            assert resources == ["${local.staged_objects}"], sid  # staged files only, never audit files
        if any("audit" in r for r in resources):
            assert actions in ({"dynamodb:PutItem"}, {"s3:PutObject"}), sid  # the audit log is add-only
    assert _local("iam.tf", "staged_objects") == "${aws_s3_bucket.staging.arn}/staging/*"
    assert _local("iam.tf", "audit_objects") == "${aws_s3_bucket.staging.arn}/audit/*"


def test_lifecycle_rules_keep_audit_versions_and_clear_staged_ones():
    rules = {r["id"]: r for r in _blocks("s3.tf", "resource", "aws_s3_bucket_lifecycle_configuration")["staging"]["rule"]}
    audit, staged = rules["expire-audit-detail"], rules["remove-deleted-versions"]
    assert audit["filter"][0]["prefix"] == "audit/" and audit["expiration"][0]["days"] == 365
    assert audit["noncurrent_version_expiration"][0]["noncurrent_days"] == 365
    assert staged["filter"][0]["prefix"] == "staging/" and staged["noncurrent_version_expiration"][0]["noncurrent_days"] == 1


def test_the_reader_accounts_secret_is_created_empty_and_only_named_in_the_settings():
    """Design (Roles, The read-only service account): Terraform makes the secret but never its value, so the
    password is not in the code or in Terraform's state; the app is told only which secret to read."""
    text = (APP / "secrets.tf").read_text()
    assert _blocks("secrets.tf", "resource", "aws_secretsmanager_secret")["reader"]["name"] == "${local.name}/cspace-reader"
    assert "aws_secretsmanager_secret_version" not in "".join(p.read_text() for p in APP.glob("*.tf"))
    assert "secret_string" not in text
    env = _local("ecs.tf", "app_environment")
    assert env["BMU_READER_SECRET_ID"] == "${aws_secretsmanager_secret.reader.arn}"
    assert "BMU_READER_USER" not in env and "BMU_READER_PASSWORD" not in env
    assert "reader.py" not in (Path(appmod.__file__).parent / "worker.py").read_text()  # the worker never uses it
