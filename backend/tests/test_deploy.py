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
