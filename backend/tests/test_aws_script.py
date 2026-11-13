"""deploy/aws.sh, run against stand-ins for the aws, terraform, docker and curl commands (nothing reaches AWS):

- the museums (CSPACE_TENANTS, or TENANT and CSPACE_URL): checked, and passed to Terraform as its tenants map;
- the museum check: a deployed museum's CollectionSpace server never changes; museums can be added, and removed only
  without unfinished jobs and once its name is typed (check_museums);
- the takeover guard: the first use of an environment on a computer asks first when the account already holds
  Terraform state for that environment's name (check_not_someone_elses);
- the simulated CollectionSpace (SIMULATED_CSPACE=true): its address, label, image and read-only account;
- the read-only accounts' secrets, one per museum (reader-secret MUSEUM, status).
- ci-role: CI's ECR Public role, with the account's GitHub OIDC provider created or reused.
- the front door (FRONT_DOOR, DOMAIN_NAME): its settings, the certificate's DNS record, and no change of front door
  once deployed (check_front_door); REQUIRE_CLEAN (check_clean).
- the settings in SSM Parameter Store (SETTINGS=ssm; settings push, show and delete): pushed by the administrator,
  read by every other command, never written by the deployer.
"""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "aws.sh"
ACCOUNT = "111122223333"

FAKE_AWS = r"""#!/usr/bin/env bash
arg() {  # arg OPTION ARGS...: the value after OPTION
  local want="$1"; shift
  while [ $# -gt 0 ]; do [ "$1" = "$want" ] && { echo "$2"; return; }; shift; done
}
# SSM Parameter Store: one file per parameter under $FAKE_LOG_DIR/ssm (its name is the path); writes are logged with
# the profile that made them.
SSM="$FAKE_LOG_DIR/ssm"
case "$*" in
  *"ssm describe-parameters"*)
    path="$(arg --parameter-filters "$@" | sed 's/.*Values=//')"
    ls "$SSM$path" 2>/dev/null | sed "s|^|$path/|" | paste -s -d '\t' - ;;
  *"ssm get-parameters"*)
    take=false
    for a in "$@"; do
      case "$a" in --names) take=true ;; --*) take=false ;;
        *) [ "$take" = false ] || printf '%s\t%s\n' "$a" "$(cat "$SSM$a")" ;; esac
    done ;;
  *"ssm put-parameter"*)
    name="$(arg --name "$@")"; mkdir -p "$(dirname "$SSM$name")"; printf '%s' "$(arg --value "$@")" > "$SSM$name"
    echo "put $name as $(arg --profile "$@")" >> "$FAKE_LOG_DIR/ssm-writes" ;;
  *"ssm delete-parameter"*)
    rm -f "$SSM$(arg --name "$@")"; echo "delete $(arg --name "$@") as $(arg --profile "$@")" >> "$FAKE_LOG_DIR/ssm-writes" ;;
  *"ssm add-tags-to-resource"*) echo "tag $(arg --resource-id "$@") $(arg --tags "$@")" >> "$FAKE_LOG_DIR/ssm-writes" ;;
  *"s3 cp"*) echo "${FAKE_STATE_JSON:-}" ;;
esac
case "$*" in
  *"sts get-caller-identity"*) echo "$FAKE_ACCOUNT" ;;
  *"s3api head-bucket"*) exit "${FAKE_BUCKET_RC:-0}" ;;
  *"s3api head-object"*) exit "${FAKE_STATE_RC:-1}" ;;
  *"ecr get-login-password"*) echo token ;;
  *"dynamodb query"*) printf '%s\n' "$@" > "$FAKE_LOG_DIR/dynamodb-query"; echo "${FAKE_UNFINISHED_JOBS:-0}" ;;
  *"secretsmanager describe-secret"*)
    case "$*" in *LastChangedDate*) echo "2026-10-07T12:00:00" ;; *) echo "${FAKE_SECRET_VERSIONS-0}" ;; esac ;;
  *"iam list-open-id-connect-providers"*) echo "${FAKE_OIDC_PROVIDERS:-}" ;;
  *"acm describe-certificate"*)
    case "$*" in *Certificate.Status*) echo "${FAKE_CERT_STATUS:-ISSUED}" ;;
      *) printf 'CNAME\t_abc.bmu-qa.example.invalid.\t_xyz.acm-validations.aws.\n' ;; esac ;;
  *"secretsmanager put-secret-value"*)
    printf '%s\n' "$@" | grep -A1 -x -e --secret-id | tail -1 > "$FAKE_LOG_DIR/secret-id"
    cat > "$FAKE_LOG_DIR/secret" ;;
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
  *"output -raw museums"*) out museums FAKE_MUSEUMS ;;
  *"output -raw cspace_url"*) out cspace_url FAKE_URL ;;
  *"output -raw fakecspace_image_uri"*) out fakecspace_image_uri FAKE_SIM_IMAGE ;;
  *"output -raw fakecspace_repository_url"*) echo "repo/bmu-dev-fakecspace" ;;
  *"output -raw repository_url"*) echo "repo/bmu-dev" ;;
  *"output -raw url"*) echo "https://bmu.example.invalid" ;;
  *"output -raw front_door"*) out front_door FAKE_FRONT_DOOR ;;
  *"output -raw domain_name"*) out domain_name FAKE_DOMAIN ;;
  *"output -raw alb_dns_name"*) echo "bmu-dev-123.us-west-2.elb.amazonaws.com" ;;
  *"output -raw certificate_arn"*) echo "${FAKE_CERT_ARN-arn:aws:acm:us-west-2:111122223333:certificate/abc}" ;;
  *"output -raw role_arn"*) echo "arn:aws:iam::$FAKE_ACCOUNT:role/bmu-ci-ecr-public-pull" ;;
  *"state list"*) echo "${FAKE_CI_STATE:-}" ;;
  *" plan "*|*" apply "*|*" destroy "*)
    printf '%s\n' "$@" > "$FAKE_LOG_DIR/terraform-$(printf '%s\n' "$@" | grep -m1 -x -E 'plan|apply|destroy')-${1#-chdir=deploy/terraform/}"
    [ "$2" != plan ] || echo "PLANNED tenants=$(printf '%s\n' "$@" | sed -n 's/^tenants=//p')" ;;
  *) echo "unexpected: terraform $*" >&2; exit 9 ;;
esac
"""

