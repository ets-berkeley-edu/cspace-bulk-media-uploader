"""The AWS deployment (deploy/) agrees with the app: the CloudFormation template creates the tables the app uses
(the same keys, index and TTL as Storage.create_tables makes locally), sets only settings that exist, keeps Demo
tools off, and runs the web app and the worker the way the image expects. cfn-lint checks the template itself
(README: deploy/README.md)."""
from pathlib import Path

import boto3
import pytest
import yaml
from moto import mock_aws

from bmu import app as appmod
from bmu.config import Settings
from bmu.storage import Storage

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


class _CfnLoader(yaml.SafeLoader):
    """Reads CloudFormation's short-form functions (!Ref, !Sub, ...) as {"Ref": ...} / {"Fn::Sub": ...}."""


def _tag(loader, suffix, node):
    name = "Ref" if suffix == "Ref" else f"Fn::{suffix}"
    if isinstance(node, yaml.ScalarNode):
        return {name: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {name: loader.construct_sequence(node, deep=True)}
    return {name: loader.construct_mapping(node, deep=True)}


_CfnLoader.add_multi_constructor("!", _tag)


@pytest.fixture(scope="module")
def template():
    return yaml.load((DEPLOY / "cloudformation" / "bmu.yaml").read_text(), Loader=_CfnLoader)


def _resources(template, type_):
    return {k: v["Properties"] for k, v in template["Resources"].items() if v["Type"] == type_}


def _name(sub: dict | str, env="dev") -> str:
    s = sub["Fn::Sub"] if isinstance(sub, dict) else sub
    return s.replace("${EnvName}", env)


def test_the_template_creates_the_tables_the_app_uses(template):
    with mock_aws():
        storage = Storage(Settings(table_prefix="bmu-dev", s3_bucket="bmu-x", aws_region="us-west-2", _env_file=None))
        storage.create_tables()
        client = boto3.client("dynamodb", region_name="us-west-2")
        local = {}
        for name in client.list_tables()["TableNames"]:
            t = client.describe_table(TableName=name)["Table"]
            local[name] = {
                "keys": sorted((k["AttributeName"], k["KeyType"]) for k in t["KeySchema"]),
                "attrs": sorted((a["AttributeName"], a["AttributeType"]) for a in t["AttributeDefinitions"]),
                "gsis": sorted((g["IndexName"], tuple((k["AttributeName"], k["KeyType"]) for k in g["KeySchema"]))
                               for g in t.get("GlobalSecondaryIndexes", [])),
            }
    cfn = {}
    for props in _resources(template, "AWS::DynamoDB::Table").values():
        cfn[_name(props["TableName"])] = {
            "keys": sorted((k["AttributeName"], k["KeyType"]) for k in props["KeySchema"]),
            "attrs": sorted((a["AttributeName"], a["AttributeType"]) for a in props["AttributeDefinitions"]),
            "gsis": sorted((g["IndexName"], tuple((k["AttributeName"], k["KeyType"]) for k in g["KeySchema"]))
                           for g in props.get("GlobalSecondaryIndexes", [])),
        }
        assert props["BillingMode"] == "PAY_PER_REQUEST"
    assert cfn == local
    ttl = {_name(p["TableName"]): p.get("TimeToLiveSpecification") for p in _resources(template, "AWS::DynamoDB::Table").values()}
    for t in ("bmu-dev-sessions", "bmu-dev-credentials", "bmu-dev-audit"):  # as Storage.create_tables turns on
        assert ttl[t] == {"AttributeName": "expires", "Enabled": True}
    pitr = {_name(p["TableName"]): p["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"]
            for p in _resources(template, "AWS::DynamoDB::Table").values()}
    assert pitr == {"bmu-dev-jobs": True, "bmu-dev-audit": True,  # design: no backups of passwords, even encrypted
                    "bmu-dev-sessions": False, "bmu-dev-credentials": False}


def _containers(template):
    return {c["Name"]: c for td in _resources(template, "AWS::ECS::TaskDefinition").values() for c in td["ContainerDefinitions"]}


def test_containers_set_only_real_settings_and_never_demo(template):
    fields = set(Settings.model_fields)
    containers = _containers(template)
    assert set(containers) == {"web", "worker"}
    for c in containers.values():
        env = {e["Name"]: e["Value"] for e in c["Environment"]}
        for name in env:
            assert name.startswith("BMU_") and name[4:].lower() in fields, name
        assert env["BMU_DEMO"] == "false" and env["BMU_CRYPTO_MODE"] == "kms" and env["BMU_COOKIE_SECURE"] == "true"
        assert {"BMU_KMS_SESSION_KEY_ID", "BMU_KMS_JOB_KEY_ID", "BMU_S3_KMS_KEY_ID", "BMU_S3_BUCKET"} <= set(env)
        assert "BMU_CREATE_TABLES" not in env and "BMU_SESSION_KEY_B64" not in env  # tables and keys come from the stack
        assert env["BMU_TABLE_PREFIX"] == {"Fn::Sub": "bmu-${EnvName}"}
    assert containers["worker"]["Command"] == ["python", "-m", "bmu.worker"]
    assert "Command" not in containers["web"]  # the image's CMD: uvicorn on port 8000
    assert containers["web"]["PortMappings"][0]["ContainerPort"] == 8000


def test_the_load_balancer_checks_a_route_the_app_has(template):
    path = _resources(template, "AWS::ElasticLoadBalancingV2::TargetGroup")["WebTargetGroup"]["HealthCheckPath"]
    assert path == "/api/health" and f'@app.get("{path}")' in Path(appmod.__file__).read_text()


def test_key_policies_follow_the_design(template):
    keys = _resources(template, "AWS::KMS::Key")
    def grants(key):
        return {s["Principal"]["AWS"]["Fn::GetAtt"]: s["Action"] for s in keys[key]["KeyPolicy"]["Statement"]
                if isinstance(s["Principal"]["AWS"], dict) and "Fn::GetAtt" in s["Principal"]["AWS"]}
    assert grants("SessionKey") == {"WebTaskRole.Arn": ["kms:GenerateDataKey", "kms:Decrypt"]}
    assert grants("JobKey") == {"WebTaskRole.Arn": "kms:GenerateDataKey", "WorkerTaskRole.Arn": "kms:Decrypt"}
    for key in ("SessionKey", "JobKey"):  # the account manages these keys but can't use them
        admin = [s for s in keys[key]["KeyPolicy"]["Statement"] if s["Sid"] == "AccountManagesTheKeyButCannotUseIt"][0]
        assert not {"kms:Decrypt", "kms:GenerateDataKey", "kms:*", "kms:Encrypt"} & set(admin["Action"])


def test_the_image_builds_the_production_app(template):
    dockerfile = (DEPLOY / "Dockerfile").read_text()
    assert "RUN npm run build\n" in dockerfile  # not build:demo: the Demo tools pane is left out of the bundle
    assert "BMU_STATIC_DIR=/app/static" in dockerfile and "USER bmu" in dockerfile
    ignore = (DEPLOY.parent / ".dockerignore").read_text()
    assert "**/.env" in ignore and "deploy/environments/*.local.conf" in ignore
