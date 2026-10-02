#!/usr/bin/env bash
# ./bmu aws — deploy the BMU to AWS and look after it. Run through ./bmu (./bmu aws help).
#
#   ./bmu aws deploy        build the image, push it and create or update the stacks; prints the address
#   ./bmu aws status        the stacks, the services' tasks and the image they run
#   ./bmu aws url           the address
#   ./bmu aws logs web|worker   follow a service's logs (the last 30 minutes first)
#   ./bmu aws pause         stop both services to save money (the data stays); ./bmu aws resume starts them
#   ./bmu aws allow-my-ip   add this computer's current address to the allowlist
#   ./bmu aws destroy       delete everything in AWS for this environment, data included (asks first)
#
# Which environment: --env NAME or BMU_AWS_ENV (default personal-dev). Its settings are in
# deploy/environments/NAME.conf; NAME.local.conf (not committed) holds the account number and allowed addresses.
# Sign in first with: aws sso login --profile <the environment's AWS_PROFILE>. Nothing here handles a password or key.
# Works with the macOS bash (3.2).
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_DIR=deploy/environments
CFN_DIR=deploy/cloudformation

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
  ACCOUNT_ID="" ALLOWED_CIDRS=""
  # shellcheck disable=SC1090
  . "$CONF"
  # shellcheck disable=SC1090
  [ -f "$LOCAL" ] && . "$LOCAL"
  : "${AWS_PROFILE:?set AWS_PROFILE in $CONF}" "${AWS_REGION:?set AWS_REGION in $CONF}" "${BMU_ENV_NAME:?set BMU_ENV_NAME in $CONF}"
  STACK="bmu-$BMU_ENV_NAME"
  ECR_STACK="bmu-$BMU_ENV_NAME-ecr"
  export AWS_PAGER=""
}

aws_() { aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

save_local() {  # save_local KEY VALUE: set one setting in the environment's .local.conf
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  { [ -f "$LOCAL" ] && grep -v "^$key=" "$LOCAL" || echo "# ./bmu aws settings for '$ENV' on this computer only (not committed)."; } > "$tmp"
  echo "$key=\"$value\"" >> "$tmp"
  mv "$tmp" "$LOCAL"
}

# Signed in, and to the account this environment was first deployed to.
check_account() {
  local who
  who="$(aws_ sts get-caller-identity --query Account --output text 2>/dev/null)" ||
    die "Not signed in to AWS for '$ENV'. Run: aws sso login --profile $AWS_PROFILE"
  if [ -z "$ACCOUNT_ID" ]; then
    echo "Profile $AWS_PROFILE is signed in to AWS account $who."
    read -r -p "Is that the account for the '$ENV' environment? [y/N] " ok
    case "$ok" in y|Y|yes) save_local ACCOUNT_ID "$who"; ACCOUNT_ID="$who" ;; *) die "Stopped; nothing was changed." ;; esac
  elif [ "$who" != "$ACCOUNT_ID" ]; then
    die "Profile $AWS_PROFILE is signed in to account $who, but '$ENV' is account $ACCOUNT_ID ($LOCAL). Stopped."
  fi
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

stack_status() { aws_ cloudformation describe-stacks --stack-name "$1" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo NONE; }
output() { aws_ cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

# Change some of the stack's parameters, keeping the template and every other value as deployed.
update_params() {  # update_params Key=Value ...
  local keys params=() k found kv json out
  [ "$(stack_status "$STACK")" != NONE ] || die "'$ENV' isn't deployed (./bmu aws deploy)."
  keys="$(aws_ cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Parameters[].ParameterKey' --output text)"
  for k in $keys; do
    found=""
    for kv in "$@"; do [ "${kv%%=*}" = "$k" ] && found="${kv#*=}"; done
    # JSON, since values can hold commas (AllowedCidrs) that the CLI's shorthand syntax would split
    if [ -n "$found" ]; then
      found="$(printf '%s' "$found" | sed 's/\\/\\\\/g; s/"/\\"/g')"
      params+=("{\"ParameterKey\":\"$k\",\"ParameterValue\":\"$found\"}")
    else
      params+=("{\"ParameterKey\":\"$k\",\"UsePreviousValue\":true}")
    fi
  done
  json="[$(IFS=,; echo "${params[*]}")]"
  if ! out="$(aws_ cloudformation update-stack --stack-name "$STACK" --use-previous-template \
                --capabilities CAPABILITY_NAMED_IAM --parameters "$json" 2>&1)"; then
    case "$out" in *"No updates are to be performed"*) echo "Nothing to change."; return 0 ;; *) die "$out" ;; esac
  fi
  echo "Updating stack $STACK ..."
  aws_ cloudformation wait stack-update-complete --stack-name "$STACK" || die "The update didn't finish; see the stack's Events in the CloudFormation console."
}

