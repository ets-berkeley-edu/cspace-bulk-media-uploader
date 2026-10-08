"""The AWS deployment (deploy/) agrees with the app: the Terraform configuration creates the tables the app uses
(the same keys, index and TTL as Storage.create_tables makes locally), sets only settings that exist, keeps Demo
tools off, and runs the web app and the worker the way the image expects. Terraform's own checks (terraform validate,
terraform test) cover the configuration itself (deploy/README.md)."""
import json
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
    assert {"BMU_KMS_SESSION_KEY_ID", "BMU_KMS_JOB_KEY_ID", "BMU_S3_KMS_KEY_IDS", "BMU_S3_BUCKET", "BMU_TENANTS"} <= set(env)
    assert "BMU_CREATE_TABLES" not in env and "BMU_SESSION_KEY_B64" not in env  # tables and keys come from Terraform
    # several museums (design: One deployment for several museums): no single-museum setting to fall back on
    assert not {"BMU_TENANT", "BMU_CSPACE_URL", "BMU_S3_KMS_KEY_ID", "BMU_READER_SECRET_ID"} & set(env)
    assert env["BMU_TENANTS"] == "${jsonencode(var.tenants)}"
    assert env["BMU_S3_KMS_KEY_IDS"] == "${jsonencode({for m, key in aws_kms_key.staging : m => key.arn})}"
    assert env["BMU_READER_SECRET_IDS"] == "${jsonencode({for m, secret in aws_secretsmanager_secret.reader : m => secret.arn})}"
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


def test_the_production_image_has_no_simulator_and_the_simulators_image_has_no_bmu():
    production = (DEPLOY / "Dockerfile").read_text()
    simulator = (DEPLOY / "fakecspace.Dockerfile").read_text()
    assert "COPY backend/fakecspace" not in production
    assert "COPY backend/fakecspace ./fakecspace" in simulator and "backend/bmu" not in simulator
    assert "pip install --no-cache-dir --require-hashes -r requirements.txt" in simulator  # the same pins
    assert "USER fakecspace" in simulator and '"--port", "8180"' in simulator


def test_the_simulator_is_off_by_default_never_with_protected_data_and_wholly_optional():
    variables = {name: body for block in _tf("variables.tf")["variable"] for name, body in block.items()}
    assert variables["simulated_cspace"]["default"] is False and variables["fakecspace_image_uri"]["default"] == ""
    conditions = [v["condition"] for v in variables["simulated_cspace"]["validation"]]
    assert any("var.protect_data" in c for c in conditions)
    # every simulator resource exists only with simulated_cspace (fakecspace.tf)
    resources = [(t, n, body) for block in _tf("fakecspace.tf")["resource"] for t, named in block.items()
                 for n, body in named.items()]
    assert len(resources) >= 8 and all(body.get("count") == "${local.simulated}" for _, _, body in resources), resources
    assert 'count                = var.simulated_cspace ? 1 : 0' in (DEPLOY / "terraform" / "registry" / "main.tf").read_text()
    # only the web app and the worker can reach it
    rules = _blocks("fakecspace.tf", "resource", "aws_vpc_security_group_ingress_rule")
    assert {r["referenced_security_group_id"] for r in rules.values()} == {"${aws_security_group.web.id}",
                                                                          "${aws_security_group.worker.id}"}
    assert _local("ecs.tf", "app_environment")["BMU_CSPACE_SIMULATED"] == "${tostring(var.simulated_cspace)}"


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
    # the read-only CollectionSpace accounts' secrets: the web app reads those, one per museum, and nothing else may
    assert web["ReaderSecrets"] == ({"secretsmanager:GetSecretValue"}, "${[for secret in aws_secretsmanager_secret.reader : secret.arn]}")
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
    reader = _blocks("secrets.tf", "resource", "aws_secretsmanager_secret")["reader"]
    assert reader["name"] == "${local.name}/cspace-reader/${each.key}" and reader["for_each"] == "${var.tenants}"  # one per museum
    assert "aws_secretsmanager_secret_version" not in "".join(p.read_text() for p in APP.glob("*.tf"))
    assert "secret_string" not in text
    env = _local("ecs.tf", "app_environment")
    assert "aws_secretsmanager_secret.reader" in env["BMU_READER_SECRET_IDS"]
    assert "BMU_READER_USER" not in env and "BMU_READER_PASSWORD" not in env
    assert "reader.py" not in (Path(appmod.__file__).parent / "worker.py").read_text()  # the worker never uses it


def test_what_the_app_writes_to_s3_names_the_staging_key_as_the_bucket_policy_requires(settings, aws):
    """The bucket refuses a PutObject without SSE-KMS and the staging key (s3.tf: StringNotEqualsIfExists also
    refuses a request that names neither). Thumbnails and audit detail are written by the app itself."""
    policy = (APP / "s3.tf").read_text()
    assert policy.count("StringNotEqualsIfExists") == 2 and "OnlyKmsEncryptedUploads" in policy and "OnlyTheStagingKeyOf" in policy
    sent = []
    for key_id in (None, "arn:aws:kms:us-west-2:111122223333:key/abc"):
        settings.s3_kms_key_id = key_id
        storage = Storage(settings)
        storage.s3 = type("S3", (), {"put_object": lambda self, **kw: sent.append(kw)})()
        storage.put_bytes("staging/pahma/j/00001/thumb-x", b"jpeg", "image/jpeg")
    assert "ServerSideEncryption" not in sent[0]  # locally: no key, plain upload
    assert sent[1]["ServerSideEncryption"] == "aws:kms" and sent[1]["SSEKMSKeyId"] == "arn:aws:kms:us-west-2:111122223333:key/abc"
    assert "put_object(" not in (Path(appmod.__file__).parent / "storage.py").read_text().replace("self.s3.put_object(Bucket=self.s.s3_bucket, Key=key, Body=data, ContentType=content_type, **sse)", "")


