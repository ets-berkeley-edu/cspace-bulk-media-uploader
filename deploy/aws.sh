#!/usr/bin/env bash
# ./bmu aws — deploy the BMU to AWS and look after it. Run through ./bmu (./bmu aws help).
#
#   ./bmu aws deploy        build the image, push it, then show Terraform's plan and apply it; prints the address
#   ./bmu aws plan          show what a deploy of the running image would change, without changing anything
#   ./bmu aws status        the services' tasks, the image they run and the allowed addresses
#   ./bmu aws url           the address
#   ./bmu aws logs web|worker|fakecspace   follow a service's logs (the last 30 minutes first)
#   ./bmu aws pause         stop both services to save money (the data stays); ./bmu aws resume starts them
#   ./bmu aws allow-my-ip   add this computer's current address to the allowlist
#   ./bmu aws reader-secret set or change the read-only CollectionSpace account's sign-in (asks; nothing is shown or saved here)
#   ./bmu aws destroy       delete everything in AWS for this environment, data included (asks first)
#   ./bmu aws init          point Terraform at this environment's state, to run terraform commands yourself
#
# Which environment: --env NAME or BMU_AWS_ENV (default personal-dev). Its settings are in
# deploy/environments/NAME.conf; NAME.local.conf (not committed) holds the account number and allowed addresses.
# Sign in first with: aws sso login --profile <the environment's AWS_PROFILE>. Nothing here handles a password or key,
# except reader-secret, which passes what you type straight to AWS Secrets Manager.
# Terraform (deploy/terraform) creates everything; its state is in an S3 bucket in the same account, which the first
# deploy creates. BMU_AWS_YES=1 skips Terraform's "yes" prompt. Works with the macOS bash (3.2).
# SIMULATED_CSPACE=true (in the settings) runs the simulated CollectionSpace in the environment instead of using a real
# one. A deployed environment's CollectionSpace server never changes (check_server), and the first use of an
# environment on a computer asks first if the account already has one by that name (check_not_someone_elses).
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_DIR=deploy/environments
TF_DIR=deploy/terraform

die() { echo "$*" >&2; exit 1; }

# ---- arguments ---------------------------------------------------------------------------------------------------
ENV="${BMU_AWS_ENV:-personal-dev}"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --env) [ $# -ge 2 ] || die "--env needs a name"; ENV="$2"; shift 2 ;;
    --env=*) ENV="${1#--env=}"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}
CMD="${1:-help}"; shift || true

# ---- settings -----------------------------------------------------------------------------------------------------
load_env() {
  CONF="$ENV_DIR/$ENV.conf"
  LOCAL="$ENV_DIR/$ENV.local.conf"
  URL_FILE="$ENV_DIR/$ENV.url"
  [ -f "$CONF" ] || die "No settings for environment '$ENV' ($CONF). Environments: $(ls "$ENV_DIR" | sed -n 's/\.conf$//p' | grep -v '\.local$' | tr '\n' ' ')"
  ACCOUNT_ID="" ALLOWED_CIDRS="" SIMULATED_CSPACE="" ENV_LABEL=""
  # shellcheck disable=SC1090
  . "$CONF"
  local conf_label="$ENV_LABEL"
  # shellcheck disable=SC1090
  [ -f "$LOCAL" ] && . "$LOCAL"
  : "${AWS_PROFILE:?set AWS_PROFILE in $CONF}" "${AWS_REGION:?set AWS_REGION in $CONF}" "${BMU_ENV_NAME:?set BMU_ENV_NAME in $CONF}"
  NAME="bmu-$BMU_ENV_NAME"   # the cluster's name and the prefix of every resource
  CSPACE_URL="${CSPACE_URL%/}"   # one spelling of the server, for the server check below
  case "${SIMULATED_CSPACE:=false}" in true|false) ;; *) die "SIMULATED_CSPACE must be true or false ($CONF, $LOCAL)." ;; esac
  if [ "$SIMULATED_CSPACE" = true ]; then
    [ "${PROTECT_DATA:-false}" != true ] ||
      die "SIMULATED_CSPACE=true can't be used with PROTECT_DATA=true: the simulator's data is lost on every restart, and its accounts' passwords are public."
    CSPACE_URL="$(sim_url)"   # CSPACE_URL in the settings is ignored
    [ "$ENV_LABEL" != "$conf_label" ] || ENV_LABEL="AWS · $ENV · simulated CollectionSpace"   # unless .local.conf sets one
  fi
  export AWS_PAGER="" AWS_PROFILE AWS_REGION   # Terraform signs in with the same profile
  # Keys in the shell would win over the profile in Terraform (though not in "aws --profile"): never use them here.
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  export TF_IN_AUTOMATION=1
}