FAKE_DOCKER = r"""#!/usr/bin/env bash
# docker login reads the token from the pipe; without reading it, aws.sh's pipe could fail with SIGPIPE (141)
[ "$1" != login ] || cat > /dev/null
[ "$1" = info ] || echo "DOCKER $*"
"""

FAKE_CURL = r"""#!/usr/bin/env bash
case "$*" in *checkip*) echo 198.51.100.9 ;; *) echo 200 ;; esac
"""

CONF = """AWS_PROFILE=bmu-test
AWS_REGION=us-west-2
BMU_ENV_NAME=dev
{museums}
ENV_LABEL="test"
ALWAYS_RUN_TIME=false
"""
QA = "https://pahma.qa.collectionspace.org"
BAMPFA = "https://bampfa.qa.collectionspace.org"


@pytest.fixture
def tree(tmp_path):
    """A copy of deploy/aws.sh in its own tree, with stand-in aws and terraform first on the PATH."""
    (tmp_path / "deploy" / "environments").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "deploy" / "aws.sh")
    (tmp_path / "backend" / "bmu" / "tenants").mkdir(parents=True)  # each museum needs its configuration
    for museum in ("pahma", "bampfa"):  # bampfa: a test-only museum
        (tmp_path / "backend" / "bmu" / "tenants" / f"{museum}.yaml").write_text("")
    (tmp_path / "log").mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("aws", FAKE_AWS), ("terraform", FAKE_TERRAFORM), ("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(stat.S_IRWXU)
    return tmp_path


def write_env(tree, url=QA, account=ACCOUNT, local_extra="", museums=None):
    """museums: a CSPACE_TENANTS value; without it, the one-museum form TENANT=pahma on CSPACE_URL=url."""
    envs = tree / "deploy" / "environments"
    (envs / "t.conf").write_text(CONF.format(museums=f'CSPACE_TENANTS="{museums}"' if museums else f"CSPACE_URL={url}\nTENANT=pahma"))
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


# ---- the museums and the museum check ---------------------------------------------------------------------------------

def tf_tenants(tree, name="plan-app"):
    """The tenants map passed to the last stand-in terraform plan, apply or destroy, as a dict."""
    return json.loads(tf_args(tree, name)["tenants"].replace('"=', '":'))


def test_one_museum_from_tenant_and_cspace_url(tree):
    write_env(tree, url=QA + "/")  # a trailing slash is the same server
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    assert f'PLANNED tenants={{"pahma"="{QA}"}}' in r.stdout


def test_several_museums_from_cspace_tenants(tree):
    write_env(tree, museums=f"pahma={QA}/  bampfa={BAMPFA}")
    r = run(tree, "plan", museums=f"pahma={QA} bampfa={BAMPFA}")
    assert r.returncode == 0, r.stderr
    assert tf_tenants(tree) == {"pahma": QA, "bampfa": BAMPFA}
    assert "Adding" not in r.stdout


@pytest.mark.parametrize("museums, message", [
    (f"pahma={QA} pahma={QA}", "lists pahma twice"),
    (f"pahma{QA}", "isn't museum=server"),
    (f"PAHMA={QA}", "isn't museum=server"),
    ("pahma=https://pahma.qa.collectionspace.org/cspace-services", "must be an address alone"),
    ("pahma=https://pahma.qa.collectionspace.org{x}", "must be an address alone"),  # nothing that isn't a host name
    (f"cinefiles={QA}", "no configuration for the museum 'cinefiles'"),
])
def test_bad_museum_lists_are_refused(tree, museums, message):
    write_env(tree, museums=museums)
    r = run(tree, "plan")
    assert r.returncode == 1 and message in r.stderr, r.stderr
    assert not (tree / "log" / "terraform-plan-app").exists()


def test_cspace_tenants_with_tenant_or_cspace_url_is_refused(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra=f"CSPACE_URL={QA}\n")
    r = run(tree, "plan")
    assert r.returncode == 1 and "not both" in r.stderr


def test_a_museums_new_server_is_refused_before_terraform_changes_anything(tree):
    write_env(tree, museums="pahma=https://other.collectionspace.org")
    for command in ("plan", "pause", "resume"):
        r = run(tree, command, museums=f"pahma={QA}")
        assert r.returncode == 1, command
        assert "Stopped; nothing was changed" in r.stderr
        assert f"was deployed with pahma on {QA}" in r.stderr and "now say https://other.collectionspace.org" in r.stderr
        assert "PLANNED" not in r.stdout and not (tree / "log" / "terraform-apply-app").exists()


def test_a_deploy_to_a_new_server_stops_before_building_the_image(tree):
    write_env(tree, url="https://other.collectionspace.org")
    r = run(tree, "deploy", museums=f"pahma={QA}")
    assert r.returncode == 1
    assert "Stopped; nothing was changed" in r.stderr
    assert "DOCKER" not in r.stdout and "Image repository" not in r.stdout


def test_a_museum_can_be_added(tree):
    write_env(tree, museums=f"pahma={QA} bampfa={BAMPFA}")
    r = run(tree, "resume", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    assert f"Adding the museum bampfa ({BAMPFA})" in r.stdout
    assert tf_tenants(tree, "apply-app") == {"pahma": QA, "bampfa": BAMPFA}


def test_removing_a_museum_without_unfinished_jobs_needs_its_name_typed(tree):
    write_env(tree, museums=f"pahma={QA}")
    r = run(tree, "resume", answers="pahma\n", museums=f"pahma={QA} bampfa={BAMPFA}")
    assert r.returncode == 1 and "Stopped; nothing was changed" in r.stderr
    assert not (tree / "log" / "terraform-apply-app").exists()
    r = run(tree, "resume", answers="bampfa\n", museums=f"pahma={QA} bampfa={BAMPFA}")
    assert r.returncode == 0, r.stderr
    assert "bampfa is no longer in the settings" in r.stdout and "unreadable" in r.stdout
    assert tf_tenants(tree, "apply-app") == {"pahma": QA}
    query = (tree / "log" / "dynamodb-query").read_text().splitlines()
    assert query[query.index("--table-name") + 1] == "bmu-dev-jobs" and query[query.index("--index-name") + 1] == "tenant"
    values = json.loads(query[query.index("--expression-attribute-values") + 1])
    assert values == {":t": {"S": "bampfa"}, ":meta": {"S": "META"}, ":done": {"S": "Completed"}}
    names = json.loads(query[query.index("--expression-attribute-names") + 1])
    assert names == {"#t": "tenant", "#k": "SK", "#s": "status"}
    assert query[query.index("--key-condition-expression") + 1] == "#t = :t"
    assert query[query.index("--filter-expression") + 1] == "#k = :meta AND #s <> :done"  # jobs, not their rows
    assert query[query.index("--select") + 1] == "COUNT" and query[query.index("--query") + 1] == "Count"


def test_plan_shows_a_removal_without_asking(tree):
    write_env(tree, museums=f"pahma={QA}")
    r = run(tree, "plan", museums=f"pahma={QA} bampfa={BAMPFA}")
    assert r.returncode == 0, r.stderr
    assert "bampfa is no longer in the settings" in r.stdout and "PLANNED" in r.stdout


def test_a_museum_with_unfinished_jobs_is_never_removed(tree):
    write_env(tree, museums=f"pahma={QA}")
    for command in ("plan", "resume"):
        r = run(tree, command, answers="bampfa\n", museums=f"pahma={QA} bampfa={BAMPFA}", unfinished_jobs=2)
        assert r.returncode == 1, command
        assert "it has 2 unfinished job(s)" in r.stderr and "Stopped; nothing was changed" in r.stderr
        assert "PLANNED" not in r.stdout and not (tree / "log" / "terraform-apply-app").exists()


def test_a_museum_is_never_removed_where_data_is_protected(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra="PROTECT_DATA=true\n")
    r = run(tree, "resume", answers="bampfa\n", museums=f"pahma={QA} bampfa={BAMPFA}")
    assert r.returncode == 1 and "protects its data" in r.stderr
    assert not (tree / "log" / "dynamodb-query").exists()


def test_an_environment_deployed_before_museums_were_listed_is_refused(tree):
    """No migration (a prototype): its single staging key and secret would be replaced. Destroy, then deploy."""
    write_env(tree)
    for command in ("deploy", "plan", "resume"):
        r = run(tree, command, url=QA)  # the state has the old cspace_url output and no museums
        assert r.returncode == 1, command
        assert "deployed before environments listed their museums" in r.stderr and "./bmu aws destroy" in r.stderr
        assert "DOCKER" not in r.stdout and "PLANNED" not in r.stdout and not (tree / "log" / "terraform-apply-app").exists()


def test_a_first_deploy_checks_nothing(tree):
    write_env(tree, museums=f"pahma={QA} bampfa={BAMPFA}")
    r = run(tree, "deploy")  # the state has no museums output yet
    assert r.returncode == 0, r.stderr
    assert "Adding" not in r.stdout and tf_tenants(tree, "apply-app") == {"pahma": QA, "bampfa": BAMPFA}
    assert f"  pahma: {QA}" in r.stdout and f"  bampfa: {BAMPFA}" in r.stdout  # where jobs create real records


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
    r = run(tree, "plan", state_rc=0, museums=f"pahma={QA}")
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
    r = run(tree, "plan", museums=f"pahma={SIM_URL}", sim_image="repo/bmu-dev-fakecspace:abc")
    assert r.returncode == 0, r.stderr
    args = tf_args(tree, "plan-app")
    assert tf_tenants(tree) == {"pahma": SIM_URL} and args["simulated_cspace"] == "true"
    assert args["fakecspace_image_uri"] == "repo/bmu-dev-fakecspace:abc"
    assert args["env_label"] == "AWS · t · simulated CollectionSpace"


def test_a_label_set_in_the_local_settings_is_kept_with_the_simulator(tree):
    write_env(tree, local_extra='SIMULATED_CSPACE=true\nENV_LABEL="My sandbox"\n')
    r = run(tree, "plan", museums=f"pahma={SIM_URL}", sim_image="x:1")
    assert r.returncode == 0, r.stderr
    assert tf_args(tree, "plan-app")["env_label"] == "My sandbox"


def test_without_the_simulator_nothing_changes(tree):
    write_env(tree)
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    args = tf_args(tree, "plan-app")
    assert args["simulated_cspace"] == "false" and args["fakecspace_image_uri"] == "" and args["env_label"] == "test"


def test_turning_the_simulator_on_in_a_deployed_environment_is_a_change_of_server(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\n")
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 1
    assert f"now say {SIM_URL}" in r.stderr and "Stopped; nothing was changed" in r.stderr


def test_the_simulator_serves_pahma_alone_whatever_the_museums_in_the_settings(tree):
    write_env(tree, museums=f"pahma={QA} bampfa={BAMPFA}", local_extra="SIMULATED_CSPACE=true\n")
    r = run(tree, "plan", museums=f"pahma={SIM_URL}", sim_image="x:1")
    assert r.returncode == 0, r.stderr
    assert tf_tenants(tree) == {"pahma": SIM_URL}


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
    assert tf_tenants(tree, "apply-app") == {"pahma": SIM_URL} and args["simulated_cspace"] == "true"
    assert (tree / "log" / "secret").read_text() == '{"username":"bmureader","password":"bmureader"}'
    assert (tree / "log" / "secret-id").read_text() == "bmu-dev/cspace-reader/pahma\n"
    assert "simulated CollectionSpace" in r.stdout and "real records" not in r.stdout


def test_a_later_deploy_with_the_simulator_leaves_the_read_only_account_alone(tree):
    write_env(tree, local_extra="SIMULATED_CSPACE=true\n")
    r = run(tree, "deploy", museums=f"pahma={SIM_URL}", sim_image="x:1", secret_versions=1)
    assert r.returncode == 0, r.stderr
    assert not (tree / "log" / "secret").exists()


def test_a_deploy_without_the_simulator_builds_one_image_and_leaves_the_secret_alone(tree):
    write_env(tree)
    r = run(tree, "deploy", museums=f"pahma={QA}")
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


# ---- the read-only accounts' secrets, one per museum ----------------------------------------------------------------

def test_reader_secret_with_one_museum_needs_no_name(tree):
    write_env(tree)
    r = run(tree, "reader-secret", answers="reader\nsecret-value\nsecret-value\n")
    assert r.returncode == 0, r.stderr
    assert (tree / "log" / "secret-id").read_text() == "bmu-dev/cspace-reader/pahma\n"
    assert "secret-value" not in r.stdout + r.stderr  # never shown


def test_reader_secret_with_several_museums_asks_which(tree):
    write_env(tree, museums=f"pahma={QA} bampfa={BAMPFA}")
    r = run(tree, "reader-secret")
    assert r.returncode == 1 and "one of: pahma bampfa" in r.stderr
    r = run(tree, "reader-secret", "cinefiles")
    assert r.returncode == 1 and "doesn't serve a museum 'cinefiles'" in r.stderr
    r = run(tree, "reader-secret", "bampfa", answers="reader\nsecret-value\nsecret-value\n")
    assert r.returncode == 0, r.stderr
    assert (tree / "log" / "secret-id").read_text() == "bmu-dev/cspace-reader/bampfa\n"
    assert f"bampfa's read-only CollectionSpace account on {BAMPFA}" in r.stdout


def test_status_lists_each_deployed_museum_and_its_read_only_account(tree):
    write_env(tree, museums=f"pahma={QA} bampfa={BAMPFA}")
    r = run(tree, "status", museums=f"bampfa={BAMPFA} pahma={QA}", secret_versions=0)  # Terraform's order: by name
    assert r.returncode == 0, r.stderr
    assert f"  pahma: {QA}" in r.stdout and f"  bampfa: {BAMPFA}" in r.stdout
    assert "NOT SET (./bmu aws reader-secret bampfa)" in r.stdout and "plan shows the change" not in r.stdout
    r = run(tree, "status", museums=f"pahma={QA}", secret_versions=1)
    assert "set, last changed 2026-10-07" in r.stdout and "  bampfa:" not in r.stdout  # what is deployed, not the settings
    assert "./bmu aws plan shows the change" in r.stdout


# ---- review 29 October 2026, section 5 -------------------------------------------------------------------------------

def test_a_real_collectionspace_must_be_https(tree):
    write_env(tree, museums="pahma=http://pahma.qa.collectionspace.org")
    r = run(tree, "plan")
    assert r.returncode == 1 and "must be https://" in r.stderr, r.stderr
    assert not (tree / "log" / "terraform-plan-app").exists()


def test_an_environment_whose_data_is_protected_is_never_destroyed(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra="PROTECT_DATA=true\n")
    r = run(tree, "destroy", answers="t\n")
    assert r.returncode == 1 and "can't be destroyed" in r.stderr, r.stderr
    assert not (tree / "log" / "terraform-destroy-app").exists()


@pytest.mark.parametrize("extra, waf", [("", "false"), ("PROTECT_DATA=true\n", "true"),
                                        ("PROTECT_DATA=true\nWAF_ENABLED=false\n", "false"), ("WAF_ENABLED=true\n", "true")])
def test_with_alb_the_waf_comes_with_protected_data_unless_the_settings_say_otherwise(tree, extra, waf):
    write_env(tree, museums=f"pahma={QA}", local_extra=ALB + extra)
    r = run(tree, "plan", museums=f"pahma={QA}", front_door="alb")
    assert r.returncode == 0, r.stderr
    assert tf_args(tree, "plan-app")["waf_enabled"] == waf


def test_a_cloudfront_environment_has_no_waf(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra="PROTECT_DATA=true\n")
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    assert tf_args(tree, "plan-app")["waf_enabled"] == "false"
    write_env(tree, museums=f"pahma={QA}", local_extra="WAF_ENABLED=true\n")
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 1 and "WAF_ENABLED=true needs FRONT_DOOR=alb" in r.stderr


def test_https_to_the_load_balancer_needs_both_settings(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra="ORIGIN_DOMAIN=bmu-dev-origin.example.berkeley.edu\n")
    r = run(tree, "plan")
    assert r.returncode == 1 and "ORIGIN_DOMAIN and ORIGIN_CERTIFICATE_ARN together" in r.stderr
    arn = "arn:aws:acm:us-west-2:111122223333:certificate/abc"
    write_env(tree, museums=f"pahma={QA}", local_extra=f"ORIGIN_DOMAIN=bmu-dev-origin.example.berkeley.edu\nORIGIN_CERTIFICATE_ARN={arn}\n")
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    args = tf_args(tree, "plan-app")
    assert args["origin_domain"] == "bmu-dev-origin.example.berkeley.edu" and args["origin_certificate_arn"] == arn


# ---- ci-role: the role CI assumes to sign in to ECR Public (deploy/terraform/ci) -----------------------------------
def test_ci_role_creates_the_oidc_provider_when_the_account_has_none_and_prints_the_variable_command(tree):
    write_env(tree)
    r = run(tree, "ci-role")
    assert r.returncode == 0, r.stderr
    apply = (tree / "log" / "terraform-apply-ci").read_text().splitlines()
    assert f"account_id={ACCOUNT}" in "\n".join(apply) and "-var=create_oidc_provider=true" in apply
    assert "gh variable set ECR_PUBLIC_ROLE_ARN --repo ets-berkeley-edu/cspace-bulk-media-uploader" in r.stdout
    assert f"arn:aws:iam::{ACCOUNT}:role/bmu-ci-ecr-public-pull" in r.stdout


def test_ci_role_uses_an_oidc_provider_the_account_already_has(tree):
    write_env(tree)
    existing = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
    r = run(tree, "ci-role", oidc_providers=existing)
    assert r.returncode == 0, r.stderr
    assert "-var=create_oidc_provider=false" in (tree / "log" / "terraform-apply-ci").read_text().splitlines()
    assert "already has GitHub's OIDC provider" in r.stdout


def test_ci_role_keeps_an_oidc_provider_its_own_state_created(tree):
    write_env(tree)
    existing = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
    r = run(tree, "ci-role", oidc_providers=existing, ci_state="aws_iam_openid_connect_provider.github[0]")
    assert r.returncode == 0, r.stderr
    assert "-var=create_oidc_provider=true" in (tree / "log" / "terraform-apply-ci").read_text().splitlines()


# ---- the front door (FRONT_DOOR, DOMAIN_NAME) and REQUIRE_CLEAN -------------------------------------------------------

ALB = ('FRONT_DOOR=alb\nVPC_ID=vpc-00000000000000001\nAPP_SUBNET_IDS="subnet-0000000000000000a,subnet-0000000000000000b"\n'
       'LB_SUBNET_IDS="subnet-0000000000000000c,subnet-0000000000000000d"\nDOMAIN_NAME=bmu-qa.example.invalid\n')


def test_by_default_the_front_door_is_cloudfront_with_no_domain(tree):
    write_env(tree, museums=f"pahma={QA}")
    r = run(tree, "deploy", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    args = tf_args(tree, "apply-app")
    assert args["front_door"] == "cloudfront" and args["domain_name"] == "" and args["certificate_arn"] == ""
    assert tf_args(tree, "apply-registry")["domain_name"] == ""
    assert "15-25 minutes (CloudFront)" in r.stdout and "DNS:" not in r.stdout


def test_alb_passes_the_domain_and_the_registrys_certificate(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra=ALB)
    r = run(tree, "deploy", museums=f"pahma={QA}", front_door="alb")
    assert r.returncode == 0, r.stderr
    assert tf_args(tree, "apply-registry")["domain_name"] == "bmu-qa.example.invalid"
    args = tf_args(tree, "apply-app")
    assert args["front_door"] == "alb" and args["domain_name"] == "bmu-qa.example.invalid"
    assert args["certificate_arn"] == f"arn:aws:acm:us-west-2:{ACCOUNT}:certificate/abc"
    assert args["lb_subnet_ids"] == '["subnet-0000000000000000c","subnet-0000000000000000d"]'
    assert args["waf_managed_rules"] == "count"
    assert "DNS: bmu-qa.example.invalid must point at the load balancer bmu-dev-123.us-west-2.elb.amazonaws.com" in r.stdout


def test_while_the_certificate_isnt_issued_deploy_prints_its_record_and_stops_before_the_app(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra=ALB)
    r = run(tree, "deploy", museums=f"pahma={QA}", front_door="alb", cert_status="PENDING_VALIDATION")
    assert r.returncode == 1, r.stdout
    assert "The certificate for bmu-qa.example.invalid is PENDING_VALIDATION" in r.stdout
    assert "_abc.bmu-qa.example.invalid." in r.stdout and "_xyz.acm-validations.aws." in r.stdout
    assert "once the record is in DNS and the certificate is ISSUED" in r.stderr
    assert "DOCKER build" not in r.stdout and not (tree / "log" / "terraform-apply-app").exists()


@pytest.mark.parametrize("drop, message", [("VPC_ID", "needs VPC_ID and LB_SUBNET_IDS"), ("LB_SUBNET_IDS", "needs VPC_ID and LB_SUBNET_IDS"),
                                           ("DOMAIN_NAME", "needs DOMAIN_NAME")])
def test_alb_needs_an_existing_vpcs_public_subnets_and_a_domain(tree, drop, message):
    extra = "".join(line + "\n" for line in ALB.splitlines() if not line.startswith(drop + "="))
    if drop == "VPC_ID":
        extra = "".join(line + "\n" for line in extra.splitlines() if not line.startswith(("APP_SUBNET_IDS=", "LB_SUBNET_IDS=")))
    write_env(tree, museums=f"pahma={QA}", local_extra=extra)
    r = run(tree, "plan", museums=f"pahma={QA}", front_door="alb")
    assert r.returncode == 1 and message in r.stderr, r.stderr


def test_the_domain_goes_only_in_the_local_settings(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra=ALB)
    conf = tree / "deploy" / "environments" / "t.conf"
    conf.write_text(conf.read_text() + "DOMAIN_NAME=bmu-qa.example.invalid\n")
    r = run(tree, "plan", museums=f"pahma={QA}", front_door="alb")
    assert r.returncode == 1 and "not in" in r.stderr and "DOMAIN_NAME" in r.stderr


def test_a_domain_or_an_origin_domain_belongs_to_one_front_door(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra="DOMAIN_NAME=bmu-qa.example.invalid\n")
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 1 and "DOMAIN_NAME is for FRONT_DOOR=alb" in r.stderr
    arn = "arn:aws:acm:us-west-2:111122223333:certificate/abc"
    write_env(tree, museums=f"pahma={QA}", local_extra=ALB + f"ORIGIN_DOMAIN=bmu-dev-origin.example.invalid\nORIGIN_CERTIFICATE_ARN={arn}\n")
    r = run(tree, "plan", museums=f"pahma={QA}", front_door="alb")
    assert r.returncode == 1 and "are for FRONT_DOOR=cloudfront" in r.stderr


@pytest.mark.parametrize("deployed, now", [(None, "alb"), ("cloudfront", "alb"), ("alb", "cloudfront")])
def test_a_deployed_environments_front_door_never_changes(tree, deployed, now):
    """None: deployed before FRONT_DOOR existed, so behind CloudFront."""
    write_env(tree, museums=f"pahma={QA}", local_extra=ALB if now == "alb" else "")
    fake = {"museums": f"pahma={QA}"} | ({"front_door": deployed} if deployed else {})
    for cmd in ("plan", "deploy", "pause", "destroy"):
        r = run(tree, cmd, answers="t\n", **fake)
        assert r.returncode == 1 and f"deployed with FRONT_DOOR={deployed or 'cloudfront'}" in r.stderr, (cmd, r.stderr)
    assert not list((tree / "log").glob("terraform-*-app")), "nothing was planned, applied or destroyed"
    assert "DOCKER build" not in r.stdout


def test_status_shows_the_front_door(tree):
    write_env(tree, museums=f"pahma={QA}", local_extra=ALB)
    r = run(tree, "status", museums=f"pahma={QA}", front_door="alb", domain="bmu-qa.example.invalid")
    assert r.returncode == 0, r.stderr
    assert "Front door: the load balancer bmu-dev-123.us-west-2.elb.amazonaws.com, on bmu-qa.example.invalid" in r.stdout


def git(tree, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=tree, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def clean_checkout(tree, tmp_path_factory):
    """tree as a git checkout of main, with an origin (a bare repository) at the same commit."""
    origin = tmp_path_factory.mktemp("origin")
    git(origin, "init", "--bare", "-b", "main")
    (tree / ".gitignore").write_text("log/\nbin/\n*.local.conf\n")
    git(tree, "init", "-b", "main")
    git(tree, "remote", "add", "origin", str(origin))
    return tree


def commit_and_push(tree):
    git(tree, "add", "-A")
    git(tree, "commit", "-m", "c")
    git(tree, "push", "-q", "origin", "main")


def test_require_clean_deploys_from_a_clean_checkout_on_main(clean_checkout):
    tree = clean_checkout
    write_env(tree, museums=f"pahma={QA}", local_extra="REQUIRE_CLEAN=true\n")
    commit_and_push(tree)
    r = run(tree, "deploy", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    assert "-dirty" not in tf_args(tree, "apply-app")["image_uri"]


def test_require_clean_refuses_changes_or_untracked_files(clean_checkout):
    tree = clean_checkout
    write_env(tree, museums=f"pahma={QA}", local_extra="REQUIRE_CLEAN=true\n")
    commit_and_push(tree)
    (tree / "medium.jpg").write_text("x")
    for cmd in ("deploy", "pause"):
        r = run(tree, cmd, museums=f"pahma={QA}")
        assert r.returncode == 1 and "only from a clean checkout" in r.stderr, (cmd, r.stderr)
    assert "DOCKER build" not in r.stdout and not list((tree / "log").glob("terraform-apply-*"))


def test_require_clean_refuses_a_head_that_isnt_on_origin_main(clean_checkout):
    tree = clean_checkout
    write_env(tree, museums=f"pahma={QA}", local_extra="REQUIRE_CLEAN=true\n")
    commit_and_push(tree)
    (tree / "change.txt").write_text("x")
    git(tree, "add", "-A")
    git(tree, "commit", "-m", "not pushed")
    r = run(tree, "deploy", museums=f"pahma={QA}")
    assert r.returncode == 1 and "isn't on origin/main" in r.stderr, r.stderr
    assert not list((tree / "log").glob("terraform-apply-*"))


def test_without_require_clean_a_dirty_checkout_deploys_with_a_dirty_tag(clean_checkout):
    tree = clean_checkout
    write_env(tree, museums=f"pahma={QA}")
    commit_and_push(tree)
    (tree / "medium.jpg").write_text("x")
    r = run(tree, "deploy", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    assert "-dirty-" in tf_args(tree, "apply-app")["image_uri"]


# ---- settings in SSM Parameter Store (SETTINGS=ssm; design: Deploys, BP4) -------------------------------------------

SSM_LOCAL = "SETTINGS=ssm\nADMIN_PROFILE=bmu-admin\n"


def ssm(tree):
    """The stand-in SSM's parameters under /bmu-dev/settings/, as {SETTING: value}."""
    root = tree / "log" / "ssm" / "bmu-dev" / "settings"
    return {p.name: p.read_text() for p in root.iterdir()} if root.exists() else {}


def ssm_writes(tree):
    log = tree / "log" / "ssm-writes"
    return log.read_text().splitlines() if log.exists() else []


def push(tree, answers="y\n"):
    return run(tree, "settings", "push", answers=answers)


def test_settings_needs_an_environment_that_keeps_them_in_ssm(tree):
    write_env(tree)
    r = push(tree)
    assert r.returncode == 1
    assert "add SETTINGS=ssm to" in r.stderr and ssm(tree) == {}


def test_settings_push_shows_the_changes_and_writes_them_as_the_administrator_only_when_told(tree):
    write_env(tree, local_extra=SSM_LOCAL)
    r = push(tree, answers="n\n")
    assert r.returncode == 1
    assert "  + ALLOWED_CIDRS=203.0.113.7/32" in r.stdout and "  + CSPACE_URL=" + QA in r.stdout
    assert ssm(tree) == {}
    r = push(tree)
    assert r.returncode == 0, r.stderr
    settings = ssm(tree)
    assert settings["ACCOUNT_ID"] == ACCOUNT and settings["ALLOWED_CIDRS"] == "203.0.113.7/32"
    assert settings["TENANT"] == "pahma" and settings["CSPACE_URL"] == QA
    assert settings["FRONT_DOOR"] == "cloudfront"  # load_env's defaults go too, so SSM says what a deploy uses
    # What says how to reach the account, SETTINGS itself and REQUIRE_CLEAN stay in the files.
    assert not {"AWS_PROFILE", "AWS_REGION", "BMU_ENV_NAME", "ADMIN_PROFILE", "SETTINGS", "REQUIRE_CLEAN"} & set(settings)
    writes = [w for w in ssm_writes(tree) if w.startswith("put ")]
    assert writes and all(w.endswith(" as bmu-admin") for w in writes)  # never as the deployer (bmu-test)
    assert any("Key=project,Value=bmu" in w for w in ssm_writes(tree))
    assert "SSM already has these settings" in push(tree).stdout


def test_settings_push_removes_a_setting_the_files_no_longer_have(tree):
    local = write_env(tree, local_extra=SSM_LOCAL + 'ENV_LABEL="AWS · test"\n')
    push(tree)
    local.write_text(local.read_text().replace('ENV_LABEL="AWS · test"\n', ""))
    r = push(tree)
    assert r.returncode == 0, r.stderr
    assert "  ~ ENV_LABEL=test (was AWS · test)" in r.stdout and ssm(tree)["ENV_LABEL"] == "test"


def test_with_settings_in_ssm_a_command_uses_ssms_and_says_where_the_files_differ(tree):
    local = write_env(tree, local_extra=SSM_LOCAL)
    push(tree)
    local.write_text(local.read_text().replace("203.0.113.7/32", "198.51.100.0/24"))
    r = run(tree, "plan", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    assert tf_args(tree, "plan-app")["allowed_cidrs"] == '["203.0.113.7/32"]'
    assert "differ from SSM in ALLOWED_CIDRS; SSM's are used" in r.stderr
    assert ssm_writes(tree) and all(w.endswith(" as bmu-admin") or w.startswith("tag ") for w in ssm_writes(tree))


def test_with_no_settings_in_ssm_a_command_says_who_puts_them_there(tree):
    write_env(tree, local_extra=SSM_LOCAL)
    r = run(tree, "plan")
    assert r.returncode == 1
    assert "has none under /bmu-dev/settings/" in r.stderr and "./bmu aws settings push --env t" in r.stderr


def test_settings_in_ssm_from_another_account_are_refused(tree):
    write_env(tree, local_extra=SSM_LOCAL)
    push(tree)
    (tree / "log" / "ssm" / "bmu-dev" / "settings" / "ACCOUNT_ID").write_text("999988887777")
    r = run(tree, "plan")
    assert r.returncode == 1
    assert "SSM's ACCOUNT_ID for 't' (999988887777) isn't the account it is in" in r.stderr


def test_the_deployer_never_writes_a_setting_to_ssm(tree):
    local = write_env(tree, local_extra=SSM_LOCAL)
    push(tree)
    before = ssm_writes(tree)
    r = run(tree, "allow-my-ip")
    assert r.returncode == 1
    assert 'set ALLOWED_CIDRS="203.0.113.7/32,198.51.100.9/32" in' in r.stderr and "settings push --env t" in r.stderr
    # With no allowed addresses in SSM, a deploy stops instead of adding this computer's.
    local.write_text(local.read_text().replace('ALLOWED_CIDRS="203.0.113.7/32"\n', ""))
    push(tree)
    assert "ALLOWED_CIDRS" not in ssm(tree)
    before = ssm_writes(tree)
    r = run(tree, "deploy")
    assert r.returncode == 1
    assert "has no ALLOWED_CIDRS in SSM" in r.stderr
    assert ssm_writes(tree) == before and "ALLOWED_CIDRS" not in local.read_text()


def test_settings_show_marks_what_the_files_here_disagree_with(tree):
    local = write_env(tree, local_extra=SSM_LOCAL)
    push(tree)
    (tree / "log" / "ssm" / "bmu-dev" / "settings" / "OLD_SETTING").write_text("x")
    local.write_text(local.read_text().replace("203.0.113.7/32", "198.51.100.0/24"))
    r = run(tree, "settings", "show")
    assert r.returncode == 0, r.stderr
    assert "  ALLOWED_CIDRS=203.0.113.7/32   (the files here: 198.51.100.0/24)" in r.stdout
    assert f"  CSPACE_URL={QA}\n" in r.stdout
    assert "  OLD_SETTING=x   (not a setting ./bmu aws reads; ignored)" in r.stdout


def test_settings_delete_waits_until_the_environment_is_destroyed(tree):
    write_env(tree, local_extra=SSM_LOCAL)
    push(tree)
    r = run(tree, "settings", "delete", answers="t\n", state_json='{"resources": [{"type": "x"}]}')
    assert r.returncode == 1
    assert "is still deployed" in r.stderr and ssm(tree)
    r = run(tree, "settings", "delete", answers="nope\n")
    assert r.returncode == 1 and ssm(tree)
    r = run(tree, "settings", "delete", answers="t\n")
    assert r.returncode == 0, r.stderr
    assert ssm(tree) == {}
    assert (tree / "deploy" / "environments" / "t.local.conf").exists()  # the files stay


def test_status_says_where_the_settings_are(tree):
    write_env(tree, local_extra=SSM_LOCAL)
    push(tree)
    r = run(tree, "status", museums=f"pahma={QA}")
    assert r.returncode == 0, r.stderr
    assert "Settings: SSM Parameter Store, /bmu-dev/settings/" in r.stdout