# ---- several museums (design: One deployment for several museums) ---------------------------------------------------
def test_each_museum_has_its_staging_key_limited_to_its_objects():
    key = _blocks("kms.tf", "resource", "aws_kms_key")["staging"]
    assert key["for_each"] == "${var.tenants}" and key["policy"] == "${data.aws_iam_policy_document.staging_key[each.key].json}"
    assert _blocks("kms.tf", "resource", "aws_kms_alias")["staging"]["name"] == "alias/${local.name}-staging-${each.key}"
    doc = _blocks("kms.tf", "data", "aws_iam_policy_document")["staging_key"]
    deny = next(s for s in doc["statement"] if s.get("effect") == "Deny")
    assert deny["principals"] == [{"type": "AWS", "identifiers": ["*"]}]
    assert {"kms:Decrypt", "kms:GenerateDataKey*", "kms:Encrypt", "kms:ReEncrypt*"} == set(deny["actions"])
    # StringNotLike: a request whose context isn't one of the museum's objects, or has none (not through S3), is refused
    assert deny["condition"] == [{"test": "StringNotLike", "variable": "kms:EncryptionContext:aws:s3:arn",
                                  "values": "${local.museum_objects[each.key]}"}]
    objects = _local("kms.tf", "museum_objects")
    assert "${local.staging_bucket}/staging/${m}/*" in objects and "${local.staging_bucket}/audit/${m}/*" in objects
    # S3 Bucket Keys off: the encryption context is each object's ARN, and CloudTrail records each file's use
    sse = _blocks("s3.tf", "resource", "aws_s3_bucket_server_side_encryption_configuration")["staging"]["rule"][0]
    assert sse["bucket_key_enabled"] is False and "kms_master_key_id" not in sse["apply_server_side_encryption_by_default"][0]


def test_the_bucket_takes_each_museums_files_only_under_its_prefixes_with_its_key():
    doc = _blocks("s3.tf", "data", "aws_iam_policy_document")["staging_bucket"]
    prefixes = next(s for s in doc["statement"] if s["sid"] == "OnlyTheMuseumsPrefixes")
    assert prefixes["effect"] == "Deny" and prefixes["actions"] == ["s3:PutObject"]
    assert "/staging/${m}/*" in prefixes["not_resources"] and "/audit/${m}/*" in prefixes["not_resources"]
    per_museum = doc["dynamic"][0]["statement"]
    assert per_museum["for_each"] == "${var.tenants}"
    content = per_museum["content"][0]
    assert content["resources"] == ["${aws_s3_bucket.staging.arn}/staging/${statement.key}/*",
                                    "${aws_s3_bucket.staging.arn}/audit/${statement.key}/*"]
    assert content["condition"][0]["values"] == ["${aws_kms_key.staging[statement.key].arn}"]
    assert _statements("task_common")["StagingKeys"][1] == "${[for key in aws_kms_key.staging : key.arn]}"


def test_storage_writes_only_where_the_bucket_policy_allows():
    """The bucket allows writes only under staging/<museum>/ and audit/<museum>/ (above); Storage refuses any other
    key before asking S3 (storage.py, _kms_key)."""
    storage = (Path(appmod.__file__).parent / "storage.py").read_text()
    assert 'f"staging/{tenant}/' in storage and 'f"audit/{tenant}/' in storage


def test_what_terraform_passes_is_what_the_app_reads(monkeypatch):
    """BMU_TENANTS, BMU_S3_KMS_KEY_IDS and BMU_READER_SECRET_IDS are JSON objects (jsonencode in ecs.tf), read into
    Settings' dicts; with them, every museum has its server, key and secret, with nothing to fall back on."""
    tenants = {"bampfa": "https://bampfa.qa.collectionspace.org", "pahma": "https://pahma.qa.collectionspace.org"}
    monkeypatch.setenv("BMU_TENANTS", json.dumps(tenants))
    monkeypatch.setenv("BMU_S3_KMS_KEY_IDS", json.dumps({m: f"arn:aws:kms:us-west-2:111122223333:key/{m}" for m in tenants}))
    monkeypatch.setenv("BMU_READER_SECRET_IDS", json.dumps({m: f"arn:aws:secretsmanager:us-west-2:111122223333:secret:r-{m}" for m in tenants}))
    settings = Settings(_env_file=None)
    assert settings.museums() == tenants
    assert settings.kms_key_for("bampfa").endswith("key/bampfa") and settings.reader_secret_for("pahma").endswith("r-pahma")
    assert settings.s3_kms_key_id is None and settings.reader_secret_id is None


def test_each_museum_in_the_settings_has_a_configuration():
    for conf in (DEPLOY / "environments").glob("*.conf"):
        if conf.name.endswith(".local.conf"):
            continue  # never read: not committed, and may hold an account number
        line = next(l for l in conf.read_text().splitlines() if l.startswith("CSPACE_TENANTS="))
        for entry in line.split("=", 1)[1].strip('"').split():
            museum = entry.split("=", 1)[0]
            assert (Path(appmod.__file__).parent / "tenants" / f"{museum}.yaml").exists(), (conf.name, museum)