aws_() { aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

# The simulated CollectionSpace's address in the VPC (Cloud Map). The same as local.fakecspace_url in
# deploy/terraform/app/fakecspace.tf; Terraform refuses any other with simulated_cspace (variables.tf).
sim_url() { echo "http://fakecspace.$NAME.internal:8180"; }

save_local() {  # save_local KEY VALUE: set one setting in the environment's .local.conf
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  { [ -f "$LOCAL" ] && grep -v "^$key=" "$LOCAL" || echo "# ./bmu aws settings for '$ENV' on this computer only (not committed)."; } > "$tmp"
  echo "$key=\"$value\"" >> "$tmp"
  mv "$tmp" "$LOCAL"
}

# First use of an environment on this computer: if the account already holds Terraform state for this environment's
# name, it was deployed from somewhere else. That may be the same person on another computer or clone, or someone
# else sharing the account, whose environment a deploy from here would take over (code, allowed addresses, label).
check_not_someone_elses() {  # check_not_someone_elses ACCOUNT
  local key ok found=""
  for key in app registry; do
    aws_ s3api head-object --bucket "bmu-tfstate-$1-$AWS_REGION" --key "bmu/$BMU_ENV_NAME/$key.tfstate" >/dev/null 2>&1 &&
      found="s3://bmu-tfstate-$1-$AWS_REGION/bmu/$BMU_ENV_NAME/" && break
  done
  [ -n "$found" ] || return 0
  echo "This account already has a BMU environment named '$BMU_ENV_NAME' (its Terraform state is in $found),"
  echo "deployed from another computer or clone, or deployed once and destroyed. If it's yours, carry on."
  echo "If it may be someone else's, answer no and set BMU_ENV_NAME to a name of your own in $LOCAL:"
  echo "a deploy from here would replace their environment's code and allowed addresses."
  read -r -p "Is the '$BMU_ENV_NAME' environment in this account yours? [y/N] " ok
  case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
}

# Signed in, and to the account this environment was first deployed to.
check_account() {
  local who
  who="$(aws_ sts get-caller-identity --query Account --output text 2>/dev/null)" ||
    die "Not signed in to AWS for '$ENV'. Run: aws sso login --profile $AWS_PROFILE"
  if [ -z "$ACCOUNT_ID" ]; then
    echo "Profile $AWS_PROFILE is signed in to AWS account $who."
    read -r -p "Is that the account for the '$ENV' environment? [y/N] " ok
    case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
    check_not_someone_elses "$who"
    save_local ACCOUNT_ID "$who"; ACCOUNT_ID="$who"
  elif [ "$who" != "$ACCOUNT_ID" ]; then
    die "Profile $AWS_PROFILE is signed in to account $who, but '$ENV' is account $ACCOUNT_ID ($LOCAL). Stopped."
  fi
  STATE_BUCKET="bmu-tfstate-$ACCOUNT_ID-$AWS_REGION"
}

my_ip() {
  local ip
  ip="$(curl -fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]')" || die "Couldn't find this computer's address (https://checkip.amazonaws.com)."
  echo "$ip" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || die "Unexpected address from checkip.amazonaws.com: $ip"
  echo "$ip"
}

ensure_allowlist() {
  [ -n "$ALLOWED_CIDRS" ] && return
  local ip; ip="$(my_ip)"
  echo "The BMU in AWS is open only to listed addresses. Adding this computer's: $ip/32"
  echo "(More later with ./bmu aws allow-my-ip, or edit ALLOWED_CIDRS in $LOCAL and deploy.)"
  save_local ALLOWED_CIDRS "$ip/32"; ALLOWED_CIDRS="$ip/32"
}

# ---- Terraform ----------------------------------------------------------------------------------------------------
need_terraform() {
  command -v terraform >/dev/null || die "Terraform isn't installed. On a Mac: brew tap hashicorp/tap && brew install hashicorp/tap/terraform"
}

# One state bucket per account and region, shared by the account's BMU environments (one key each). Versioned, so an
# earlier state can be recovered; private; encrypted. Terraform can't create the bucket its own state lives in.
ensure_state_bucket() {
  if ! aws_ s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
    echo "Creating the Terraform state bucket s3://$STATE_BUCKET (once per account)"
    if [ "$AWS_REGION" = us-east-1 ]; then
      aws_ s3api create-bucket --bucket "$STATE_BUCKET" >/dev/null
    else
      aws_ s3api create-bucket --bucket "$STATE_BUCKET" --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
    fi
  fi
  # Set every time (they change nothing when already set), so an interrupted first run is completed by the next.
  aws_ s3api put-public-access-block --bucket "$STATE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws_ s3api put-bucket-versioning --bucket "$STATE_BUCKET" --versioning-configuration Status=Enabled
  aws_ s3api put-bucket-tagging --bucket "$STATE_BUCKET" --tagging 'TagSet=[{Key=project,Value=bmu}]'
}

tf() {  # tf registry|app <terraform arguments>
  local part="$1"; shift
  terraform -chdir="$TF_DIR/$part" "$@"
}

tf_init() {  # tf_init registry|app: point Terraform at this environment's state (the lock is a file beside it)
  tf "$1" init -input=false -reconfigure \
    -backend-config="bucket=$STATE_BUCKET" -backend-config="key=bmu/$BMU_ENV_NAME/$1.tfstate" \
    -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true" >/dev/null ||
    die "terraform init failed for $1. Run it again without '>/dev/null' to see why: ./bmu aws init"
}

cidr_list() {  # "a/32,b/24" -> ["a/32","b/24"]
  printf '["%s"]' "$(printf '%s' "$ALLOWED_CIDRS" | sed 's/ //g; s/,/","/g')"
}

# The app configuration's variables. app_vars IMAGE RUNNING fills the array TF_VARS.
app_vars() {  # app_vars IMAGE RUNNING [SIMULATOR-IMAGE]
  TF_VARS=(
    -var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$BMU_ENV_NAME" -var "image_uri=$1" -var "running=$2"
    -var "allowed_cidrs=$(cidr_list)" -var "cspace_url=$CSPACE_URL" -var "tenant=$TENANT"
    -var "env_label=$ENV_LABEL" -var "always_run_time=$ALWAYS_RUN_TIME" -var "protect_data=${PROTECT_DATA:-false}"
    -var "simulated_cspace=$SIMULATED_CSPACE" -var "fakecspace_image_uri=${3:-}"
  )
}

registry_vars() {
  REGISTRY_VARS=(-var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$BMU_ENV_NAME" -var "simulated_cspace=$SIMULATED_CSPACE")
}

approve() { [ "${BMU_AWS_YES:-}" = 1 ] && echo "-auto-approve" || true; }

deployed_image() {  # the image the services run now; empty if the app was never applied
  tf app output -raw image_uri 2>/dev/null || true
}

need_deployed() {
  IMAGE="$(deployed_image)"
  case "$IMAGE" in ""|*"No outputs"*|*Warning*) die "'$ENV' isn't deployed (./bmu aws deploy)." ;; esac
}

applied() {  # applied OUTPUT: a value the app was last applied with; empty if never applied or not an output then
  local v
  v="$(tf app output -raw "$1" 2>/dev/null || true)"
  case "$v" in *"No outputs"*|*Warning*|*"not found"*) v="" ;; esac
  echo "$v"
}