# A stack whose first creation failed can't be updated, only deleted; nothing of it is left but the record. Other
# failed states need a person: say so instead of passing on CloudFormation's error.
clear_failed_create() {
  local st; st="$(stack_status "$1")"
  case "$st" in
    ROLLBACK_COMPLETE|ROLLBACK_FAILED)
      echo "The last attempt to create $1 failed ($st); removing what's left of it first."
      aws_ cloudformation delete-stack --stack-name "$1"
      aws_ cloudformation wait stack-delete-complete --stack-name "$1" || die "Couldn't remove $1; see its Events in the CloudFormation console." ;;
    *_IN_PROGRESS)
      die "Stack $1 is busy ($st). Wait for it to finish (CloudFormation console, or ./bmu aws status), then try again." ;;
    UPDATE_ROLLBACK_FAILED|DELETE_FAILED)
      die "Stack $1 is stuck ($st). See its Events in the CloudFormation console: an update rollback can be continued there (Stack actions, Continue update rollback); a failed deletion is finished with ./bmu aws destroy." ;;
  esac
}

wait_services() {
  echo "Waiting for the web app and the worker to be running ..."
  aws_ ecs wait services-stable --cluster "$STACK" --services web worker ||
    die "The services didn't settle. See ./bmu aws status and ./bmu aws logs web|worker."
}

# ---- commands -----------------------------------------------------------------------------------------------------
deploy() {
  load_env; check_account; ensure_allowlist
  command -v docker >/dev/null || die "Docker isn't installed or isn't on the PATH."
  docker info >/dev/null 2>&1 || die "Docker isn't running. Start Docker Desktop and try again."
  local tag repo registry image url
  tag="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  [ -z "$(git status --porcelain 2>/dev/null)" ] || tag="$tag-dirty"
  tag="$tag-$(date -u +%Y%m%d%H%M%S)"

  echo "== 1/4 Image repository (stack $ECR_STACK)"
  clear_failed_create "$ECR_STACK"
  aws_ cloudformation deploy --stack-name "$ECR_STACK" --template-file "$CFN_DIR/ecr.yaml" \
    --parameter-overrides "EnvName=$BMU_ENV_NAME" --tags project=bmu "environment=$BMU_ENV_NAME" --no-fail-on-empty-changeset
  repo="$(aws_ cloudformation describe-stacks --stack-name "$ECR_STACK" --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text)"
  registry="${repo%%/*}"
  image="$repo:$tag"

  echo "== 2/4 Image $image (linux/arm64)"
  docker build --platform linux/arm64 -f deploy/Dockerfile -t "$image" .
  # The registry's short-lived token goes straight from the AWS CLI to Docker; it is never shown or saved here.
  aws_ ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  docker push "$image"

  echo "== 3/4 The BMU (stack $STACK). The first time takes about 15-25 minutes (CloudFront)."
  clear_failed_create "$STACK"
  aws_ cloudformation deploy --stack-name "$STACK" --template-file "$CFN_DIR/bmu.yaml" \
    --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset \
    --tags project=bmu "environment=$BMU_ENV_NAME" \
    --parameter-overrides "EnvName=$BMU_ENV_NAME" "ImageUri=$image" "AllowedCidrs=$ALLOWED_CIDRS" \
      "CSpaceUrl=$CSPACE_URL" "Tenant=$TENANT" "EnvLabel=$ENV_LABEL" "AlwaysRunTime=$ALWAYS_RUN_TIME" "Running=true"

  echo "== 4/4 Starting"
  wait_services
  url="$(output Url)"
  echo "$url" > "$URL_FILE"
  local code; code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url/api/health" || true)"
  echo
  echo "$ENV_LABEL is up: $url   (./bmu open aws)"
  [ "$code" = 200 ] || echo "Note: $url/api/health answered $code. A new CloudFront address can take a few minutes to work everywhere."
  echo "Careful: jobs run here create real records in $CSPACE_URL, and they stay."
}

