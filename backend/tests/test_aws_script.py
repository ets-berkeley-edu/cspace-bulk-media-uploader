"""deploy/aws.sh's guards, run against stand-ins for the aws and terraform commands (nothing reaches AWS):

- the server check: a deployed environment's CollectionSpace server and tenant never change (check_server);
- the takeover guard: the first use of an environment on a computer asks first when the account already holds
  Terraform state for that environment's name (check_not_someone_elses).
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "aws.sh"
ACCOUNT = "111122223333"

FAKE_AWS = r"""#!/usr/bin/env bash
case "$*" in
  *"sts get-caller-identity"*) echo "$FAKE_ACCOUNT" ;;
  *"s3api head-bucket"*) exit "${FAKE_BUCKET_RC:-0}" ;;
  *"s3api head-object"*) exit "${FAKE_STATE_RC:-1}" ;;
esac
"""

FAKE_TERRAFORM = r"""#!/usr/bin/env bash
out() {  # out NAME VALUE-VARIABLE: an output, or Terraform's error when the state doesn't have it
  if [ -n "${!2+x}" ]; then echo "${!2}"; else echo "Error: Output \"$1\" not found" >&2; exit 1; fi
}
case "$*" in
  *" init "*) ;;
  *"output -raw image_uri"*) echo "repo/bmu-dev:abc1234-20261007000000" ;;
  *"output -raw running"*) echo true ;;
  *"output -raw cspace_url"*) out cspace_url FAKE_URL ;;
  *"output -raw tenant"*) out tenant FAKE_TENANT ;;
  *" plan "*) echo "PLANNED cspace_url=$(printf '%s\n' "$@" | sed -n 's/^cspace_url=//p')" ;;
  *) echo "unexpected: terraform $*" >&2; exit 9 ;;
esac
"""

FAKE_DOCKER = r"""#!/usr/bin/env bash
[ "$1" = info ] || echo "DOCKER $*"
"""

CONF = """AWS_PROFILE=bmu-test
AWS_REGION=us-west-2
BMU_ENV_NAME=dev
CSPACE_URL={url}
TENANT=pahma
ENV_LABEL="test"
ALWAYS_RUN_TIME=false
"""


@pytest.fixture
def tree(tmp_path):
    """A copy of deploy/aws.sh in its own tree, with stand-in aws and terraform first on the PATH."""
    (tmp_path / "deploy" / "environments").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "deploy" / "aws.sh")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("aws", FAKE_AWS), ("terraform", FAKE_TERRAFORM), ("docker", FAKE_DOCKER)):
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(stat.S_IRWXU)
    return tmp_path


def write_env(tree, url="https://pahma.qa.collectionspace.org", account=ACCOUNT):
    envs = tree / "deploy" / "environments"
    (envs / "t.conf").write_text(CONF.format(url=url))
    local = 'ALLOWED_CIDRS="203.0.113.7/32"\n' + (f'ACCOUNT_ID="{account}"\n' if account else "")
    (envs / "t.local.conf").write_text(local)
    return envs / "t.local.conf"


def run(tree, *args, answers="", **fake):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "AWS_", "BMU_AWS"))}
    env["PATH"] = f"{tree / 'bin'}{os.pathsep}{env['PATH']}"
    env["FAKE_ACCOUNT"] = ACCOUNT
    env.update({f"FAKE_{k.upper()}": str(v) for k, v in fake.items()})
    return subprocess.run(["bash", str(tree / "deploy" / "aws.sh"), "--env", "t", *args], input=answers,
                          capture_output=True, text=True, env=env, timeout=30)


# ---- the server check -----------------------------------------------------------------------------------------------

def test_the_same_server_goes_ahead(tree):
    write_env(tree)
    r = run(tree, "plan", url="https://pahma.qa.collectionspace.org", tenant="pahma")
    assert r.returncode == 0, r.stderr
    assert "PLANNED" in r.stdout


def test_a_trailing_slash_in_the_settings_is_the_same_server(tree):
    write_env(tree, url="https://pahma.qa.collectionspace.org/")
    r = run(tree, "plan", url="https://pahma.qa.collectionspace.org", tenant="pahma")
    assert r.returncode == 0, r.stderr
    assert "PLANNED cspace_url=https://pahma.qa.collectionspace.org\n" in r.stdout


def test_another_server_is_refused_before_terraform_changes_anything(tree):
    write_env(tree, url="https://other.collectionspace.org")
    for command in ("plan", "pause", "resume"):
        r = run(tree, command, url="https://pahma.qa.collectionspace.org", tenant="pahma")
        assert r.returncode == 1, command
        assert "Stopped; nothing was changed" in r.stderr
        assert "was deployed for https://pahma.qa.collectionspace.org" in r.stderr
        assert "PLANNED" not in r.stdout and "apply" not in r.stdout


def test_a_deploy_to_another_server_stops_before_building_the_image(tree):
    write_env(tree, url="https://other.collectionspace.org")
    r = run(tree, "deploy", url="https://pahma.qa.collectionspace.org", tenant="pahma")
    assert r.returncode == 1
    assert "Stopped; nothing was changed" in r.stderr
    assert "DOCKER" not in r.stdout and "Image repository" not in r.stdout


def test_another_tenant_on_the_same_server_is_refused(tree):
    write_env(tree)
    r = run(tree, "plan", url="https://pahma.qa.collectionspace.org", tenant="bampfa")
    assert r.returncode == 1
    assert "(tenant bampfa)" in r.stderr and "(tenant pahma)" in r.stderr


def test_an_environment_deployed_before_the_check_goes_ahead_and_is_recorded_by_the_apply(tree):
    write_env(tree)
    r = run(tree, "plan")  # the state has no cspace_url or tenant output yet
    assert r.returncode == 0, r.stderr
    assert "PLANNED" in r.stdout


# ---- the takeover guard ---------------------------------------------------------------------------------------------

def test_first_use_with_no_state_in_the_account_asks_only_for_the_account(tree):
    local = write_env(tree, account=None)
    r = run(tree, "plan", answers="y\n", bucket_rc=1)  # no state bucket: nothing deployed, stops there
    assert r.returncode == 0, r.stderr
    assert "already has a BMU environment" not in r.stdout
    assert f'ACCOUNT_ID="{ACCOUNT}"' in local.read_text()


def test_first_use_where_the_name_is_taken_stops_unless_it_is_yours(tree):
    local = write_env(tree, account=None)
    r = run(tree, "plan", answers="y\nn\n", state_rc=0)
    assert r.returncode == 1
    assert "already has a BMU environment named 'dev'" in r.stdout
    assert "BMU_ENV_NAME" in r.stdout
    assert "Stopped; nothing was changed" in r.stderr
    assert "ACCOUNT_ID" not in local.read_text()  # asked again next time


def test_first_use_where_the_name_is_yours_carries_on(tree):
    local = write_env(tree, account=None)
    r = run(tree, "plan", answers="y\ny\n", state_rc=0, bucket_rc=1)
    assert r.returncode == 0, r.stderr
    assert "already has a BMU environment named 'dev'" in r.stdout
    assert f'ACCOUNT_ID="{ACCOUNT}"' in local.read_text()


def test_a_known_account_is_never_asked_again(tree):
    write_env(tree)
    r = run(tree, "plan", state_rc=0, url="https://pahma.qa.collectionspace.org", tenant="pahma")
    assert r.returncode == 0, r.stderr
    assert "already has a BMU environment" not in r.stdout