# One CollectionSpace server and tenant per environment. Its jobs, drafts, CSIDs, saved sign-ins and audit entries
# belong to the server it was deployed for, and a queued job would run on whatever server it points at next: so a
# deployed environment's server never changes. An environment applied before this check recorded nothing yet;
# its next apply records the server.
check_server() {  # after tf_init app
  local url tenant
  url="$(applied cspace_url)"; tenant="$(applied tenant)"
  if { [ -n "$url" ] && [ "$url" != "$CSPACE_URL" ]; } || { [ -n "$tenant" ] && [ "$tenant" != "$TENANT" ]; }; then
    echo "'$ENV' was deployed for $url (tenant ${tenant:-$TENANT}), but its settings now say $CSPACE_URL (tenant $TENANT)." >&2
    echo "Its jobs, drafts and audit entries refer to records on the first, and a queued job would run on the new one." >&2
    die "Stopped; nothing was changed. Put the setting back; or run ./bmu aws destroy first (it deletes the BMU's data);
or deploy the new server as another environment: a different BMU_ENV_NAME in $LOCAL."
  fi
}

# ---- commands -----------------------------------------------------------------------------------------------------
prepare() { load_env; check_account; need_terraform; ensure_state_bucket; }

# For commands that only look: no state bucket means nothing was ever deployed, and nothing is created.
look() {
  load_env; check_account; need_terraform
  aws_ s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1 || { echo "'$ENV' isn't deployed (./bmu aws deploy)."; exit 0; }
  tf_init app
}