status() {
  load_env; check_account
  echo "Environment: $ENV (account $ACCOUNT_ID, $AWS_REGION)"
  echo "Stacks: $ECR_STACK $(stack_status "$ECR_STACK"), $STACK $(stack_status "$STACK")"
  [ "$(stack_status "$STACK")" != NONE ] || return 0
  echo "Address: $(output Url)"
  aws_ ecs describe-services --cluster "$STACK" --services web worker \
    --query "services[].[serviceName, join('', ['running ', to_string(runningCount), ' of ', to_string(desiredCount)]), taskDefinition]" --output text |
  while IFS="$(printf '\t')" read -r name counts td; do
    echo "  $name: $counts  image $(aws_ ecs describe-task-definition --task-definition "$td" --query 'taskDefinition.containerDefinitions[0].image' --output text | sed 's#.*:##')"
  done
  echo "Allowed addresses: $ALLOWED_CIDRS"
}

logs() {
  load_env
  local svc="${1:-}"
  case "$svc" in web|worker) ;; *) die "Usage: ./bmu aws logs web|worker" ;; esac
  aws_ logs tail "/bmu/$BMU_ENV_NAME/$svc" --follow --since 30m
}

empty_bucket() {  # every object version and delete marker; the stack can't delete a bucket that has any
  local bucket="$1" batch
  aws_ s3api head-bucket --bucket "$bucket" >/dev/null 2>&1 || return 0
  echo "Emptying s3://$bucket ..."
  while :; do
    batch="$(aws_ s3api list-object-versions --bucket "$bucket" --max-items 1000 --output json \
      --query '{Objects: ([Versions, DeleteMarkers][][].{Key: Key, VersionId: VersionId})[:1000], Quiet: `true`}')"
    case "$batch" in *'"Key"'*) ;; *) break ;; esac
    aws_ s3api delete-objects --bucket "$bucket" --delete "$batch" >/dev/null
  done
}

destroy() {
  load_env; check_account
  echo "This deletes the '$ENV' BMU in AWS account $ACCOUNT_ID: its jobs, staged files, audit entries, logs and images."
  echo "Records it created in CollectionSpace stay. The KMS keys are deleted after a 7-day waiting period."
  read -r -p "Type the environment's name ($ENV) to go ahead: " ok
  [ "$ok" = "$ENV" ] || die "Stopped; nothing was deleted."
  if [ "$(stack_status "$STACK")" != NONE ]; then
    local staging logs try
    staging="$(output StagingBucket)"; logs="$(output LogsBucket)"
    echo "Deleting stack $STACK (about 15-20 minutes: CloudFront is disabled first) ..."
    for try in 1 2 3; do
      # S3 delivers access logs late, so the logs bucket can fill again while the stack is being deleted: empty
      # both and try again if the deletion stopped on a bucket that wasn't empty.
      empty_bucket "$staging"; empty_bucket "$logs"
      aws_ cloudformation delete-stack --stack-name "$STACK"
      if aws_ cloudformation wait stack-delete-complete --stack-name "$STACK"; then break; fi
      [ "$try" = 3 ] && die "The deletion didn't finish; see the stack's Events in the CloudFormation console, then run ./bmu aws destroy again."
      # CloudFront removes its VPC origin's network interfaces in the background, which can briefly hold the VPC.
      echo "Not finished yet (try $try of 3); waiting a few minutes, then emptying the buckets and trying again ..."
      sleep 240
    done
  fi
  if [ "$(stack_status "$ECR_STACK")" != NONE ]; then
    echo "Deleting stack $ECR_STACK ..."
    aws_ cloudformation delete-stack --stack-name "$ECR_STACK"
    aws_ cloudformation wait stack-delete-complete --stack-name "$ECR_STACK"
  fi
  rm -f "$URL_FILE"
  echo "Done. '$ENV' is gone from AWS (./bmu aws deploy creates it again)."
}

case "$CMD" in
  deploy) deploy ;;
  status) status ;;
  url) load_env; if [ -f "$URL_FILE" ]; then cat "$URL_FILE"; else check_account; output Url; fi ;;
  logs) logs "${1:-}" ;;
  pause) load_env; check_account; update_params Running=false; echo "Paused: no tasks run (./bmu aws resume)." ;;
  resume) load_env; check_account; update_params Running=true; wait_services; echo "Running: $(output Url)" ;;
  allow-my-ip)
    load_env; check_account
    ip="$(my_ip)/32"
    case ",$ALLOWED_CIDRS," in *",$ip,"*) echo "$ip is already allowed." ; exit 0 ;; esac
    new="${ALLOWED_CIDRS:+$ALLOWED_CIDRS,}$ip"
    save_local ALLOWED_CIDRS "$new"
    if [ "$(stack_status "$STACK")" != NONE ]; then update_params "AllowedCidrs=$new"; fi
    echo "Allowed: $new" ;;
  destroy) destroy ;;
  help|-h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "Unknown command '$CMD'. ./bmu aws help lists them." ;;
esac
