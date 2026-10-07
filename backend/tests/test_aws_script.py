"""deploy/aws.sh, run against stand-ins for the aws, terraform, docker and curl commands (nothing reaches AWS):

- the server check: a deployed environment's CollectionSpace server and tenant never change (check_server);
- the takeover guard: the first use of an environment on a computer asks first when the account already holds
  Terraform state for that environment's name (check_not_someone_elses);
- the simulated CollectionSpace (SIMULATED_CSPACE=true): its address, label, image and read-only account.
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
  *"ecr get-login-password"*) echo token ;;
  *"secretsmanager describe-secret"*) echo "${FAKE_SECRET_VERSIONS-0}" ;;
  *"secretsmanager put-secret-value"*) cat > "$FAKE_LOG_DIR/secret" ;;
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
  *"output -raw fakecspace_image_uri"*) out fakecspace_image_uri FAKE_SIM_IMAGE ;;
  *"output -raw fakecspace_repository_url"*) echo "repo/bmu-dev-fakecspace" ;;
  *"output -raw repository_url"*) echo "repo/bmu-dev" ;;
  *"output -raw url"*) echo "https://bmu.example.invalid" ;;
  *" plan "*|*" apply "*|*" destroy "*)
    printf '%s\n' "$@" > "$FAKE_LOG_DIR/terraform-$(printf '%s\n' "$@" | grep -m1 -x -E 'plan|apply|destroy')-${1#-chdir=deploy/terraform/}"
    [ "$2" != plan ] || echo "PLANNED cspace_url=$(printf '%s\n' "$@" | sed -n 's/^cspace_url=//p')" ;;
  *) echo "unexpected: terraform $*" >&2; exit 9 ;;
esac
"""

FAKE_DOCKER = r"""#!/usr/bin/env bash
# docker login reads the token from the pipe; without reading it, aws.sh's pipe could fail with SIGPIPE (141)
[ "$1" != login ] || cat > /dev/null
[ "$1" = info ] || echo "DOCKER $*"
"""