app_url() {  # empty while a first deploy hasn't finished
  tf app output -raw url 2>/dev/null || true
}

deploy() {
  load_env; check_account; ensure_allowlist; need_terraform
  command -v docker >/dev/null || die "Docker isn't installed or isn't on the PATH."
  docker info >/dev/null 2>&1 || die "Docker isn't running. Start Docker Desktop and try again."
  ensure_state_bucket
  tf_init app; check_server   # before building anything
  local tag repo registry image sim_image url code
  tag="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  [ -z "$(git status --porcelain 2>/dev/null)" ] || tag="$tag-dirty"
  tag="$tag-$(date -u +%Y%m%d%H%M%S)"

  echo "== 1/3 Image repository"
  registry_vars
  tf_init registry
  tf registry apply -input=false -auto-approve "${REGISTRY_VARS[@]}"
  repo="$(tf registry output -raw repository_url)"
  registry="${repo%%/*}"
  image="$repo:$tag"

  echo "== 2/3 Image $image (linux/arm64)"
  docker build --platform linux/arm64 -f deploy/Dockerfile -t "$image" .
  # The registry's short-lived token goes straight from the AWS CLI to Docker; it is never shown or saved here.
  aws_ ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  docker push "$image"
  sim_image=""
  if [ "$SIMULATED_CSPACE" = true ]; then
    sim_image="$(tf registry output -raw fakecspace_repository_url):$tag"
    echo "== 2/3 Simulated CollectionSpace image $sim_image (linux/arm64)"
    docker build --platform linux/arm64 -f deploy/fakecspace.Dockerfile -t "$sim_image" .
    docker push "$sim_image"
  fi

  echo "== 3/3 The BMU. Terraform shows its plan and asks before changing anything."
  echo "   The first time takes about 15-25 minutes (CloudFront); it finishes when the web app and worker are running."
  echo "   If a task can't start, Terraform waits up to 20 minutes before saying so: ./bmu aws logs web shows why sooner."
  app_vars "$image" true "$sim_image"
  # shellcheck disable=SC2046
  tf app apply -input=false $(approve) "${TF_VARS[@]}"
  [ "$SIMULATED_CSPACE" = false ] || sim_reader_secret

  url="$(app_url)"
  echo "$url" > "$URL_FILE"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url/api/health" || true)"
  echo
  echo "$ENV_LABEL is up: $url   (./bmu open aws)"
  [ "$code" = 200 ] || echo "Note: $url/api/health answered $code. A new CloudFront address can take a few minutes to work everywhere."
  if [ "$SIMULATED_CSPACE" = true ]; then
    echo "It uses the simulated CollectionSpace: sign in with the simulator's accounts (deploy/README.md). Its records"
    echo "are lost whenever it restarts (a pause, a deploy), while the BMU keeps its jobs."
  else
    echo "Careful: jobs run here create real records in $CSPACE_URL, and they stay."
  fi
}

was_running() {  # true unless the environment is paused
  [ "$(tf app output -raw running 2>/dev/null || true)" = false ] && echo false || echo true
}

plan() {
  look; need_deployed; check_server
  app_vars "$IMAGE" "$(was_running)" "$(applied fakecspace_image_uri)"
  tf app plan -input=false "${TF_VARS[@]}"
}

# Apply again with the running image: for a changed setting (pause, resume, the allowlist).
reapply() {  # reapply RUNNING
  prepare; tf_init app; need_deployed; check_server
  app_vars "$IMAGE" "$1" "$(applied fakecspace_image_uri)"
  # shellcheck disable=SC2046
  tf app apply -input=false $(approve) "${TF_VARS[@]}"
}

status() {
  look
  local url
  echo "Environment: $ENV (account $ACCOUNT_ID, $AWS_REGION); Terraform state in s3://$STATE_BUCKET/bmu/$BMU_ENV_NAME/"
  IMAGE="$(deployed_image)"
  case "$IMAGE" in ""|*"No outputs"*|*Warning*) echo "Not deployed (./bmu aws deploy)."; return 0 ;; esac
  url="$(app_url)"
  case "$url" in https://*) echo "Address: $url" ;; *) echo "Address: none yet. The last deploy didn't finish; run ./bmu aws deploy again." ;; esac
  echo "Image:   ${IMAGE##*:}"
  local services="web worker"
  [ "$SIMULATED_CSPACE" = false ] || services="web worker fakecspace"
  # shellcheck disable=SC2086
  { aws_ ecs describe-services --cluster "$NAME" --services $services \
      --query "services[].[serviceName, join('', ['running ', to_string(runningCount), ' of ', to_string(desiredCount)])]" --output text 2>/dev/null || true; } |
  while IFS="$(printf '\t')" read -r name counts; do echo "  $name: $counts"; done
  echo "Allowed addresses: $ALLOWED_CIDRS"
  [ "$SIMULATED_CSPACE" = false ] || echo "CollectionSpace: the simulated one, in the environment ($CSPACE_URL)"
  case "$(reader_secret_field 'length(keys(VersionIdsToStages || `{}`))')" in
    "") echo "Read-only account for interns' checks: no secret yet (the next ./bmu aws deploy creates it)" ;;
    0)  echo "Read-only account for interns' checks: NOT SET (./bmu aws reader-secret)" ;;
    *)  echo "Read-only account for interns' checks: set, last changed $(reader_secret_field LastChangedDate | cut -c1-10) (change it every 90 days)" ;;
  esac
}

# ---- the read-only CollectionSpace account for interns' checks (design: Roles; backend/bmu/reader.py) ----------------
reader_secret_field() {  # reader_secret_field QUERY: one fact about the secret; never reads its value
  aws_ secretsmanager describe-secret --secret-id "$NAME/cspace-reader" --query "$1" --output text 2>/dev/null || true
}

json_string() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }  # printf is a builtin: not in the process list

# With the simulator, deploy sets the secret once to the simulator's read-only account (bmureader), whose password is
# in backend/fakecspace/app.py like all its accounts'. Nothing else ever writes it: the server never changes.
sim_reader_secret() {
  [ "$(reader_secret_field 'length(keys(VersionIdsToStages || `{}`))')" = 0 ] || return 0
  local user=bmureader password
  password="$(sed -n "s/^ *\"$user\": (\"\([^\"]*\)\".*/\1/p" backend/fakecspace/app.py)"
  [ -n "$password" ] || die "Couldn't find the simulator's $user account in backend/fakecspace/app.py; interns' checks won't work."
  printf '{"username":"%s","password":"%s"}' "$user" "$(json_string "$password")" |
    aws_ secretsmanager put-secret-value --secret-id "$NAME/cspace-reader" --secret-string file:///dev/stdin >/dev/null
  echo "The read-only account for interns' checks is the simulator's $user."
}

reader_secret() {
  load_env; check_account
  [ "$SIMULATED_CSPACE" = false ] ||
    die "'$ENV' uses the simulated CollectionSpace: ./bmu aws deploy has set the read-only account to the simulator's own."
  local secret="$NAME/cspace-reader" user="" password="" again=""
  aws_ secretsmanager describe-secret --secret-id "$secret" >/dev/null 2>&1 ||
    die "No secret $secret yet. ./bmu aws deploy creates it; then run this again."
  echo "The read-only CollectionSpace account that checks interns' drafts (role BMU_Reader, nothing else)."
  echo "What you type goes to AWS Secrets Manager ($secret). It isn't shown, saved on this computer or logged."
  printf "Its user name: "; IFS= read -r user
  printf "Its password (not shown): "; IFS= read -rs password; echo
  printf "The password again: "; IFS= read -rs again; echo
  [ -n "$user" ] && [ -n "$password" ] || die "Nothing was changed: the user name and the password are both needed."
  [ "$password" = "$again" ] || die "Nothing was changed: the two passwords differ."
  printf '{"username":"%s","password":"%s"}' "$(json_string "$user")" "$(json_string "$password")" |
    aws_ secretsmanager put-secret-value --secret-id "$secret" --secret-string file:///dev/stdin >/dev/null
  password="" again=""
  echo "Saved. The BMU uses it within 5 minutes; no deploy or restart is needed."
  echo "Check it: sign in to the BMU as an intern and open a draft. Its documents are checked against CollectionSpace."
}