FAKE_CURL = r"""#!/usr/bin/env bash
echo 200
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
    (tmp_path / "backend" / "fakecspace").mkdir(parents=True)  # where deploy reads the simulator's reader account
    shutil.copy(SCRIPT.parents[1] / "backend" / "fakecspace" / "app.py", tmp_path / "backend" / "fakecspace" / "app.py")
    (tmp_path / "log").mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("aws", FAKE_AWS), ("terraform", FAKE_TERRAFORM), ("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(stat.S_IRWXU)
    return tmp_path


def write_env(tree, url="https://pahma.qa.collectionspace.org", account=ACCOUNT, local_extra=""):
    envs = tree / "deploy" / "environments"
    (envs / "t.conf").write_text(CONF.format(url=url))
    local = 'ALLOWED_CIDRS="203.0.113.7/32"\n' + (f'ACCOUNT_ID="{account}"\n' if account else "") + local_extra
    (envs / "t.local.conf").write_text(local)
    return envs / "t.local.conf"


def run(tree, *args, answers="", **fake):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "AWS_", "BMU_AWS"))}
    env["PATH"] = f"{tree / 'bin'}{os.pathsep}{env['PATH']}"
    env["FAKE_ACCOUNT"] = ACCOUNT
    env["FAKE_LOG_DIR"] = str(tree / "log")
    env.update({f"FAKE_{k.upper()}": str(v) for k, v in fake.items()})
    return subprocess.run(["bash", str(tree / "deploy" / "aws.sh"), "--env", "t", *args], input=answers,
                          capture_output=True, text=True, env=env, timeout=30)


def test_the_script_is_executable():
    """./bmu runs deploy/aws.sh directly, so it must keep its executable bit in git (lost once, in PR #78)."""
    assert os.access(SCRIPT, os.X_OK), "chmod +x deploy/aws.sh && git update-index --chmod=+x deploy/aws.sh"


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


# ---- the simulated CollectionSpace ----------------------------------------------------------------------------------

SIM_URL = "http://fakecspace.bmu-dev.internal:8180"  # local.fakecspace_url in deploy/terraform/app/fakecspace.tf


def tf_args(tree, name):
    """The arguments of the last stand-in terraform plan, apply or destroy, e.g. tf_args(tree, "apply-app")."""
    lines = (tree / "log" / f"terraform-{name}").read_text().splitlines()
    return {k: v for k, _, v in (a.partition("=") for a in lines if "=" in a and not a.startswith("-"))}


def test_the_simulators_address_is_the_one_terraform_gives_it():
    fakecspace_tf = (SCRIPT.parent / "terraform" / "app" / "fakecspace.tf").read_text()
    variables_tf = (SCRIPT.parent / "terraform" / "app" / "variables.tf").read_text()
    assert 'fakecspace_url = "http://fakecspace.${local.name}.internal:8180"' in fakecspace_tf
    assert 'name        = "${local.name}.internal"' in fakecspace_tf and 'name  = "fakecspace"' in fakecspace_tf
    assert '"http://fakecspace.bmu-${var.env_name}.internal:8180"' in variables_tf
    assert 'sim_url() { echo "http://fakecspace.$NAME.internal:8180"; }' in SCRIPT.read_text()


def test_with_the_simulator_the_bmu_uses_it_and_says_so(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\n")  # CSPACE_URL in the settings is ignored
    r = run(tree, "plan", url=SIM_URL, tenant="pahma", sim_image="repo/bmu-dev-fakecspace:abc")
    assert r.returncode == 0, r.stderr
    args = tf_args(tree, "plan-app")
    assert args["cspace_url"] == SIM_URL and args["simulated_cspace"] == "true"
    assert args["fakecspace_image_uri"] == "repo/bmu-dev-fakecspace:abc"
    assert args["env_label"] == "AWS · t · simulated CollectionSpace"


def test_a_label_set_in_the_local_settings_is_kept_with_the_simulator(tree):
    write_env(tree, local_extra='SIMULATED_CSPACE=true\nENV_LABEL="My sandbox"\n')
    r = run(tree, "plan", url=SIM_URL, tenant="pahma", sim_image="x:1")
    assert r.returncode == 0, r.stderr
    assert tf_args(tree, "plan-app")["env_label"] == "My sandbox"


def test_without_the_simulator_nothing_changes(tree):
    write_env(tree)
    r = run(tree, "plan", url="https://pahma.qa.collectionspace.org", tenant="pahma")
    assert r.returncode == 0, r.stderr
    args = tf_args(tree, "plan-app")
    assert args["simulated_cspace"] == "false" and args["fakecspace_image_uri"] == "" and args["env_label"] == "test"


def test_turning_the_simulator_on_in_a_deployed_environment_is_a_change_of_server(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\n")
    r = run(tree, "plan", url="https://pahma.qa.collectionspace.org", tenant="pahma")
    assert r.returncode == 1
    assert f"now say {SIM_URL}" in r.stderr and "Stopped; nothing was changed" in r.stderr


def test_the_simulator_is_refused_where_data_is_protected(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\nPROTECT_DATA=true\n")
    r = run(tree, "plan")
    assert r.returncode == 1 and "can't be used with PROTECT_DATA=true" in r.stderr


def test_simulated_cspace_must_be_true_or_false(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=yes\n")
    r = run(tree, "plan")
    assert r.returncode == 1 and "SIMULATED_CSPACE must be true or false" in r.stderr


def test_a_deploy_with_the_simulator_builds_its_image_and_sets_the_read_only_account_once(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\n")
    r = run(tree, "deploy", bucket_rc=0)  # a first deploy: no outputs yet
    assert r.returncode == 0, r.stderr
    builds = [line for line in r.stdout.splitlines() if line.startswith("DOCKER build")]
    assert len(builds) == 2 and "-f deploy/Dockerfile" in builds[0] and "-f deploy/fakecspace.Dockerfile" in builds[1]
    assert tf_args(tree, "apply-registry")["simulated_cspace"] == "true"
    args = tf_args(tree, "apply-app")
    assert args["fakecspace_image_uri"].startswith("repo/bmu-dev-fakecspace:nogit-")
    assert args["cspace_url"] == SIM_URL and args["simulated_cspace"] == "true"
    assert (tree / "log" / "secret").read_text() == '{"username":"bmureader","password":"bmureader"}'
    assert "simulated CollectionSpace" in r.stdout and "real records" not in r.stdout


def test_a_later_deploy_with_the_simulator_leaves_the_read_only_account_alone(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\n")
    r = run(tree, "deploy", url=SIM_URL, tenant="pahma", sim_image="x:1", secret_versions=1)
    assert r.returncode == 0, r.stderr
    assert not (tree / "log" / "secret").exists()


def test_a_deploy_without_the_simulator_builds_one_image_and_leaves_the_secret_alone(tree):
    write_env(tree)
    r = run(tree, "deploy", url="https://pahma.qa.collectionspace.org", tenant="pahma")
    assert r.returncode == 0, r.stderr
    assert [line for line in r.stdout.splitlines() if line.startswith("DOCKER build")] == [
        next(line for line in r.stdout.splitlines() if "-f deploy/Dockerfile" in line)]
    assert tf_args(tree, "apply-registry")["simulated_cspace"] == "false"
    assert not (tree / "log" / "secret").exists()
    assert "real records" in r.stdout


def test_the_reader_secret_command_is_refused_with_the_simulator(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\n")
    r = run(tree, "reader-secret")
    assert r.returncode == 1 and "simulated CollectionSpace" in r.stderr