logs() {
  load_env
  local svc="${1:-}"
  case "$svc" in web|worker) ;; fakecspace) [ "$SIMULATED_CSPACE" = true ] || die "'$ENV' doesn't run the simulated CollectionSpace." ;;
    *) die "Usage: ./bmu aws logs web|worker|fakecspace" ;; esac
  aws_ logs tail "/bmu/$BMU_ENV_NAME/$svc" --follow --since 30m
}

destroy() {
  prepare
  echo "This deletes the '$ENV' BMU in AWS account $ACCOUNT_ID: its jobs, staged files, audit entries, logs and images."
  echo "Records it created in CollectionSpace stay. The KMS keys are deleted after a 7-day waiting period."
  read -r -p "Type the environment's name ($ENV) to go ahead: " ok
  [ "$ok" = "$ENV" ] || die "Stopped; nothing was deleted."
  tf_init app
  IMAGE="$(deployed_image)"
  case "$IMAGE" in ""|*"No outputs"*|*Warning*) IMAGE=none ;; esac
  [ -n "$ALLOWED_CIDRS" ] || ALLOWED_CIDRS="127.0.0.1/32"   # the variable must be set, even to destroy
  sim_image="$(applied fakecspace_image_uri)"
  [ -n "$sim_image" ] || sim_image=none   # the variable must be set when SIMULATED_CSPACE is true, even to destroy
  app_vars "$IMAGE" false "$sim_image"
  echo "Destroying the BMU (about 15-20 minutes: CloudFront is disabled first) ..."
  # CloudFront removes its VPC origin's network interfaces in the background, which can briefly hold the VPC.
  tf app destroy -input=false -auto-approve "${TF_VARS[@]}" ||
    die "The destroy didn't finish. Wait a few minutes and run ./bmu aws destroy again; Terraform continues where it stopped."
  tf_init registry
  registry_vars
  tf registry destroy -input=false -auto-approve "${REGISTRY_VARS[@]}"
  rm -f "$URL_FILE"
  echo "Done. '$ENV' is gone from AWS (./bmu aws deploy creates it again)."
  echo "The Terraform state bucket s3://$STATE_BUCKET is kept; it holds the (now empty) state and its history."
}

case "$CMD" in
  deploy) deploy ;;
  plan) plan ;;
  status) status ;;
  url) load_env
       if [ -f "$URL_FILE" ]; then cat "$URL_FILE"; else
         look; u="$(app_url)"
         case "$u" in https://*) echo "$u" ;; *) echo "'$ENV' isn't deployed (./bmu aws deploy)." ;; esac
       fi ;;
  logs) logs "${1:-}" ;;
  pause) reapply false; echo "Paused: no tasks run (./bmu aws resume)." ;;
  resume) reapply true; echo "Running: $(app_url)" ;;
  allow-my-ip)
    load_env
    ip="$(my_ip)/32"
    case ",$ALLOWED_CIDRS," in *",$ip,"*) echo "$ip is already allowed." ; exit 0 ;; esac
    new="${ALLOWED_CIDRS:+$ALLOWED_CIDRS,}$ip"
    save_local ALLOWED_CIDRS "$new"; ALLOWED_CIDRS="$new"
    echo "Allowed: $new"
    prepare; tf_init app
    case "$(deployed_image)" in ""|*"No outputs"*|*Warning*) echo "Saved; it applies at the first deploy." ;; *) reapply "$(was_running)" ;; esac ;;
  init) prepare; tf registry init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="key=bmu/$BMU_ENV_NAME/registry.tfstate" -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true"
        tf app init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="key=bmu/$BMU_ENV_NAME/app.tfstate" -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true" ;;
  reader-secret) reader_secret ;;
  destroy) destroy ;;
  help|-h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "Unknown command '$CMD'. ./bmu aws help lists them." ;;
esac
