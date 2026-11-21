#!/usr/bin/env bash
# ./bmu aws — deploy the BMU to AWS and look after it. Run through ./bmu (./bmu aws help).
#
#   ./bmu aws deploy        build the image, push it, then show Terraform's plan and apply it; prints the address
#                           (with FRONT_DOOR=alb, first the certificate's DNS record while it isn't issued, and at the
#                           end the load balancer that DOMAIN_NAME's DNS record must point at)
#   ./bmu aws plan          show what a deploy of the running image would change, without changing anything
#   ./bmu aws status        the services' tasks, the image they run, the allowed addresses and the museums
#   ./bmu aws url           the address
#   ./bmu aws logs web|worker|fakecspace   follow a service's logs (the last 30 minutes first)
#   ./bmu aws pause         stop both services to save money (the data stays); ./bmu aws resume starts them
#   ./bmu aws allow-my-ip   add this computer's current address to the allowlist
#   ./bmu aws reader-secret [MUSEUM]  set or change a museum's read-only CollectionSpace account's sign-in (asks;
#                           nothing is shown or saved here)
#   ./bmu aws destroy       delete everything in AWS for this environment, data included (asks first)
#   ./bmu aws init          point Terraform at this environment's state, to run terraform commands yourself
#   ./bmu aws ci-role       once per account: the role CI assumes to sign in to ECR Public (deploy/terraform/ci);
#                           prints the gh command that sets the repository's ECR_PUBLIC_ROLE_ARN variable
#   ./bmu aws rehearsal-vpc [destroy]   a rehearsal environment only (REHEARSAL=true), in your own account: make (or
#                           delete) what Operations provides in UC Berkeley's account, a VPC with public subnets and a
#                           NAT gateway and a deployer role with only deploy/iam/bmu-deployer-policy.json (and the
#                           simulator's bmu-simulator-dns-policy.json), as ADMIN_PROFILE
#   ./bmu aws settings push|set|pull|show|migrate|delete   an environment with SETTINGS=ssm (BP4), where one SSM
#                           parameter, the settings document /bmu-<name>/settings/all, holds the settings (Operations
#                           may edit it in the AWS console) and the files are only this computer's copy: push adds
#                           the settings SSM doesn't have yet from the files; set KEY [VALUE] changes one setting (or
#                           removes it) in SSM and in the files here; pull brings the files here up to date with SSM;
#                           show lists them, marking any the files here disagree with; migrate moves an environment
#                           from one parameter per setting into the document. push, set and migrate run as
#                           SETTINGS_PROFILE if it has one, else ADMIN_PROFILE; pull and show as the deployer, which
#                           only reads; delete removes them once the environment is destroyed, as ADMIN_PROFILE
#   ./bmu aws pipeline [destroy]   as the account's administrator (ADMIN_PROFILE), for an environment with
#                           SETTINGS=ssm: make (or delete) its deploy pipeline (deploy/terraform/pipeline): the roles the
#                           deploy workflow assumes, the CodeBuild projects and their role, and GitHub's OIDC provider
#                           where the account has none
#   ./bmu aws sim-secrets   with the simulated CollectionSpace, in a pipeline environment: set the simulator's
#                           read-only account, which a deploy from here sets itself (nothing is shown)
#   ./bmu aws pipeline-plan | pipeline-apply   only in the pipeline's builds (deploy/pipeline/): no questions, the
#                           build's own role, the settings from SSM
#
# Once an environment has a deploy pipeline (docs/design.md, Deploys), the pipeline deploys it: ./bmu aws deploy from a
# laptop is a break-glass deploy (it asks you to type "break glass"), pause and resume set RUNNING in SSM for the next
# pipeline run, as SETTINGS_PROFILE or the administrator, and allow-my-ip refuses (the allowed ranges change with settings set). A deploy
# of an environment with a real CollectionSpace (UC Berkeley's data) asks the person deploying to type the account's
# number, and the pipeline's builds need the account an administrator confirmed (REAL_DATA_ACCOUNT): UC Berkeley data
# only in UC Berkeley accounts.
#
# Which environment: --env NAME or BMU_AWS_ENV (default personal-dev). Its settings are in
# deploy/environments/NAME.conf; NAME.local.conf (not committed) holds the account number and allowed addresses.
# With SETTINGS=ssm (design: Deploys, BP4), every setting but AWS_PROFILE, AWS_REGION, BMU_ENV_NAME, ADMIN_PROFILE,
# SETTINGS_PROFILE, SETTINGS and REQUIRE_CLEAN is read from SSM Parameter Store in the account instead
# (the settings document, /bmu-<name>/settings/all). SSM is then the settings' one copy: anyone with access may change one there,
# including Operations in the AWS console, so nobody has to tell anyone. ./bmu aws settings push puts a new
# environment's settings there from its files (only adding); after that, settings set changes one, and settings pull brings
# the files here up to date. The deployer only reads them: set is the account's administrator's, or, where the
# environment has one, SETTINGS_PROFILE's, a role that can write only its settings (in UC Berkeley's account, where the
# person deploying isn't the account's administrator; deploy/iam/README.md).
# CSPACE_TENANTS lists the museums the environment serves, each with its CollectionSpace server
# ("pahma=https://... bampfa=https://..."); TENANT and CSPACE_URL instead mean a list of one.
# Sign in first with aws sso login: for a profile that takes a role from another (source_profile, as in UC Berkeley's
# account), through that profile's SSO session (sign_in_hint names it). Nothing here handles a password or key,
# except reader-secret, which passes what you type straight to AWS Secrets Manager.
# Terraform (deploy/terraform) creates everything; its state is in an S3 bucket in the same account, which the first
# deploy creates. BMU_AWS_YES=1 skips Terraform's "yes" prompt. Works with the macOS bash (3.2).
# SIMULATED_CSPACE=true (in the settings) runs the simulated CollectionSpace in the environment instead of using a real
# one, for PAHMA alone. A deployed museum's CollectionSpace server never changes; a museum can be added, and removed
# once it has no unfinished jobs (check_museums). The first use of an environment on a computer asks first if the
# account already has one by that name (check_not_someone_elses).
# FRONT_DOOR (deploy/terraform/app/variables.tf, front_door): cloudfront (the default; a personal account) or alb (UC
# Berkeley's account: an internet-facing load balancer on DOMAIN_NAME with an ACM certificate, which Operations
# validates with a DNS record that deploy prints, and a regional WAF). A deployed environment's front door never
# changes (check_front_door). REQUIRE_CLEAN=true deploys only from a clean checkout whose HEAD is on origin/main
# (check_clean).
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
SUBCMD="${1:-}"   # settings push|set|pull|show|migrate|delete, pipeline [destroy], …

# ---- settings -----------------------------------------------------------------------------------------------------
load_env() {
  CONF="$ENV_DIR/$ENV.conf"
  LOCAL="$ENV_DIR/$ENV.local.conf"
  URL_FILE="$ENV_DIR/$ENV.url"
  [ -f "$CONF" ] || die "No settings for environment '$ENV' ($CONF). Environments: $(ls "$ENV_DIR" | sed -n 's/\.conf$//p' | grep -v '\.local$' | tr '\n' ' ')"
  ACCOUNT_ID="" ALLOWED_CIDRS="" SIMULATED_CSPACE="" ENV_LABEL="" CSPACE_TENANTS="" TENANT="" CSPACE_URL=""
  WAF_ENABLED="" ORIGIN_DOMAIN="" ORIGIN_CERTIFICATE_ARN="" FRONT_DOOR="" DOMAIN_NAME="" PROTECT_DATA="" ALWAYS_RUN_TIME=""
  REQUIRE_CLEAN="" WAF_MANAGED_RULES="" SETTINGS="" ALLOW_SELF_REVIEW="" REAL_DATA_ACCOUNT="" RUNNING=""
  VPC_ID="" APP_SUBNET_IDS="" LB_SUBNET_IDS="" CREATE_GATEWAY_ENDPOINTS="" REHEARSAL="" ADMIN_PROFILE="" SETTINGS_PROFILE=""
  # shellcheck disable=SC1090
  . "$CONF"
  local conf_label="$ENV_LABEL"
  # shellcheck disable=SC1090
  [ -f "$LOCAL" ] && . "$LOCAL"
  CERTIFICATE_ARN=""   # not a setting: load_certificate reads it from ../registry's state
  # BP8: only the committed settings file may allow self-review, so allowing it is a reviewed change.
  if [ -f "$LOCAL" ] && grep -Eq '^[[:space:]]*(ALLOW_SELF_REVIEW|REAL_DATA_ACCOUNT|RUNNING)=' "$LOCAL" ||
     grep -Eq '^[[:space:]]*(REAL_DATA_ACCOUNT|RUNNING)=' "$CONF"; then
    die "ALLOW_SELF_REVIEW goes only in $CONF, the committed file (BP8); REAL_DATA_ACCOUNT and RUNNING only in SSM, where ./bmu aws pipeline, pause and resume put them. Remove them from $LOCAL or $CONF."
  fi
  case "${ALLOW_SELF_REVIEW:=false}" in true|false) ;; *) die "ALLOW_SELF_REVIEW must be true or false ($CONF)." ;; esac
  : "${AWS_PROFILE:?set AWS_PROFILE in $CONF}" "${AWS_REGION:?set AWS_REGION in $CONF}" "${BMU_ENV_NAME:?set BMU_ENV_NAME in $CONF}"
  NAME="bmu-$BMU_ENV_NAME"   # the cluster's name and the prefix of every resource
  # A rehearsal's VPC and deployer, the settings in SSM and the pipeline are the account administrator's to make: the
  # deployer can't make itself, and only reads the settings. Where SETTINGS_PROFILE is set, it writes the settings
  # instead (settings push and set; pause and resume in pipeline_pause), and the administrator deletes them.
  DEPLOYER_PROFILE="$AWS_PROFILE"
  case "$CMD" in rehearsal-vpc|pipeline) [ -z "$ADMIN_PROFILE" ] || AWS_PROFILE="$ADMIN_PROFILE" ;; esac
  case "$CMD:$SUBCMD" in settings:pull|settings:show) ;;   # they only read: the deployer may
    settings:*) [ -z "$(settings_writer)" ] || AWS_PROFILE="$(settings_writer)" ;; esac
  # The pipeline's builds sign in as the build's own role, and always read the settings from SSM.
  IN_BUILD=false
  case "$CMD" in pipeline-plan|pipeline-apply)
    [ -n "${CODEBUILD_BUILD_ID:-}" ] || die "./bmu aws $CMD runs only in the pipeline's builds (deploy/pipeline/)."
    IN_BUILD=true SETTINGS=ssm; unset AWS_PROFILE ;;
  esac
  case "${SETTINGS:=files}" in files|ssm) ;; *) die "SETTINGS must be files or ssm ($CONF, $LOCAL)." ;; esac
  [ "$SETTINGS" = files ] || [ "$CMD" = settings ] || from_ssm   # settings compares the files with SSM itself
  case "${REHEARSAL:=false}" in true|false) ;; *) die "REHEARSAL must be true or false ($CONF)." ;; esac
  case "${ALWAYS_RUN_TIME:=false}" in true|false) ;; *) die "ALWAYS_RUN_TIME must be true or false ($CONF, $LOCAL)." ;; esac
  case "${SIMULATED_CSPACE:=false}" in true|false) ;; *) die "SIMULATED_CSPACE must be true or false ($CONF, $LOCAL)." ;; esac
  if [ "$SIMULATED_CSPACE" = true ]; then
    [ "${PROTECT_DATA:-false}" != true ] ||
      die "SIMULATED_CSPACE=true can't be used with PROTECT_DATA=true: the simulator's data is lost on every restart, and its accounts' passwords are public."
    MUSEUMS="pahma=$(sim_url)"   # the simulator is PAHMA's; CSPACE_TENANTS, TENANT and CSPACE_URL are ignored
    [ "$ENV_LABEL" != "$conf_label" ] || ENV_LABEL="AWS · $ENV · simulated CollectionSpace"   # unless .local.conf sets one
  else
    read_museums
  fi
  case "${FRONT_DOOR:=cloudfront}" in cloudfront|alb) ;; *) die "FRONT_DOOR must be cloudfront or alb ($CONF)." ;; esac
  case "${REQUIRE_CLEAN:=false}" in true|false) ;; *) die "REQUIRE_CLEAN must be true or false ($CONF)." ;; esac
  case "${WAF_MANAGED_RULES:=count}" in count|block) ;; *) die "WAF_MANAGED_RULES must be count or block ($CONF, $LOCAL)." ;; esac
  # The WAF (deploy/terraform/app/waf.tf), on the load balancer with FRONT_DOOR=alb only, comes with protected data
  # unless the settings say otherwise.
  if [ "$FRONT_DOOR" = alb ]; then : "${WAF_ENABLED:=${PROTECT_DATA:-false}}"; else : "${WAF_ENABLED:=false}"; fi
  case "$WAF_ENABLED" in true|false) ;; *) die "WAF_ENABLED must be true or false ($CONF, $LOCAL)." ;; esac
  [ "$WAF_ENABLED" = false ] || [ "$FRONT_DOOR" = alb ] ||
    die "WAF_ENABLED=true needs FRONT_DOOR=alb ($CONF, $LOCAL): the WAF is on the load balancer, and a CloudFront environment has none."
  # HTTPS from CloudFront to the load balancer: both settings, or neither (variables.tf, origin_domain).
  [ -z "$ORIGIN_DOMAIN" ] && [ -z "$ORIGIN_CERTIFICATE_ARN" ] || { [ -n "$ORIGIN_DOMAIN" ] && [ -n "$ORIGIN_CERTIFICATE_ARN" ]; } ||
    die "Set ORIGIN_DOMAIN and ORIGIN_CERTIFICATE_ARN together, or neither ($CONF, $LOCAL)."
  [ -z "$ORIGIN_DOMAIN" ] || [ "$FRONT_DOOR" = cloudfront ] ||
    die "ORIGIN_DOMAIN and ORIGIN_CERTIFICATE_ARN are for FRONT_DOOR=cloudfront; with alb, the load balancer's name is DOMAIN_NAME ($CONF, $LOCAL)."
  [ -z "$DOMAIN_NAME" ] || [ "$FRONT_DOOR" = alb ] || die "DOMAIN_NAME is for FRONT_DOOR=alb ($LOCAL)."
  # An existing VPC (deploy/terraform/app/network.tf): its IDs identify the account's network, and the domain is
  # Operations', so only in .local.conf.
  ! grep -Eq '^[[:space:]]*(VPC_ID|APP_SUBNET_IDS|LB_SUBNET_IDS|DOMAIN_NAME)=' "$CONF" ||
    die "Put VPC_ID, APP_SUBNET_IDS, LB_SUBNET_IDS and DOMAIN_NAME in $LOCAL, which isn't committed, not in $CONF."
  case "${CREATE_GATEWAY_ENDPOINTS:=false}" in true|false) ;; *) die "CREATE_GATEWAY_ENDPOINTS must be true or false ($LOCAL)." ;; esac
  if [ "$CMD" = rehearsal-vpc ] || [ "$CMD" = settings ]; then
    :   # rehearsal-vpc makes the VPC and saves its IDs; settings delete runs once it is gone
  elif [ "$REHEARSAL" = true ] && [ -z "$VPC_ID" ]; then
    die "'$ENV' is a rehearsal: first ./bmu aws rehearsal-vpc --env $ENV (it makes the VPC and the deployer, as $ADMIN_PROFILE)."
  elif [ -n "$VPC_ID" ]; then
    [ -n "$APP_SUBNET_IDS" ] || die "VPC_ID needs APP_SUBNET_IDS: the VPC's private subnets for the tasks, in two zones ($LOCAL)."
  else
    [ -z "$APP_SUBNET_IDS$LB_SUBNET_IDS" ] && [ "$CREATE_GATEWAY_ENDPOINTS" = false ] ||
      die "APP_SUBNET_IDS, LB_SUBNET_IDS and CREATE_GATEWAY_ENDPOINTS need VPC_ID ($LOCAL)."
  fi
  if [ "$FRONT_DOOR" = alb ] && [ "$CMD" != rehearsal-vpc ] && [ "$CMD" != settings ]; then
    [ -n "$VPC_ID" ] && [ -n "$LB_SUBNET_IDS" ] ||
      die "FRONT_DOOR=alb needs VPC_ID and LB_SUBNET_IDS: the VPC's public subnets, in two zones, for the internet-facing load balancer ($LOCAL)."
    [ -n "$DOMAIN_NAME" ] ||
      die "FRONT_DOOR=alb needs DOMAIN_NAME in $LOCAL: the BMU's name (from Operations in UC Berkeley's account; in a rehearsal, a name in a DNS zone you control)."
  fi
  case "${RUNNING:=true}" in true|false) ;; *) die "RUNNING must be true or false (SSM, $(settings_path)/RUNNING)." ;; esac
  export AWS_PAGER="" AWS_REGION
  # Terraform signs in with the same profile. In a build, the build's role is in the environment, and is kept.
  if [ "$IN_BUILD" = false ]; then
    export AWS_PROFILE
    # Keys in the shell would win over the profile in Terraform (though not in "aws --profile"): never use them here.
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  fi
  export TF_IN_AUTOMATION=1
}

# The AWS CLI with the environment's profile; in the pipeline's builds, the build's role.
aws_() {
  if [ -n "${AWS_PROFILE:-}" ]; then aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"
  else aws --region "$AWS_REGION" "$@"
  fi
}

# ---- the museums ----------------------------------------------------------------------------------------------------
# MUSEUMS is "museum=server museum=server", each server without a trailing /: from CSPACE_TENANTS, or else TENANT and
# CSPACE_URL. Each museum needs its configuration, backend/bmu/tenants/<museum>.yaml.
read_museums() {
  local list="$CSPACE_TENANTS" entry museum url seen=" "
  if [ -n "$list" ]; then
    [ -z "$TENANT$CSPACE_URL" ] ||
      die "Set CSPACE_TENANTS, or TENANT and CSPACE_URL, not both ($CONF, $LOCAL): CSPACE_TENANTS lists every museum."
  else
    [ -n "$TENANT" ] && [ -n "$CSPACE_URL" ] ||
      die "No museums: set CSPACE_TENANTS=\"pahma=https://... bampfa=https://...\" in $CONF or $LOCAL."
    list="$TENANT=$CSPACE_URL"
  fi
  MUSEUMS=""
  for entry in $list; do
    museum="${entry%%=*}" url="${entry#*=}"
    url="${url%/}"   # one spelling of the server, for check_museums
    [ "$museum" != "$entry" ] && echo "$museum" | grep -Eq '^[a-z][a-z0-9]{1,19}$' ||
      die "CSPACE_TENANTS: '$entry' isn't museum=server; a museum is 2 to 20 lowercase letters or digits, such as pahma."
    echo "$url" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]+)?$' ||
      die "CSPACE_TENANTS: $museum's server '$url' must be an address alone, such as https://pahma.qa.collectionspace.org."
    case "$url" in https://*) ;; *)   # the BMU sends each user's password to it: never in the clear
      die "CSPACE_TENANTS: $museum's server '$url' must be https://, such as https://pahma.qa.collectionspace.org." ;; esac
    [ -f "backend/bmu/tenants/$museum.yaml" ] ||
      die "The BMU has no configuration for the museum '$museum' (backend/bmu/tenants/$museum.yaml)."
    case "$seen" in *" $museum "*) die "CSPACE_TENANTS lists $museum twice." ;; esac
    seen="$seen$museum "
    MUSEUMS="${MUSEUMS:+$MUSEUMS }$museum=$url"
  done
  [ -n "$MUSEUMS" ] || die "No museums: CSPACE_TENANTS is empty ($CONF, $LOCAL)."
}

museum_names() {  # museum_names [LIST]: the museums of a list (default MUSEUMS), one per line
  local entry
  for entry in ${1-$MUSEUMS}; do echo "${entry%%=*}"; done
}

server_of() {  # server_of MUSEUM [LIST]: the museum's server in a list (default MUSEUMS); fails if it isn't listed
  local entry
  for entry in ${2-$MUSEUMS}; do [ "${entry%%=*}" != "$1" ] || { echo "${entry#*=}"; return 0; }; done
  return 1
}

tenants_var() {  # MUSEUMS as a Terraform map: {"pahma"="https://...","bampfa"="https://..."}
  local entry out=""
  for entry in $MUSEUMS; do out="${out:+$out,}\"${entry%%=*}\"=\"${entry#*=}\""; done
  printf '{%s}' "$out"
}

# The simulated CollectionSpace's address in the VPC (Cloud Map). The same as local.fakecspace_url in
# deploy/terraform/app/fakecspace.tf; Terraform refuses any other with simulated_cspace (variables.tf).
sim_url() { echo "http://fakecspace.$NAME.internal:8180"; }

# With SETTINGS=ssm, a setting saved (or removed) by a command goes to SSM, which the commands read, and to the
# .local.conf as well, so that the files here stay a whole copy. Only the
# administrator's commands save one there (rehearsal-vpc): the deployer can't write SSM, so a deployer's command that
# would save a setting stops first (ensure_allowlist, allow-my-ip) and ACCOUNT_ID always comes from SSM (from_ssm).
save_local() {  # save_local KEY VALUE: set one setting in the environment's .local.conf (and SSM, SETTINGS=ssm)
  local key="$1" value="$2" tmp
  # The .local.conf is sourced: a value with " $ ` \ or a line break in it could run as a command there.
  case "$value" in *[\"\$\`\\]*|*$'\n'*) die "$key's value can't have \" \$ \` \\ or a line break in it: not saved in $LOCAL." ;; esac
  if [ "$SETTINGS" = ssm ] && [ "$CMD" != settings ] && is_ssm_setting "$key"; then put_setting "$key" "$value"; fi
  tmp="$(mktemp)"
  { [ -f "$LOCAL" ] && grep -v "^$key=" "$LOCAL" || echo "# ./bmu aws settings for '$ENV' on this computer only (not committed)."; } > "$tmp"
  echo "$key=\"$value\"" >> "$tmp"
  mv "$tmp" "$LOCAL"
}

# ---- settings in SSM Parameter Store (SETTINGS=ssm; design: Deploys, BP4) -------------------------------------------
# One String parameter, the settings document /bmu-<name>/settings/all, in the environment's account, so that the
# deploy pipeline's build and a person's ./bmu aws read the same values: one NAME="value" line per setting, with
# comments, which Operations can edit in the AWS console (decided 21 November 2026). RUNNING and REAL_DATA_ACCOUNT stay
# parameters of their own beside it (/bmu-<name>/settings/RUNNING), so that editing the document can't change them.
# The values are private (addresses, Operations' VPC and subnets, the BMU's name) but not secret. The document is data,
# never run: settings_doc_lines reads it line by line. ./bmu aws settings push adds a new environment's settings from
# the files, and settings set changes one, as the account's administrator or SETTINGS_PROFILE; the deployer policy only
# reads them (ssm:DescribeParameters, and ssm:GetParameters on parameter/bmu-*/settings/*). An environment whose
# settings are still one parameter each (before the document) is read as before; settings migrate moves it.
SSM_SETTINGS="ACCOUNT_ID ALLOWED_CIDRS SIMULATED_CSPACE ENV_LABEL CSPACE_TENANTS TENANT CSPACE_URL WAF_ENABLED
  ORIGIN_DOMAIN ORIGIN_CERTIFICATE_ARN FRONT_DOOR DOMAIN_NAME PROTECT_DATA ALWAYS_RUN_TIME WAF_MANAGED_RULES VPC_ID
  APP_SUBNET_IDS LB_SUBNET_IDS CREATE_GATEWAY_ENDPOINTS REHEARSAL"
# Always from the files: what says how to reach the account, SETTINGS itself, and REQUIRE_CLEAN, a rule about the
# checkout a deploy is run from, which belongs with the committed code.
FILE_SETTINGS="AWS_PROFILE AWS_REGION BMU_ENV_NAME ADMIN_PROFILE SETTINGS_PROFILE SETTINGS REQUIRE_CLEAN ALLOW_SELF_REVIEW"
# In SSM only, never pushed from the files (settings push leaves them alone) and never written by the build: the account
# an administrator confirmed for UC Berkeley data (./bmu aws pipeline, BP7), and whether the services run (./bmu aws
# pause and resume in a pipeline environment, BP5).
PIPELINE_SETTINGS="REAL_DATA_ACCOUNT RUNNING"

is_ssm_setting() { case " $(echo $SSM_SETTINGS) " in *" $1 "*) true ;; *) false ;; esac; }
is_pipeline_setting() { case " $PIPELINE_SETTINGS " in *" $1 "*) true ;; *) false ;; esac; }
settings_path() { echo "/$NAME/settings"; }
# Who writes the settings: SETTINGS_PROFILE where the environment has one (a role that can write only its settings),
# else the account's administrator. settings delete is always the administrator's.
settings_writer() {
  if [ -n "$SETTINGS_PROFILE" ] && [ "$SUBCMD" != delete ]; then echo "$SETTINGS_PROFILE"; else echo "$ADMIN_PROFILE"; fi
}

# Who the AWS calls are made as, for messages.
signed_in_as() {
  if [ -n "${AWS_PROFILE:-}" ]; then echo "Profile $AWS_PROFILE"; else echo "The build's role"; fi
}

# The account AWS_PROFILE (in a build, the build's role) is signed in to; stops with the command that signs in if it
# isn't. A build has no SSO token: CodeBuild gives it the role's credentials.
signed_in_account() {
  local who
  if [ "${IN_BUILD:-false}" = true ]; then
    who="$(aws_ sts get-caller-identity --query Account --output text)" || die "The build's role can't sign in (above)."
  else
    who="$(aws_ sts get-caller-identity --query Account --output text 2>/dev/null)" && sso_token_ok ||
      die "Not signed in to AWS for '$ENV'. Run: $(sign_in_hint)"
  fi
  echo "$who"
}

settings_doc() { echo "$(settings_path)/all"; }
SETTINGS_DOC_MAX=4096   # a standard parameter's limit, in bytes

ssm_param_names() {  # every parameter under settings_path, one name per line
  local names
  names="$(aws_ ssm describe-parameters --parameter-filters "Key=Path,Option=OneLevel,Values=$(settings_path)" \
    --query 'Parameters[].Name' --output text)" || die "Couldn't list $(settings_path)/ in SSM (see above)."
  [ "$names" != None ] || names=""
  printf '%s\n' $names | grep . || true
}

# How the environment's settings are kept in SSM: document (settings_doc), parameters (one per setting, before the
# document; settings migrate moves them) or none.
settings_store() {
  local names; names="$(ssm_param_names)" || exit 1
  if grep -qx "$(settings_doc)" <<<"$names"; then echo document
  elif grep -v -x -e "$(settings_path)/REAL_DATA_ACCOUNT" -e "$(settings_path)/RUNNING" <<<"$names" | grep -q .; then echo parameters
  else echo none
  fi
}

read_settings_doc() {  # the document's text; nothing if there's none
  local text
  text="$(aws_ ssm get-parameters --names "$(settings_doc)" --query 'Parameters[0].Value' --output text)" ||
    die "Couldn't read $(settings_doc) in SSM (see above)."
  [ "$text" = None ] || printf '%s\n' "$text"
}

settings_doc_version() {  # the document's version number; None if there's none
  aws_ ssm get-parameters --names "$(settings_doc)" --query 'Parameters[0].Version' --output text ||
    die "Couldn't read $(settings_doc) in SSM (see above)."
}

# The document's settings, one "SETTING<tab>VALUE" line each; stops at the first line that isn't a comment, a blank or
# NAME="value" for a setting ./bmu aws keeps here, naming the line. A value is taken as written, never run: no " $ `
# or \ in it (a value goes into a developer's .local.conf, which is sourced). An empty value is kept, as set to
# nothing: settings push doesn't fill it in.
settings_doc_lines() {  # settings_doc_lines TEXT
  local n=0 line key rest value seen=" "
  local name_re='^[[:space:]]*([A-Z][A-Z0-9_]*)=(.*)$'
  local quoted_re='^"([^"$`\\]*)"([[:space:]]+#.*)?[[:space:]]*$' bare_re="^([^\"\$\`\\\\#'[:space:]]*)([[:space:]]+#.*)?[[:space:]]*\$"
  local where="of $(settings_doc) in SSM"
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1)); line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*(#.*)?$ ]] && continue
    [[ "$line" =~ $name_re ]] || die "Line $n $where isn't NAME=\"value\": $line"
    key="${BASH_REMATCH[1]}" rest="${BASH_REMATCH[2]}"
    if is_pipeline_setting "$key"; then
      die "Line $n $where: $key isn't kept in the document (./bmu aws $([ "$key" = RUNNING ] && echo "pause and resume" || echo pipeline) set it). Remove the line."
    fi
    is_ssm_setting "$key" || die "Line $n $where: $key isn't a setting ./bmu aws reads. They are: $(echo $SSM_SETTINGS)"
    case "$seen" in *" $key "*) die "Line $n $where: $key is set twice." ;; esac
    seen="$seen$key "
    if [[ "$rest" =~ $quoted_re ]] || [[ "$rest" =~ $bare_re ]]; then value="${BASH_REMATCH[1]}"
    else die "Line $n $where: $key's value must be in double quotes, without \" \$ \` or \\ in it: $line"
    fi
    case "$value" in *“*|*”*|*‘*|*’*) die "Line $n $where: $key's value has a curly quote in it (copied from a document?): use straight double quotes: $line" ;; esac
    printf '%s\t%s\n' "$key" "$value"   # an empty value too: the line is there, set to nothing
  done <<<"$1"
}

# One parameter's value ("" if it doesn't exist), read on its own so that a line break in it can't pass for another
# setting's line.
read_param() {  # read_param NAME
  local value
  value="$(aws_ ssm get-parameters --names "$1" --query 'Parameters[0].Value' --output text)" ||
    die "Couldn't read $1 in SSM (see above)."
  [ "$value" = None ] || printf '%s' "$value"
}

# RUNNING and REAL_DATA_ACCOUNT, the parameters beside the document, checked: true or false, and an account number.
pipeline_settings_lines() {  # pipeline_settings_lines NAMES (ssm_param_names' output)
  local key value
  for key in $PIPELINE_SETTINGS; do
    grep -qx "$(settings_path)/$key" <<<"$1" || continue
    value="$(read_param "$(settings_path)/$key")" || exit 1
    case "$key:$value" in
      RUNNING:true|RUNNING:false) ;;
      REAL_DATA_ACCOUNT:*) [[ "$value" =~ ^[0-9]{12}$ ]] || die "$(settings_path)/$key in SSM isn't an account number." ;;
      *) die "$(settings_path)/$key in SSM must be true or false." ;;
    esac
    printf '%s\t%s\n' "$key" "$value"
  done
}

ssm_settings() {  # the environment's settings in SSM, one "SETTING<tab>VALUE" line each, sorted; nothing if none
  local names text out="" line
  names="$(ssm_param_names)" || exit 1
  [ -n "$names" ] || return 0
  if grep -qx "$(settings_doc)" <<<"$names"; then
    text="$(read_settings_doc)" || exit 1
    out="$(settings_doc_lines "$text")" || exit 1
  else   # one parameter per setting, from before the document: each line must be one of them
    # shellcheck disable=SC2086
    set -- $(grep -v -x -e "$(settings_path)/REAL_DATA_ACCOUNT" -e "$(settings_path)/RUNNING" <<<"$names" || true)
    while [ $# -gt 0 ]; do   # GetParameters takes at most 10 names
      text="$(aws_ ssm get-parameters --names "${@:1:10}" --query 'Parameters[].[Name,Value]' --output text)" ||
        die "Couldn't read $(settings_path)/ in SSM (see above)."
      while IFS= read -r line; do
        [ -n "$line" ] || continue
        [[ "$line" =~ ^$(settings_path)/[A-Za-z0-9_.-]+$'\t' ]] ||
          die "A value under $(settings_path)/ in SSM has a line break in it. Fix it in SSM first."
        out+="${line#"$(settings_path)/"}"$'\n'
      done <<<"$text"
      shift $(( $# < 10 ? $# : 10 ))
    done
  fi
  out+=$'\n'"$(pipeline_settings_lines "$names")" || exit 1
  printf '%s\n' "$out" | grep . | sort || true
}

setting_in() {  # setting_in SETTING LINES: its value in ssm_settings' LINES; empty if it isn't there
  printf '%s\n' "$2" | awk -F'\t' -v k="$1" '$1 == k { print substr($0, length(k) + 2); exit }'
}

write_settings_doc() {  # write_settings_doc TEXT: the whole document, after checking it reads back
  local text="$1"
  settings_doc_lines "$text" >/dev/null || exit 1
  [ "$(printf '%s' "$text" | wc -c)" -le "$SETTINGS_DOC_MAX" ] ||
    die "The settings document would be over $SETTINGS_DOC_MAX bytes, a standard parameter's limit."
  aws_ ssm put-parameter --name "$(settings_doc)" --type String --value "$text" --overwrite >/dev/null ||
    die "Couldn't write $(settings_doc) in SSM (see above)."
  aws_ ssm add-tags-to-resource --resource-type Parameter --resource-id "$(settings_doc)" --tags Key=project,Value=bmu
}

settings_doc_header() {
  cat <<EOF
# The BMU's settings for '$ENV' (account $ACCOUNT_ID). One setting per line: NAME="value". Lines starting with # are
# comments. A change applies at the next deploy (with a pipeline: Actions › Deploy). Not here: RUNNING and
# REAL_DATA_ACCOUNT, which ./bmu aws pause, resume and pipeline set. The settings: deploy/README.md in the repository.
EOF
}

# One setting in the document, as the account's administrator or SETTINGS_PROFILE: its line is replaced (or added, or,
# with no VALUE, removed); every other line, comments included, stays as it is. Made against the version it read: if
# someone saved the document in between, it stops rather than undo their change.
set_in_settings_doc() {  # set_in_settings_doc SETTING VALUE
  local key="$1" value="$2" text version out="" line found=false
  case "$value" in *[\"\$\`\\]*|*$'\n'*) die "A setting's value can't have \" \$ \` \\ or a line break in it." ;; esac
  version="$(settings_doc_version)" || exit 1
  text="$(read_settings_doc)" || exit 1
  [ -n "$text" ] || text="$(settings_doc_header)"
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^[[:space:]]*$key= ]]; then
      [ "$found" = true ] || [ -z "$value" ] || out+="$key=\"$value\""$'\n'
      found=true
    else out+="$line"$'\n'
    fi
  done <<<"$text"
  [ "$found" = true ] || [ -z "$value" ] || out+="$key=\"$value\""$'\n'
  [ "$(settings_doc_version)" = "$version" ] ||
    die "Someone saved $(settings_doc) just now. Nothing was changed: run the command again."
  write_settings_doc "${out%$'\n'}"
}

put_setting() {  # put_setting SETTING VALUE: in SSM; an empty VALUE removes it (SSM has no empty values)
  local name
  if is_pipeline_setting "$1"; then   # a parameter of its own, beside the document
    name="$(settings_path)/$1"
    if [ -z "$2" ]; then aws_ ssm delete-parameter --name "$name" >/dev/null 2>&1 || true; return 0; fi
    aws_ ssm put-parameter --name "$name" --type String --value "$2" --overwrite >/dev/null
    aws_ ssm add-tags-to-resource --resource-type Parameter --resource-id "$name" --tags Key=project,Value=bmu
    return 0
  fi
  local store; store="$(settings_store)" || exit 1
  [ "$store" != parameters ] ||
    die "'$ENV' keeps its settings one parameter each, from before the settings document. The account's administrator (or SETTINGS_PROFILE) moves them first: ./bmu aws settings migrate --env $ENV"
  set_in_settings_doc "$1" "$2"
}

# The settings from SSM in place of the files' (load_env), before load_env checks them. The account is checked first,
# against this computer's ACCOUNT_ID if it has one; then SSM's ACCOUNT_ID must be the account it was read from.
from_ssm() {
  local who lines key value file_values="" differ=""
  export AWS_PAGER=""
  who="$(signed_in_account)" || exit 1
  [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "$who" ] ||
    die "$(signed_in_as) is signed in to account $who, but '$ENV' is account $ACCOUNT_ID ($LOCAL). Stopped."
  lines="$(ssm_settings)" || exit 1
  [ -n "$lines" ] || die "'$ENV' keeps its settings in SSM (SETTINGS=ssm), and account $who has none under $(settings_path)/.
The account's administrator (or SETTINGS_PROFILE) puts them there from $CONF and $LOCAL: ./bmu aws settings push --env $ENV"
  for key in $SSM_SETTINGS; do
    file_values="$file_values$key	${!key}
"
    printf -v "$key" '%s' "$(setting_in "$key" "$lines")"
  done
  for key in $PIPELINE_SETTINGS; do printf -v "$key" '%s' "$(setting_in "$key" "$lines")"; done
  [ "$ACCOUNT_ID" = "$who" ] ||
    die "SSM's ACCOUNT_ID for '$ENV' (${ACCOUNT_ID:-none}) isn't the account it is in ($who). Stopped: check the account the profile signs in to."
  while IFS='	' read -r key value; do
    [ -n "$key" ] || continue
    is_ssm_setting "$key" || is_pipeline_setting "$key" ||
      echo "Note: $(settings_path)/$key in SSM isn't a setting ./bmu aws reads; ignored." >&2
  done <<EOF
$lines
EOF
  for key in $SSM_SETTINGS; do
    value="$(setting_in "$key" "$file_values")"
    [ -z "$value" ] || [ "$value" = "${!key}" ] || differ="$differ $key"
  done
  [ -z "$differ" ] ||
    echo "Note: the files on this computer differ from SSM in$differ; SSM's are used (./bmu aws settings pull brings the files up to date)." >&2
}

# ./bmu aws settings push|set|pull|show|migrate|delete (SETTINGS=ssm). The account is this computer's ACCOUNT_ID, asked the
# first time as for a deploy. push, set and delete run as the environment's SETTINGS_PROFILE or ADMIN_PROFILE, if it has
# one (settings_writer); pull and show as the deployer.
settings() {
  load_env
  [ "$SETTINGS" = ssm ] || die "'$ENV' keeps its settings in $CONF and $LOCAL. To keep them in SSM Parameter Store instead
(design: Deploys, BP4), add SETTINGS=ssm to $LOCAL, then: ./bmu aws settings push --env $ENV"
  check_account
  case "${1:-}" in
    push) settings_push ;;
    set) [ $# -ge 2 ] && [ $# -le 3 ] || die "./bmu aws settings set --env $ENV SETTING [VALUE] (no VALUE removes it)"
      settings_set "$2" "${3:-}" ;;
    pull) settings_pull ;;
    show) settings_show ;;
    migrate) settings_migrate ;;
    delete) settings_delete ;;
    *) die "./bmu aws settings push|set|pull|show|migrate|delete" ;;
  esac
}

# A new environment's settings, from the files (after load_env's defaults) to SSM. It only adds: a setting SSM already
# has stays as SSM has it, since SSM is their one copy, which anyone with access may change (Operations too, in the
# console), and the files here may be out of date. Always asks, even with BMU_AWS_YES=1.
settings_push() {
  local lines key value old adds="" kept="" ok store text
  store="$(settings_store)" || exit 1
  [ "$store" != parameters ] ||
    die "'$ENV' keeps its settings one parameter each, from before the settings document: ./bmu aws settings migrate --env $ENV"
  lines="$(ssm_settings)" || exit 1
  for key in $SSM_SETTINGS; do
    value="${!key}"; old="$(setting_in "$key" "$lines")"
    [ "$value" != "$old" ] || continue
    # A line SSM has, even set to nothing ("" on purpose), stays as it is.
    if [ -z "$old" ] && case $'\n'"$lines"$'\n' in *$'\n'"$key"$'\t'*) false ;; *) true ;; esac; then
      case "$value" in *[\"\$\`\\]*) die "$key's value can't have \" \$ \` or \\ in it ($CONF, $LOCAL)." ;; esac
      adds="$adds$key "
    else kept="$kept  $key=$old   (the files here: ${value:-not set})
"
    fi
  done
  if [ -n "$kept" ]; then
    echo "SSM already has these, and they stay as SSM has them (change one with ./bmu aws settings set --env $ENV;"
    echo "bring the files here up to date with ./bmu aws settings pull --env $ENV):"
    printf '%s' "$kept"
  fi
  if [ -z "$adds" ]; then
    echo "Nothing to add to $(settings_doc) (account $ACCOUNT_ID)."
    return 0
  fi
  echo "From $CONF and $LOCAL to $(settings_doc), account $ACCOUNT_ID:"
  for key in $adds; do echo "  + $key=${!key}"; done
  read -r -p "Write these to SSM? The next deploy uses them. [y/N] " ok
  case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
  if [ "$store" = none ]; then   # the whole document at once
    text="$(settings_doc_header)"
    for key in $adds; do text+=$'\n'"$key=\"${!key}\""; done
    write_settings_doc "$text"
  else
    for key in $adds; do set_in_settings_doc "$key" "${!key}"; done
  fi
  echo "Done. ./bmu aws plan --env $ENV shows what they change."
}

# An environment from before the settings document (one parameter per setting) moved into it, as the account's
# administrator or SETTINGS_PROFILE: the document is written from SSM's values (never the files'), read back, and only
# then are the old parameters deleted. RUNNING and REAL_DATA_ACCOUNT stay parameters of their own. Always asks.
settings_migrate() {
  local store lines key value text other="" ok
  store="$(settings_store)" || exit 1
  case "$store" in
    document) echo "'$ENV' already keeps its settings in one document, $(settings_doc)."; return 0 ;;
    none) die "'$ENV' has no settings in SSM yet: ./bmu aws settings push --env $ENV" ;;
  esac
  lines="$(ssm_settings)" || exit 1
  text="$(settings_doc_header)"
  for key in $SSM_SETTINGS; do
    value="$(setting_in "$key" "$lines")"
    [ -n "$value" ] || continue
    case "$value" in *[\"\$\`\\]*) die "$(settings_path)/$key's value has \" \$ \` or \\ in it: fix it in SSM first." ;; esac
    text+=$'\n'"$key=\"$value\""
  done
  while IFS='	' read -r key value; do
    [ -z "$key" ] || is_ssm_setting "$key" || is_pipeline_setting "$key" || other="$other $key"
  done <<<"$lines"
  echo "This moves the settings of '$ENV' (account $ACCOUNT_ID) into one document, $(settings_doc):"
  echo
  printf '%s\n' "$text"
  echo
  echo "Then it deletes the parameters they came from. RUNNING and REAL_DATA_ACCOUNT stay as they are."
  [ -z "$other" ] || echo "Left alone, as ./bmu aws doesn't read them:$other"
  read -r -p "Go ahead? [y/N] " ok
  case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
  write_settings_doc "$text"
  [ "$(settings_doc_lines "$(read_settings_doc)")" = "$(settings_doc_lines "$text")" ] ||
    die "$(settings_doc) didn't read back as written: the old parameters are kept. Check it in the AWS console."
  for key in $SSM_SETTINGS; do
    [ -z "$(setting_in "$key" "$lines")" ] || aws_ ssm delete-parameter --name "$(settings_path)/$key" >/dev/null
  done
  echo "Done. Edit it in the AWS console (Systems Manager › Parameter Store › $(settings_doc)) or with ./bmu aws settings set."
}

settings_in_files_only() {  # settings_in_files_only LINES: ssm_settings' LINES, less what pipeline commands write
  local key value
  while IFS='	' read -r key value; do
    [ -z "$key" ] || is_pipeline_setting "$key" || echo "$key"
  done <<EOF
$1
EOF
}

# One setting, in SSM and in the files here, as SETTINGS_PROFILE or the administrator; no VALUE removes it. The other
# settings aren't touched, so nobody else's change is undone. Always asks, even with BMU_AWS_YES=1.
settings_set() {  # settings_set SETTING VALUE
  local key="$1" value="$2" lines old ok
  is_pipeline_setting "$key" &&
    die "$key is set by ./bmu aws $([ "$key" = RUNNING ] && echo "pause and resume" || echo pipeline), not settings set."
  is_ssm_setting "$key" || die "$key isn't a setting ./bmu aws keeps in SSM. Those are: $(echo $SSM_SETTINGS)"
  [ "$key" != ACCOUNT_ID ] || die "ACCOUNT_ID is the account the settings are in ($ACCOUNT_ID): it can't be set."
  case "$key:$value" in
    SIMULATED_CSPACE:*|PROTECT_DATA:*|ALWAYS_RUN_TIME:*|WAF_ENABLED:*|CREATE_GATEWAY_ENDPOINTS:*|REHEARSAL:*)
      case "$value" in true|false|"") ;; *) die "$key must be true or false." ;; esac ;;
    FRONT_DOOR:*) case "$value" in cloudfront|alb|"") ;; *) die "FRONT_DOOR must be cloudfront or alb." ;; esac ;;
    WAF_MANAGED_RULES:*) case "$value" in count|block|"") ;; *) die "WAF_MANAGED_RULES must be count or block." ;; esac ;;
  esac
  lines="$(ssm_settings)" || exit 1
  [ -n "$(settings_in_files_only "$lines")" ] ||
    die "'$ENV' has no settings in SSM yet (account $ACCOUNT_ID, $(settings_path)/): ./bmu aws settings push --env $ENV"
  old="$(setting_in "$key" "$lines")"
  if [ "$value" = "$old" ]; then echo "$key is already ${value:-not set} in SSM."
  else
    echo "In SSM, account $ACCOUNT_ID, $(settings_path)/:"
    if [ -z "$old" ]; then echo "  + $key=$value"
    elif [ -z "$value" ]; then echo "  - $key (was $old)"
    else echo "  ~ $key=$value (was $old)"
    fi
    read -r -p "Write this to SSM? The next deploy uses it. [y/N] " ok
    case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
    put_setting "$key" "$value"
  fi
  save_local "$key" "$value"   # CMD=settings: the files here only
  echo "Done. ./bmu aws plan --env $ENV shows what it changes."
}

# The files here brought up to date with SSM: each setting that differs is written to the .local.conf (one SSM doesn't
# have, as empty). Only the files here change; the profiles and SETTINGS, which are always the files', are kept.
settings_pull() {
  local lines key value changes=0
  lines="$(ssm_settings)" || exit 1
  [ -n "$(settings_in_files_only "$lines")" ] ||
    die "'$ENV' has no settings in SSM yet (account $ACCOUNT_ID, $(settings_path)/): ./bmu aws settings push --env $ENV"
  for key in $SSM_SETTINGS; do   # every value checked before any is written, so the .local.conf is never half done
    case "$(setting_in "$key" "$lines")" in
      *[\"\$\`\\]*) die "$(settings_path)/$key's value in SSM has \" \$ \` or \\ in it: fix it in SSM first. Nothing was changed here." ;;
    esac
  done
  for key in $SSM_SETTINGS; do
    value="$(setting_in "$key" "$lines")"
    [ "$value" != "${!key}" ] || continue
    # Not in SSM, and only a default here (load_env's, not in the files): nothing to bring.
    [ -n "$value" ] || grep -q "^[[:space:]]*$key=" "$CONF" "$LOCAL" 2>/dev/null || continue
    echo "  $key=$value   (was ${!key:-not set})"
    save_local "$key" "$value"
    changes=$((changes + 1))
  done
  if [ "$changes" = 0 ]; then echo "The files here already match SSM ($(settings_path)/)."
  else echo "Updated $changes setting(s) in $LOCAL from SSM ($(settings_path)/)."
  fi
}

settings_show() {
  local lines key value differ=""
  lines="$(ssm_settings)" || exit 1
  local store version; store="$(settings_store)" || exit 1
  case "$store" in
    document) version="$(settings_doc_version)" || exit 1
      echo "'$ENV' in SSM, account $ACCOUNT_ID, the document $(settings_doc) (version $version):" ;;
    parameters) echo "'$ENV' in SSM, account $ACCOUNT_ID, one parameter per setting under $(settings_path)/"
      echo "(from before the settings document: ./bmu aws settings migrate --env $ENV moves them into one):" ;;
    *) echo "'$ENV' in SSM, account $ACCOUNT_ID, $(settings_path)/:" ;;
  esac
  [ -n "$lines" ] || { echo "  none yet (./bmu aws settings push --env $ENV)"; return 0; }
  while IFS='	' read -r key value; do
    if [ "$key" = REAL_DATA_ACCOUNT ]; then echo "  $key=$value   (set by ./bmu aws pipeline)"
    elif [ "$key" = RUNNING ]; then echo "  $key=$value   (set by ./bmu aws pause and resume)"
    elif ! is_ssm_setting "$key"; then echo "  $key=$value   (not a setting ./bmu aws reads; ignored)"
    elif [ "${!key}" != "$value" ]; then echo "  $key=$value   (the files here: ${!key:-not set})"; differ=yes
    else echo "  $key=$value"
    fi
  done <<EOF
$lines
EOF
  for key in $SSM_SETTINGS; do
    [ -z "${!key}" ] || [ -n "$(setting_in "$key" "$lines")" ] ||
      { echo "  ($key isn't in SSM; the files here: ${!key})"; differ=yes; }
  done
  [ -z "$differ" ] || echo "SSM's are the ones used. To bring the files here up to date: ./bmu aws settings pull --env $ENV"
}

settings_delete() {  # only once the environment is destroyed: a deploy, plan or destroy needs them
  local lines key value ok
  for key in app registry pipeline rehearsal; do
    ! state_has_resources "$key" ||
      die "'$ENV' is still deployed (bmu/$BMU_ENV_NAME/$key.tfstate): destroy it first (./bmu aws destroy, pipeline destroy, then rehearsal-vpc destroy for a rehearsal)."
  done
  lines="$(ssm_param_names)" || exit 1
  [ -n "$lines" ] || { echo "'$ENV' has no settings in SSM (account $ACCOUNT_ID, $(settings_path)/)."; return 0; }
  echo "This deletes $(printf '%s\n' "$lines" | grep -c .) parameter(s) of '$ENV' in SSM, account $ACCOUNT_ID, $(settings_path)/."
  echo "The files on this computer stay."
  read -r -p "Type the environment's name ($ENV) to go ahead: " ok
  [ "$ok" = "$ENV" ] || die "Stopped; nothing was deleted."
  while IFS= read -r key; do
    [ -z "$key" ] || aws_ ssm delete-parameter --name "$key" >/dev/null
  done <<EOF
$lines
EOF
  echo "Done."
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

# The command that signs in for AWS_PROFILE. aws sso login --profile works only for a profile with SSO settings of its
# own: a profile that takes a role (source_profile) signs in through the profile it takes it from, and a profile on an
# SSO session through that session (--sso-session), as for the UC Berkeley environments.
# sso_profile prints the profile at the end of AWS_PROFILE's source_profile chain, the one whose SSO settings sign in.
sso_profile() {
  local profile="$AWS_PROFILE" source hops=0
  while source="$(aws configure get source_profile --profile "$profile" 2>/dev/null)" && [ -n "$source" ] && [ "$hops" -lt 5 ]; do
    profile="$source"; hops=$((hops + 1))
  done
  echo "$profile"
}

sign_in_hint() {
  local profile session
  profile="$(sso_profile)"
  session="$(aws configure get sso_session --profile "$profile" 2>/dev/null)" || session=""
  if [ -n "$session" ]; then
    echo "aws sso login --sso-session $session"
  else
    echo "aws sso login --profile $profile"
  fi
}

# Whether the SSO token Terraform starts from is there. The AWS CLI keeps the credentials of a role it took
# (source_profile) in ~/.aws/cli/cache for up to an hour, and aws sso logout leaves them, so sts get-caller-identity
# can pass while Terraform, whose SDK doesn't read that cache, has no token and fails in terraform init. The SDKs
# keep the token in ~/.aws/sso/cache/<SHA-1 of the sso-session's name, or of the start URL>.json (the SSO token
# provider's documented cache). Good: not expired, or (an sso-session) a refresh token the SDK can renew it with.
# Reads only the file's expiry and whether it has a refresh token; prints nothing. A profile without SSO passes,
# as does a computer without python3 (the sts check alone, as before).
sso_token_ok() {
  local profile key
  profile="$(sso_profile)"
  key="$(aws configure get sso_session --profile "$profile" 2>/dev/null)" ||
    key="$(aws configure get sso_start_url --profile "$profile" 2>/dev/null)" || return 0
  [ -n "$key" ] && command -v python3 >/dev/null || return 0
  python3 - "$HOME/.aws/sso/cache" "$key" "$(aws configure get sso_session --profile "$profile" 2>/dev/null)" <<'PY' 2>/dev/null
import datetime, hashlib, json, os, sys
cache, key, session = sys.argv[1:4]
try:
    with open(os.path.join(cache, hashlib.sha1(key.encode()).hexdigest() + ".json")) as f:
        token = json.load(f)
    expires = datetime.datetime.strptime(token["expiresAt"].replace("UTC", "Z")[:19], "%Y-%m-%dT%H:%M:%S")
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    sys.exit(1)
now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
sys.exit(0 if expires > now or (session and token.get("refreshToken")) else 1)
PY
}

# Signed in, and to the account this environment was first deployed to.
check_account() {
  local who
  who="$(signed_in_account)" || exit 1
  if [ -z "$ACCOUNT_ID" ]; then
    echo "Profile $AWS_PROFILE is signed in to AWS account $who."
    read -r -p "Is that the account for the '$ENV' environment? [y/N] " ok
    case "$ok" in y|Y|yes) ;; *) die "Stopped; nothing was changed." ;; esac
    check_not_someone_elses "$who"
    save_local ACCOUNT_ID "$who"; ACCOUNT_ID="$who"
  elif [ "$who" != "$ACCOUNT_ID" ]; then
    die "$(signed_in_as) is signed in to account $who, but '$ENV' is account $ACCOUNT_ID ($LOCAL). Stopped."
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
  [ "$SETTINGS" = files ] ||
    die "'$ENV' has no ALLOWED_CIDRS in SSM. The account's administrator (or SETTINGS_PROFILE) adds the allowed ranges: ./bmu aws settings set --env $ENV ALLOWED_CIDRS \"<cidr>,<cidr>\""
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

tf() {  # tf registry|app|ci|rehearsal <terraform arguments>
  local part="$1"; shift
  terraform -chdir="$TF_DIR/$part" "$@"
}

tf_init() {  # tf_init registry|app|rehearsal: point Terraform at this environment's state (the lock is a file beside it)
  tf "$1" init -input=false -reconfigure \
    -backend-config="bucket=$STATE_BUCKET" -backend-config="key=bmu/$BMU_ENV_NAME/$1.tfstate" \
    -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true" >/dev/null ||
    die "terraform init failed for $1. Run it again without '>/dev/null' to see why: ./bmu aws init"
}

cidr_list() {  # cidr_list [VALUE]: "a/32,b/24" (ALLOWED_CIDRS by default) -> ["a/32","b/24"]; "" -> []
  local v
  v="$(printf '%s' "${1-$ALLOWED_CIDRS}" | tr ' ' ',' | sed 's/,,*/,/g; s/^,//; s/,$//')"
  if [ -z "$v" ]; then printf '[]'; else printf '["%s"]' "$(printf '%s' "$v" | sed 's/,/","/g')"; fi
}

# The app configuration's variables. app_vars IMAGE RUNNING fills the array TF_VARS.
app_vars() {  # app_vars IMAGE RUNNING [SIMULATOR-IMAGE]
  TF_VARS=(
    -var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$BMU_ENV_NAME" -var "image_uri=$1" -var "running=$2"
    -var "allowed_cidrs=$(cidr_list)" -var "tenants=$(tenants_var)"
    -var "env_label=$ENV_LABEL" -var "always_run_time=$ALWAYS_RUN_TIME" -var "protect_data=${PROTECT_DATA:-false}"
    -var "simulated_cspace=$SIMULATED_CSPACE" -var "fakecspace_image_uri=${3:-}"
    -var "waf_enabled=$WAF_ENABLED" -var "origin_domain=$ORIGIN_DOMAIN" -var "origin_certificate_arn=$ORIGIN_CERTIFICATE_ARN"
    -var "vpc_id=$VPC_ID" -var "app_subnet_ids=$(cidr_list "$APP_SUBNET_IDS")" -var "lb_subnet_ids=$(cidr_list "$LB_SUBNET_IDS")"
    -var "create_gateway_endpoints=$CREATE_GATEWAY_ENDPOINTS"
    -var "front_door=$FRONT_DOOR" -var "domain_name=$DOMAIN_NAME" -var "certificate_arn=$CERTIFICATE_ARN"
    -var "waf_managed_rules=$WAF_MANAGED_RULES"
  )
}

registry_vars() {  # with FRONT_DOOR=alb, the registry also requests DOMAIN_NAME's certificate
  REGISTRY_VARS=(-var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$BMU_ENV_NAME" -var "simulated_cspace=$SIMULATED_CSPACE"
    -var "domain_name=$DOMAIN_NAME")
}

# ---- the certificate (FRONT_DOOR=alb) -------------------------------------------------------------------------------
# DOMAIN_NAME's certificate is in ../registry (DNS-validated). It is issued only once Operations has added its
# validation record (BQ32); until then deploy says which record and stops before the app, so it never waits on
# someone else's step. The record stays valid for the same name in the same account, after a destroy too.
load_certificate() {  # CERTIFICATE_ARN from ../registry's state; empty with FRONT_DOOR=cloudfront or before a deploy
  CERTIFICATE_ARN=""
  [ "$FRONT_DOOR" = alb ] || return 0
  tf_init registry
  CERTIFICATE_ARN="$(tf registry output -raw certificate_arn 2>/dev/null || true)"
  case "$CERTIFICATE_ARN" in arn:*) ;; *) CERTIFICATE_ARN="" ;; esac
}

certificate_issued() {  # fails, after printing its validation record, while the certificate isn't issued
  local status
  [ -n "$CERTIFICATE_ARN" ] || die "No certificate for $DOMAIN_NAME in ../registry's state. Run ./bmu aws deploy again."
  status="$(aws_ acm describe-certificate --certificate-arn "$CERTIFICATE_ARN" --query Certificate.Status --output text)"
  [ "$status" = ISSUED ] && return 0
  echo
  echo "The certificate for $DOMAIN_NAME is $status. Operations adds this record in DNS, once (ACM renews the certificate after):"
  aws_ acm describe-certificate --certificate-arn "$CERTIFICATE_ARN" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.[Type,Name,Value]' --output text
  return 1
}

need_certificate() {
  certificate_issued ||
    die "Run ./bmu aws deploy again once the record is in DNS and the certificate is ISSUED. The app wasn't changed."
}

# ---- what may be deployed -------------------------------------------------------------------------------------------
# A front door can't change in place: the load balancer (internal or internet-facing), its security group and the
# address all change, and CloudFront's go. An environment deployed before FRONT_DOOR existed is cloudfront.
# Runs after tf_init app; nothing is checked before the first deploy.
check_front_door() {
  local was
  was="$(applied front_door)"
  if [ -z "$was" ]; then
    [ -n "$(applied image_uri)" ] || return 0
    was=cloudfront
  fi
  [ "$was" = "$FRONT_DOOR" ] && return 0
  die "'$ENV' was deployed with FRONT_DOOR=$was, but its settings now say $FRONT_DOOR. A front door can't change in place.
Stopped; nothing was changed. Put the setting back; to change it, run ./bmu aws destroy with the old setting first
(it deletes the BMU's data), then deploy with the new one."
}

# BQ27: an environment with REQUIRE_CLEAN=true runs only what is on main, so a deploy (or any apply) comes from a
# checkout with no changes or untracked files whose HEAD is on origin/main, after fetching it.
check_clean() {
  [ "$REQUIRE_CLEAN" = true ] || return 0
  git rev-parse --git-dir >/dev/null 2>&1 || die "'$ENV' is deployed only from a git checkout (REQUIRE_CLEAN=true in $CONF)."
  [ -z "$(git status --porcelain 2>/dev/null)" ] ||
    die "'$ENV' is deployed only from a clean checkout (REQUIRE_CLEAN=true in $CONF), and this one has changes or untracked files (git status). Stopped; nothing was changed."
  git fetch --quiet origin main ||
    die "Couldn't fetch origin/main to check this checkout (REQUIRE_CLEAN=true in $CONF). Stopped; nothing was changed."
  git merge-base --is-ancestor HEAD origin/main ||
    die "'$ENV' runs only what is on main (REQUIRE_CLEAN=true in $CONF), and this checkout's HEAD ($(git rev-parse --short HEAD)) isn't on origin/main. Check out main and pull. Stopped; nothing was changed."
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

# Each museum's jobs, drafts, CSIDs, saved sign-ins and audit entries belong to the CollectionSpace server it was
# deployed for, and a queued job would run on whatever server it points at next: so a deployed museum's server never
# changes. A museum can be added. One can be removed only when it has no unfinished jobs (anything but Completed:
# drafts, queued or running jobs, and ones needing attention or failed, which can still be fixed and run again), and
# when its name is typed: its staging key is deleted with it, and with the key, its staged and audit files become
# unreadable. Never where data is protected. Runs after tf_init app; nothing is checked before the first deploy.
# In the pipeline's plan build (build), nobody is asked: a removal is shown with the plan, the reviewer approves it, and
# REMOVED_MUSEUMS names it in the workflow's summary.
check_museums() {  # check_museums ask|look|build: ask = this command applies (removing asks first); look = plan only
  local applied museum url now removed="" n ok
  REMOVED_MUSEUMS=""
  applied="$(applied museums)"
  if [ -z "$applied" ]; then
    # Deployed before environments listed museums: one key and secret for the whole environment, which a deploy now
    # would replace, losing its files and the secret's value. No migration (a prototype): destroy and deploy again.
    [ -z "$(applied cspace_url)" ] ||
      die "'$ENV' was deployed before environments listed their museums, and can't be updated in place: its staging
key and read-only account's secret would be replaced, and its staged and audit files lost. Stopped; nothing was
changed. Run ./bmu aws destroy, then ./bmu aws deploy."
    return 0   # never deployed: nothing to check
  fi
  for museum in $(museum_names "$applied"); do
    url="$(server_of "$museum" "$applied")"
    if now="$(server_of "$museum")"; then
      [ "$now" = "$url" ] && continue
      echo "'$ENV' was deployed with $museum on $url, but its settings now say $now." >&2
      echo "$museum's jobs, drafts and audit entries refer to records on the first, and a queued job would run on the new one." >&2
      die "Stopped; nothing was changed. Put the setting back; or run ./bmu aws destroy first (it deletes the BMU's data);
or deploy the new server as another environment: a different BMU_ENV_NAME in $LOCAL."
    fi
    removed="$removed $museum"
  done
  for museum in $(museum_names); do
    server_of "$museum" "$applied" >/dev/null || echo "Adding the museum $museum ($(server_of "$museum"))."
  done
  for museum in $removed; do
    [ "${PROTECT_DATA:-false}" != true ] ||
      die "Stopped; nothing was changed. '$ENV' protects its data (PROTECT_DATA=true), so $museum can't be removed: its key would go, and with it, its audit files."
    n="$(aws_ dynamodb query --table-name "$NAME-jobs" --index-name tenant --select COUNT --query Count --output text \
          --key-condition-expression "#t = :t" --filter-expression "#k = :meta AND #s <> :done" \
          --expression-attribute-names '{"#t":"tenant","#k":"SK","#s":"status"}' \
          --expression-attribute-values "{\":t\":{\"S\":\"$museum\"},\":meta\":{\"S\":\"META\"},\":done\":{\"S\":\"Completed\"}}")" ||
      die "Stopped; nothing was changed. Couldn't count $museum's unfinished jobs in the table $NAME-jobs."
    [ "$n" = 0 ] ||
      die "Stopped; nothing was changed. $museum is no longer in the settings, but it has $n unfinished job(s) in '$ENV' (drafts, queued, running, needing attention or failed). Put it back in CSPACE_TENANTS, finish or delete its jobs, then try again."
    echo "$museum is no longer in the settings. Removing it deletes its read-only account's secret and its staging key"
    echo "(after 7 days), and with the key, its staged files and audit files become unreadable. Its jobs and audit"
    echo "entries stay in the tables. Its users can no longer sign in."
    REMOVED_MUSEUMS="${REMOVED_MUSEUMS:+$REMOVED_MUSEUMS }$museum"
    case "$1" in
      look) echo "(./bmu aws deploy asks before removing it.)"; continue ;;
      build) echo "(The reviewer approves its removal with this plan.)"; continue ;;
    esac
    read -r -p "Type the museum's name ($museum) to remove it: " ok || ok=""
    [ "$ok" = "$museum" ] || die "Stopped; nothing was changed."
  done
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

# Once an environment has a pipeline, the pipeline deploys it (BP6): a deploy from here is break-glass, for when the
# pipeline is broken and a deploy is urgent; the next pipeline run checks the environment matches main.
need_break_glass() {
  local typed
  has_pipeline || return 0
  echo
  echo "'$ENV' has a deploy pipeline (pipeline-bmu-$ENV-…): it deploys it (Actions › Deploy, from main)."
  echo "Deploy it from here only if the pipeline can't, as a break-glass deploy (design: Deploys); CloudTrail records it."
  read -r -p "Type 'break glass' to go ahead: " typed || typed=""
  [ "$typed" = "break glass" ] || die "Stopped; nothing was deployed."
}

# UC Berkeley data only in UC Berkeley AWS accounts (BP7). An environment with a real CollectionSpace (a museum from
# backend/bmu/tenants/, production or QA: Lyrasis's QA tenants hold a copy of production's records) keeps that museum's
# data in its account, so every deploy of one shows the rule and waits for the person deploying to type the account's
# number. With the simulated CollectionSpace, nothing is asked.
acknowledge_real_data() {
  [ "$SIMULATED_CSPACE" != true ] || return 0
  local typed
  echo
  echo "WARNING: '$ENV' uses a real CollectionSpace: $(museum_names | tr '\n' ' ')"
  echo "The BMU keeps UC Berkeley museum data in AWS account $ACCOUNT_ID: staff's sign-ins while their jobs wait, their"
  echo "staged media, and the records of what it created. UC Berkeley data, from production or QA, is allowed only in a"
  echo "UC Berkeley AWS account, never in a personal one."
  read -r -p "If $ACCOUNT_ID is a UC Berkeley account, type its number to go ahead: " typed || typed=""
  [ "$typed" = "$ACCOUNT_ID" ] || die "Stopped; nothing was deployed."
  echo
}

deploy() {
  load_env; check_account; need_break_glass; acknowledge_real_data; ensure_allowlist; need_terraform
  command -v docker >/dev/null || die "Docker isn't installed or isn't on the PATH."
  docker info >/dev/null 2>&1 || die "Docker isn't running. Start Docker Desktop and try again."
  check_clean
  ensure_state_bucket
  tf_init app; check_front_door; check_museums ask   # before building anything
  local tag repo registry image sim_image url code
  tag="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
  [ -z "$(git status --porcelain 2>/dev/null)" ] || tag="$tag-dirty"
  tag="$tag-$(date -u +%Y%m%d%H%M%S)"

  echo "== 1/3 Image repository"
  registry_vars
  tf_init registry
  tf registry apply -input=false -auto-approve "${REGISTRY_VARS[@]}"
  repo="$(tf registry output -raw repository_url)"
  if [ "$FRONT_DOOR" = alb ]; then load_certificate; need_certificate; fi
  registry="${repo%%/*}"
  image="$repo:$tag"

  echo "== 2/3 Image $image (linux/arm64)"
  docker build --pull --platform linux/arm64 -f deploy/Dockerfile -t "$image" .
  # The registry's short-lived token goes straight from the AWS CLI to Docker; it is never shown or saved here.
  aws_ ecr get-login-password | docker login --username AWS --password-stdin "$registry" >/dev/null
  docker push "$image"
  sim_image=""
  if [ "$SIMULATED_CSPACE" = true ]; then
    sim_image="$(tf registry output -raw fakecspace_repository_url):$tag"
    echo "== 2/3 Simulated CollectionSpace image $sim_image (linux/arm64)"
    docker build --pull --platform linux/arm64 -f deploy/fakecspace.Dockerfile -t "$sim_image" .
    docker push "$sim_image"
  fi

  echo "== 3/3 The BMU. Terraform shows its plan and asks before changing anything."
  if [ "$FRONT_DOOR" = cloudfront ]; then
    echo "   The first time takes about 15-25 minutes (CloudFront); it finishes when the web app and worker are running."
  else
    echo "   The first time takes about 5-10 minutes; it finishes when the web app and worker are running."
  fi
  echo "   If a task can't start, Terraform waits up to 20 minutes before saying so: ./bmu aws logs web shows why sooner."
  # A deploy starts the services, except in a pipeline environment paused with ./bmu aws pause (RUNNING=false in SSM).
  app_vars "$image" "$RUNNING" "$sim_image"
  # shellcheck disable=SC2046
  tf app apply -input=false $(approve) "${TF_VARS[@]}"
  [ "$SIMULATED_CSPACE" = false ] || sim_reader_secret

  url="$(app_url)"
  echo "$url" > "$URL_FILE"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url/api/health" || true)"
  echo
  echo "$ENV_LABEL is up: $url   (./bmu open aws)"
  if [ "$FRONT_DOOR" = alb ]; then
    echo "DNS: $DOMAIN_NAME must point at the load balancer $(applied alb_dns_name)"
    echo "(Operations' record: a CNAME, or an alias; a new load balancer, after a destroy, needs the record changed)."
    [ "$code" = 200 ] || echo "Note: $url/api/health answered $code. Check the DNS record, and that this computer's address is in ALLOWED_CIDRS (campus or VPN)."
  else
    [ "$code" = 200 ] || echo "Note: $url/api/health answered $code. A new CloudFront address can take a few minutes to work everywhere."
  fi
  if [ "$SIMULATED_CSPACE" = true ]; then
    echo "It uses the simulated CollectionSpace: sign in with the simulator's accounts (deploy/README.md). Its records"
    echo "are lost whenever it restarts (a pause, a deploy), while the BMU keeps its jobs."
  else
    echo "Careful: jobs run here create real records in each museum's CollectionSpace, and they stay:"
    for museum in $(museum_names); do echo "  $museum: $(server_of "$museum")"; done
  fi
}

was_running() {  # true unless the environment is paused
  [ "$(tf app output -raw running 2>/dev/null || true)" = false ] && echo false || echo true
}

need_certificate_arn() {  # for a command that applies or plans the deployed app: the certificate deploy requested
  load_certificate
  [ "$FRONT_DOOR" != alb ] || [ -n "$CERTIFICATE_ARN" ] ||
    die "No certificate for $DOMAIN_NAME in ../registry's state. Run ./bmu aws deploy."
}

plan() {
  look; need_deployed; check_front_door; check_museums look; need_certificate_arn
  app_vars "$IMAGE" "$(was_running)" "$(applied fakecspace_image_uri)"
  tf app plan -input=false "${TF_VARS[@]}"
}

# Pause or resume (BP5). In a pipeline environment, whether the services run is the setting RUNNING in SSM, which the
# settings' writer (SETTINGS_PROFILE, else the administrator) sets here (the deployer can't write SSM) and the next
# pipeline run applies, with an approved plan. Otherwise it's applied at once, as before.
pause_resume() {  # pause_resume false|true
  prepare
  if has_pipeline; then
    [ -n "$(settings_writer)" ] || die "'$ENV' has a deploy pipeline: pause and resume set RUNNING in SSM, as SETTINGS_PROFILE or the account's administrator. Set SETTINGS_PROFILE or ADMIN_PROFILE in $LOCAL or $CONF."
    AWS_PROFILE="$(settings_writer)"
    [ "$(signed_in_account)" = "$ACCOUNT_ID" ] || die "Profile $AWS_PROFILE isn't signed in to account $ACCOUNT_ID. Stopped."
    if [ "$RUNNING" = "$1" ]; then
      echo "RUNNING is already $1 in SSM ($(settings_path)/RUNNING)."
    else
      put_setting RUNNING "$1"
      echo "Saved RUNNING=$1 in SSM ($(settings_path)/RUNNING), as $AWS_PROFILE."
    fi
    echo "The pipeline applies it: Actions › Deploy › Run workflow, from main, with the environment $ENV."
    return 0
  fi
  reapply "$1"
  if [ "$1" = false ]; then echo "Paused: no tasks run (./bmu aws resume)."; else echo "Running: $(app_url)"; fi
}

# Apply again with the running image: for a changed setting (pause, resume, the allowlist).
reapply() {  # reapply RUNNING
  prepare; check_clean; tf_init app; need_deployed; check_front_door; check_museums ask; need_certificate_arn
  app_vars "$IMAGE" "$1" "$(applied fakecspace_image_uri)"
  # shellcheck disable=SC2046
  tf app apply -input=false $(approve) "${TF_VARS[@]}"
}

status() {
  look
  local url
  echo "Environment: $ENV (account $ACCOUNT_ID, $AWS_REGION); Terraform state in s3://$STATE_BUCKET/bmu/$BMU_ENV_NAME/"
  if [ "$SETTINGS" = ssm ]; then echo "Settings: SSM Parameter Store, $(settings_path)/ (./bmu aws settings show)"
  else echo "Settings: $CONF and $LOCAL"; fi
  if has_pipeline; then
    echo "Deployed by: its pipeline (Actions › Deploy); ./bmu aws deploy here is break-glass"
    [ "$RUNNING" = true ] || echo "RUNNING=false in SSM: the next pipeline run pauses it, or keeps it paused (./bmu aws resume)"
  fi
  IMAGE="$(deployed_image)"
  case "$IMAGE" in ""|*"No outputs"*|*Warning*) echo "Not deployed (./bmu aws deploy)."; return 0 ;; esac
  url="$(app_url)"
  case "$url" in https://*) echo "Address: $url" ;; *) echo "Address: none yet. The last deploy didn't finish; run ./bmu aws deploy again." ;; esac
  echo "Image:   ${IMAGE##*:}"
  if [ "$(applied front_door)" = alb ]; then
    echo "Front door: the load balancer $(applied alb_dns_name), on $(applied domain_name) (Operations' DNS record points there)"
  else
    echo "Front door: CloudFront"
  fi
  local services="web worker"
  [ "$SIMULATED_CSPACE" = false ] || services="web worker fakecspace"
  # shellcheck disable=SC2086
  { aws_ ecs describe-services --cluster "$NAME" --services $services \
      --query "services[].[serviceName, join('', ['running ', to_string(runningCount), ' of ', to_string(desiredCount)])]" --output text 2>/dev/null || true; } |
  while IFS="$(printf '\t')" read -r name counts; do echo "  $name: $counts"; done
  echo "Allowed addresses: $ALLOWED_CIDRS"
  local deployed museum
  deployed="$(applied museums)"   # what was deployed; the settings may have changed since
  echo "Museums, each with its CollectionSpace and its read-only account for interns' checks:"
  for museum in $(museum_names "${deployed:-$MUSEUMS}"); do
    if [ "$SIMULATED_CSPACE" = true ]; then
      echo "  $museum: the simulated CollectionSpace, in the environment ($(server_of "$museum" "${deployed:-$MUSEUMS}"))"
    else
      echo "  $museum: $(server_of "$museum" "${deployed:-$MUSEUMS}")"
    fi
    case "$(reader_secret_field "$museum" 'length(keys(VersionIdsToStages || `{}`))')" in
      "") echo "    read-only account: no secret yet (the next ./bmu aws deploy creates it)" ;;
      0)  echo "    read-only account: NOT SET (./bmu aws reader-secret $museum)" ;;
      *)  echo "    read-only account: set, last changed $(reader_secret_field "$museum" LastChangedDate | cut -c1-10) (change it every 90 days)" ;;
    esac
  done
  # Terraform lists the museums by name; the settings, in any order.
  [ -z "$deployed" ] || [ "$(printf '%s\n' $deployed | sort)" = "$(printf '%s\n' $MUSEUMS | sort)" ] ||
    echo "The settings list other museums or servers: ./bmu aws plan shows the change."
}

# ---- the read-only CollectionSpace account for interns' checks (design: Roles; backend/bmu/reader.py) ----------------
reader_secret_id() { echo "$NAME/cspace-reader/$1"; }  # reader_secret_id MUSEUM: one secret per museum (secrets.tf)

reader_secret_field() {  # reader_secret_field MUSEUM QUERY: one fact about the museum's secret; never reads its value
  aws_ secretsmanager describe-secret --secret-id "$(reader_secret_id "$1")" --query "$2" --output text 2>/dev/null || true
}

json_string() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }  # printf is a builtin: not in the process list

# With the simulator, deploy sets PAHMA's secret once to the simulator's read-only account (bmureader). The simulator
# is the fakecspace package (backend/requirements-sim.in), whose accounts are synthetic and published: each password is
# its user name (the package's README and accounts.py). Nothing else ever writes it: the server never changes.
sim_reader_secret() {
  [ "$(reader_secret_field pahma 'length(keys(VersionIdsToStages || `{}`))')" = 0 ] || return 0
  local user=bmureader
  local password="$user"
  printf '{"username":"%s","password":"%s"}' "$user" "$(json_string "$password")" |
    aws_ secretsmanager put-secret-value --secret-id "$(reader_secret_id pahma)" --secret-string file:///dev/stdin >/dev/null
  echo "The read-only account for interns' checks is the simulator's $user."
}

reader_secret() {  # reader_secret [MUSEUM]: needed when the environment serves several museums
  load_env
  [ "$SIMULATED_CSPACE" = false ] ||
    die "'$ENV' uses the simulated CollectionSpace: ./bmu aws deploy has set the read-only account to the simulator's own."
  local museum="${1:-}" secret user="" password="" again=""
  if [ -z "$museum" ]; then
    [ "$(museum_names | wc -l | tr -d ' ')" = 1 ] ||
      die "Which museum's read-only account? ./bmu aws reader-secret <museum>, one of: $(museum_names | tr '\n' ' ')"
    museum="$(museum_names)"
  fi
  server_of "$museum" >/dev/null || die "'$ENV' doesn't serve a museum '$museum'. Its museums: $(museum_names | tr '\n' ' ')"
  check_account
  secret="$(reader_secret_id "$museum")"
  aws_ secretsmanager describe-secret --secret-id "$secret" >/dev/null 2>&1 ||
    die "No secret $secret yet. ./bmu aws deploy creates it; then run this again."
  echo "$museum's read-only CollectionSpace account on $(server_of "$museum"), which checks interns' drafts (role BMU_Reader, nothing else)."
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
  echo "Check it: sign in to the BMU as one of $museum's interns and open a draft. Its documents are checked against CollectionSpace."
}

logs() {
  load_env
  local svc="${1:-}"
  case "$svc" in web|worker) ;; fakecspace) [ "$SIMULATED_CSPACE" = true ] || die "'$ENV' doesn't run the simulated CollectionSpace." ;;
    *) die "Usage: ./bmu aws logs web|worker|fakecspace" ;; esac
  aws_ logs tail "/bmu/$BMU_ENV_NAME/$svc" --follow --since 30m
}

destroy() {
  load_env
  # Review 5.5: an environment whose data matters is never destroyed by the script; its tables and buckets refuse it
  # anyway, but the destroy would get as far as scheduling its KMS keys (with them, the audit files) for deletion.
  [ "${PROTECT_DATA:-false}" != true ] ||
    die "'$ENV' protects its data (PROTECT_DATA=true), so it can't be destroyed. To destroy it on purpose, set PROTECT_DATA=false in the settings ($CONF or $LOCAL, or, if it keeps them in SSM, ./bmu aws settings set --env $ENV PROTECT_DATA false) and deploy first (that turns off the tables' deletion protection), then destroy."
  prepare
  echo "This deletes the '$ENV' BMU in AWS account $ACCOUNT_ID: its jobs, staged files, audit entries, logs and images."
  echo "Records it created in CollectionSpace stay. The KMS keys are deleted after a 7-day waiting period (aws kms cancel-key-deletion stops it)."
  read -r -p "Type the environment's name ($ENV) to go ahead: " ok
  [ "$ok" = "$ENV" ] || die "Stopped; nothing was deleted."
  tf_init app
  check_front_door   # the variables must describe what was deployed
  IMAGE="$(deployed_image)"
  case "$IMAGE" in ""|*"No outputs"*|*Warning*) IMAGE=none ;; esac
  load_certificate
  [ "$FRONT_DOOR" != alb ] || [ -n "$CERTIFICATE_ARN" ] || CERTIFICATE_ARN="arn:aws:acm:$AWS_REGION:$ACCOUNT_ID:certificate/none"   # set, even to destroy
  [ -n "$ALLOWED_CIDRS" ] || ALLOWED_CIDRS="127.0.0.1/32"   # the variable must be set, even to destroy
  sim_image="$(applied fakecspace_image_uri)"
  [ -n "$sim_image" ] || sim_image=none   # the variable must be set when SIMULATED_CSPACE is true, even to destroy
  deployed="$(applied museums)"
  [ -z "$deployed" ] || MUSEUMS="$deployed"   # the museums whose keys and secrets are in the state
  app_vars "$IMAGE" false "$sim_image"
  if [ "$FRONT_DOOR" = cloudfront ]; then
    echo "Destroying the BMU (about 15-20 minutes: CloudFront is disabled first) ..."
  else
    echo "Destroying the BMU (about 5-10 minutes) ..."
  fi
  # CloudFront removes its VPC origin's network interfaces in the background, which can briefly hold the VPC.
  tf app destroy -input=false -auto-approve "${TF_VARS[@]}" ||
    die "The destroy didn't finish. Wait a few minutes and run ./bmu aws destroy again; Terraform continues where it stopped."
  tf_init registry
  registry_vars
  tf registry destroy -input=false -auto-approve "${REGISTRY_VARS[@]}"
  rm -f "$URL_FILE"
  echo "Done. '$ENV' is gone from AWS (./bmu aws deploy creates it again)."
  [ "$FRONT_DOOR" != alb ] ||
    echo "$DOMAIN_NAME's DNS record now points at nothing: after the next deploy, Operations points it at the new load balancer."
  echo "The Terraform state bucket s3://$STATE_BUCKET is kept; it holds the (now empty) state and its history."
  ! has_pipeline ||
    echo "Its deploy pipeline stays: the account's administrator deletes it with ./bmu aws pipeline destroy --env $ENV."
  [ "$SETTINGS" = files ] ||
    echo "Its settings stay in SSM; once they're no longer needed, the account's administrator runs ./bmu aws settings delete --env $ENV."
}

# ---- the deployer rehearsal ----------------------------------------------------------------------------------------
# A rehearsal deploys the BMU in a developer's own account as a role with only the deployer policy, before Operations
# attaches it in UC Berkeley's account (docs/testing-checklist.md, section 24). What Operations provides there, the VPC
# and that role, comes from deploy/terraform/rehearsal, applied as the account's administrator (ADMIN_PROFILE), never as
# the deployer. The role gets the policy's parts exactly as Operations attaches them (deploy/iam/split-policy.py).
state_has_resources() {  # state_has_resources KEY: whether this environment's KEY.tfstate holds any resource
  aws_ s3 cp "s3://$STATE_BUCKET/bmu/$BMU_ENV_NAME/$1.tfstate" - 2>/dev/null |
    python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("resources") else 1)' 2>/dev/null
}

remove_local() {  # remove_local KEY: take one setting out of the environment's .local.conf (and SSM, SETTINGS=ssm)
  if [ "$SETTINGS" = ssm ] && [ "$CMD" != settings ] && is_ssm_setting "$1"; then put_setting "$1" ""; fi
  [ -f "$LOCAL" ] || return 0
  local tmp; tmp="$(mktemp)"
  grep -v "^$1=" "$LOCAL" > "$tmp" || true
  mv "$tmp" "$LOCAL"
}

rehearsal_vpc() {  # rehearsal_vpc [destroy]
  load_env
  [ "$REHEARSAL" = true ] ||
    die "'$ENV' isn't a rehearsal (REHEARSAL=true in $CONF): in UC Berkeley's account, Operations provides the VPC and the deployer."
  [ "$SIMULATED_CSPACE" = true ] && [ "${PROTECT_DATA:-false}" = false ] ||
    die "A rehearsal uses the simulated CollectionSpace only, with PROTECT_DATA=false ($CONF): no museum data in a personal account."
  [ -n "$ADMIN_PROFILE" ] || die "Set ADMIN_PROFILE in $CONF: the account's administrator profile."
  [ "$ADMIN_PROFILE" != "$DEPLOYER_PROFILE" ] || die "ADMIN_PROFILE and AWS_PROFILE must differ in $CONF: AWS_PROFILE is the deployer."
  local key role parts
  check_account; need_terraform; ensure_state_bucket
  tf_init rehearsal
  parts="$(python3 deploy/iam/split-policy.py --json)" || die "deploy/iam/split-policy.py couldn't split the policy."
  local vars=(-var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "env_name=$BMU_ENV_NAME" -var "policy_parts=$parts")
  case "${1:-}" in
    "") ;;
    destroy)
      for key in app registry; do
        ! state_has_resources "$key" ||
          die "'$ENV' is still deployed (bmu/$BMU_ENV_NAME/$key.tfstate): ./bmu aws destroy --env $ENV first, as the deployer."
      done
      echo "This deletes the rehearsal's VPC, NAT gateway and deployer role in account $ACCOUNT_ID. Terraform asks first."
      # shellcheck disable=SC2046
      tf rehearsal destroy -input=false $(approve) "${vars[@]}"
      for key in VPC_ID APP_SUBNET_IDS LB_SUBNET_IDS; do remove_local "$key"; done
      echo "Done. The [profile $DEPLOYER_PROFILE] section in ~/.aws/config can go too."
      return ;;
    *) die "./bmu aws rehearsal-vpc [destroy]" ;;
  esac
  echo "Terraform shows its plan (a VPC, two public and two private subnets, a NAT gateway, and the deployer role with"
  echo "the policy's parts) and asks."
  # shellcheck disable=SC2046
  tf rehearsal apply -input=false $(approve) "${vars[@]}"
  save_local VPC_ID "$(tf rehearsal output -raw vpc_id)"
  save_local APP_SUBNET_IDS "$(tf rehearsal output -raw app_subnet_ids)"
  save_local LB_SUBNET_IDS "$(tf rehearsal output -raw lb_subnet_ids)"
  echo "Saved VPC_ID, APP_SUBNET_IDS and LB_SUBNET_IDS in $LOCAL."
  role="$(tf rehearsal output -raw deployer_role_arn)"
  if [ "$(aws configure get role_arn --profile "$DEPLOYER_PROFILE" 2>/dev/null || true)" = "$role" ]; then
    echo "The deployer's profile $DEPLOYER_PROFILE is in ~/.aws/config."
  else
    echo
    echo "Add the deployer's profile to ~/.aws/config (it signs in through $ADMIN_PROFILE, then takes the role):"
    echo
    printf '[profile %s]\nrole_arn = %s\nsource_profile = %s\nregion = %s\n' "$DEPLOYER_PROFILE" "$role" "$ADMIN_PROFILE" "$AWS_REGION"
    echo
  fi
  [ "$FRONT_DOOR" != alb ] || [ -n "$DOMAIN_NAME" ] ||
    echo "Set DOMAIN_NAME in $LOCAL: a name in a Route 53 zone of this account, for the certificate (checklist section 24)."
  echo "Next: ./bmu aws deploy --env $ENV   (as the deployer: note every AccessDenied, checklist section 24)"
}

# GitHub's OIDC provider can exist only once in an account (BP9): a root makes it only where its own state already holds
# it, or the account has none. Each list is read whole before it's searched: with pipefail, "terraform state list |
# grep -q" fails when grep stops at its first match while terraform is still writing (SIGPIPE), and a provider the root
# made then looks like the account's own, so Terraform plans to destroy it (Serena's pipeline, November 5, 2026).
# A root never applied has no state yet: terraform state list then fails with "No state file was found!", which means
# the root holds nothing, not that its state can't be read (checklist section 32, step 4).
oidc_provider_create() {  # oidc_provider_create ci|pipeline: prints true or false; Terraform must be initialised
  local state providers
  if ! state="$(tf "$1" state list 2>&1)"; then
    case "$state" in
      *"No state file was found"*) state="" ;;
      *) die "Couldn't read $1's Terraform state (terraform state list) for '$ENV'. Nothing was changed." ;;
    esac
  fi
  if grep -q '^aws_iam_openid_connect_provider\.github' <<<"$state"; then echo true; return 0; fi
  providers="$(aws_ iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[].Arn' --output text)" ||
    die "Couldn't list the account's OIDC providers. Nothing was changed."
  if grep -q 'oidc-provider/token\.actions\.githubusercontent\.com' <<<"$providers"; then echo false; else echo true; fi
}

# The role GitHub Actions assumes to sign in to ECR Public (deploy/terraform/ci): once per account, whichever
# environment's settings pick the account. Uses the account's GitHub OIDC provider if it already has one that this
# state doesn't manage, rather than creating a second (IAM allows one per URL).
CI_REPOSITORY=ets-berkeley-edu/cspace-bulk-media-uploader
ci_role() {
  prepare
  tf ci init -input=false -reconfigure \
    -backend-config="bucket=$STATE_BUCKET" -backend-config="key=bmu/ci/ci.tfstate" \
    -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true" >/dev/null ||
    die "terraform init failed for ci. Run it yourself to see why: terraform -chdir=$TF_DIR/ci init"
  local create
  create="$(oidc_provider_create ci)" || exit 1
  [ "$create" = true ] || echo "The account already has GitHub's OIDC provider: using it."
  # shellcheck disable=SC2046
  tf ci apply -input=false $(approve) -var="account_id=$ACCOUNT_ID" -var="region=$AWS_REGION" \
    -var="create_oidc_provider=$create"
  local arn; arn="$(tf ci output -raw role_arn)"
  echo
  echo "Now set the repository's Actions variable (a variable, not a secret: it isn't committed only because it holds"
  echo "the account number). CI's bmut job then signs in to ECR Public before pulling base images:"
  echo "  gh variable set ECR_PUBLIC_ROLE_ARN --repo $CI_REPOSITORY --body '$arn'"
}

# ---- the deploy pipeline (deploy/terraform/pipeline, deploy/pipeline/, .github/workflows/deploy.yml; design: Deploys) --
# ./bmu aws pipeline makes an environment's pipeline, as the account's administrator; pipeline-plan and pipeline-apply
# are what its builds run, with the build's own role and the settings from SSM, asking nothing. Modelled on Serena's.
PIPELINE_REPO="$CI_REPOSITORY"

has_pipeline() { state_has_resources pipeline; }  # whether ./bmu aws pipeline made this environment's pipeline

# UC Berkeley data only in UC Berkeley accounts (BP7): the build can't ask, so for an environment with a real
# CollectionSpace it needs the account an administrator typed at ./bmu aws pipeline, saved in SSM where the build can't
# change it.
need_real_data_confirmed() {
  [ "$SIMULATED_CSPACE" != true ] || return 0
  [ -n "$REAL_DATA_ACCOUNT" ] && [ "$REAL_DATA_ACCOUNT" = "$ACCOUNT_ID" ] ||
    die "'$ENV' uses a real CollectionSpace, and no administrator has confirmed that its account is UC Berkeley's
(./bmu aws pipeline --env $ENV asks). UC Berkeley data goes only in UC Berkeley accounts. Stopped."
}

result() {  # result NAME VALUE: one of the build's exported variables (the buildspec reads $PIPELINE_RESULT)
  printf '%s=%q\n' "$1" "$2" >> "$PIPELINE_RESULT"
}

plan_counts() {  # plan_counts PART PLANFILE: what the saved plan does, as Terraform counts it
  tf "$1" show -json "$2" | python3 -c '
import json, sys
count = {"create": 0, "update": 0, "delete": 0}
for change in json.load(sys.stdin).get("resource_changes", []):
    for action in change["change"]["actions"]:
        if action in count:
            count[action] += 1
print("%(create)d to add, %(update)d to change, %(delete)d to destroy" % count)'
}

push_image() {  # push_image IMAGE DOCKER-BUILD-ARGUMENTS...: built and pushed, unless the image is already there
  local image="$1" repo
  shift
  repo="${image#*/}"; repo="${repo%%:*}"
  if aws_ ecr describe-images --repository-name "$repo" --image-ids "imageTag=${image##*:}" >/dev/null 2>&1; then
    echo "$image is already pushed."
    return 0
  fi
  docker build --pull --platform linux/arm64 -t "$image" "$@"
  docker push "$image"
}

# The plan build: the images (tagged with the commit), then the registry's plan and the app's, their text in this
# build's log and the files in the bucket of saved plans. Exported for the workflow: PLAN_STATUS (changes, no-changes,
# registry-only or certificate-pending), the counts, and any museum the plan removes.
pipeline_plan() {
  load_env; check_account; need_terraform; need_real_data_confirmed
  : "${PIPELINE_PLANS:?the bucket of saved plans}" "${PIPELINE_RESULT:?}"
  ensure_state_bucket
  local commit id dir code repo image sim_image=""
  commit="$(git rev-parse HEAD)" id="${CODEBUILD_BUILD_ID##*:}" dir="$(mktemp -d)"
  : > "$PIPELINE_RESULT"
  result PLAN_ID "$id"; result REGISTRY_CHANGES "no changes"; result ROOT_CHANGES ""; result REMOVED_MUSEUMS ""

  echo "== The registry: image repositories and the certificate"
  registry_vars; tf_init registry
  code=0
  tf registry plan -input=false -detailed-exitcode -out="$dir/registry.tfplan" "${REGISTRY_VARS[@]}" || code=$?
  case "$code" in 0) rm -f "$dir/registry.tfplan" ;; 2) ;; *) die "The registry's plan failed (above)." ;; esac
  if [ "$code" = 2 ]; then
    result REGISTRY_CHANGES "$(plan_counts registry "$dir/registry.tfplan")"
    echo "The registry has changes. This run applies only them, since the app's plan depends on them: run the deploy"
    echo "again afterwards."
    save_plan "$dir" "$commit" "$id" registry-only
    return 0
  fi
  load_certificate
  if [ "$FRONT_DOOR" = alb ] && ! certificate_issued; then
    echo "Run the deploy again once the record is in DNS and the certificate is ISSUED."
    result PLAN_STATUS certificate-pending
    return 0
  fi

  echo "== The images, tagged with the commit (linux/arm64)"
  repo="$(tf registry output -raw repository_url)"
  image="$repo:${commit:0:12}"
  # The registry's short-lived token goes straight from the AWS CLI to Docker; it is never shown or saved.
  aws_ ecr get-login-password | docker login --username AWS --password-stdin "${repo%%/*}" >/dev/null
  push_image "$image" -f deploy/Dockerfile .
  if [ "$SIMULATED_CSPACE" = true ]; then
    sim_image="$(tf registry output -raw fakecspace_repository_url):${commit:0:12}"
    push_image "$sim_image" -f deploy/fakecspace.Dockerfile .
  fi

  echo "== The BMU: the plan the reviewer reads"
  tf_init app; check_front_door; check_museums build
  result REMOVED_MUSEUMS "$REMOVED_MUSEUMS"
  app_vars "$image" "$RUNNING" "$sim_image"
  code=0
  tf app plan -input=false -detailed-exitcode -out="$dir/root.tfplan" "${TF_VARS[@]}" || code=$?
  case "$code" in
    0) result ROOT_CHANGES "no changes"; result PLAN_STATUS no-changes
       echo "No changes: '$ENV' matches this commit." ;;
    2) result ROOT_CHANGES "$(plan_counts app "$dir/root.tfplan")"
       save_plan "$dir" "$commit" "$id" changes ;;
    *) die "The plan failed (above)." ;;
  esac
}

save_plan() {  # save_plan DIR COMMIT ID STATUS: the plan files and what they are, in the bucket of saved plans
  COMMIT="$2" ENVIRONMENT="$ENV" STATUS="$4" python3 -c '
import json, os, time
print(json.dumps({"commit": os.environ["COMMIT"], "environment": os.environ["ENVIRONMENT"],
                  "status": os.environ["STATUS"], "made": int(time.time())}))' > "$1/plan.json"
  aws_ s3 cp --recursive --only-show-errors "$1/" "s3://$PIPELINE_PLANS/plans/$3/"
  result PLAN_STATUS "$4"
  echo "Saved as plan $3. The reviewer reads it above, then approves the deploy in GitHub."
}

# The apply build: exactly the saved plans of PLAN_ID (the workflow passes the plan build's), for this commit and
# environment, at most 24 hours old. Terraform itself refuses a plan made against a state that has changed since.
pipeline_apply() {
  load_env; check_account; need_terraform; need_real_data_confirmed
  : "${PIPELINE_PLANS:?the bucket of saved plans}" "${PIPELINE_RESULT:?}" "${PLAN_ID:?PLAN_ID, from the plan build}"
  case "$PLAN_ID" in ""|*[!0-9a-f-]*) die "PLAN_ID isn't a plan build's ID." ;; esac
  local dir status museum
  dir="$(mktemp -d)"
  : > "$PIPELINE_RESULT"
  aws_ s3 cp --recursive --only-show-errors "s3://$PIPELINE_PLANS/plans/$PLAN_ID/" "$dir/"
  [ -f "$dir/plan.json" ] || die "No saved plan $PLAN_ID (plans are kept 7 days). Run the deploy again."
  status="$(COMMIT="$(git rev-parse HEAD)" ENVIRONMENT="$ENV" python3 -c '
import json, os, sys, time
plan = json.load(open(sys.argv[1]))
if plan["commit"] != os.environ["COMMIT"]:
    sys.exit("Plan %s is of commit %s, not this one: run the deploy again." % (sys.argv[2], plan["commit"]))
if plan["environment"] != os.environ["ENVIRONMENT"]:
    sys.exit("Plan %s is for %s, not this environment." % (sys.argv[2], plan["environment"]))
if time.time() - plan["made"] > 24 * 3600:
    sys.exit("Plan %s is more than 24 hours old: run the deploy again." % sys.argv[2])
print(plan["status"])' "$dir/plan.json" "$PLAN_ID")" || exit 1
  if [ -f "$dir/registry.tfplan" ]; then
    echo "== The registry"
    tf_init registry
    tf registry apply -input=false "$dir/registry.tfplan"
  fi
  if [ "$status" = registry-only ]; then
    result APPLY_STATUS registry-only
    echo "The registry is applied. Run the deploy again for the rest."
    return 0
  fi
  [ "$status" = changes ] && [ -f "$dir/root.tfplan" ] || die "Plan $PLAN_ID has nothing to apply ($status)."
  echo "== The BMU. It finishes when the web app and the worker are running."
  tf_init app
  tf app apply -input=false "$dir/root.tfplan"
  result APPLY_STATUS applied
  echo "$ENV_LABEL is deployed at commit $(git rev-parse --short HEAD): $(app_url)"
  # The build's address isn't one the load balancer admits, so it can't check /api/health as a deploy from a laptop does.
  [ "$FRONT_DOOR" != alb ] ||
    echo "DNS: $DOMAIN_NAME must point at the load balancer $(applied alb_dns_name) (Operations' record)."
  # What only an administrator can do (BP10): the build can't read or set a secret's value.
  for museum in $(museum_names); do
    [ "$(reader_secret_field "$museum" 'length(keys(VersionIdsToStages || `{}`))')" = 0 ] || continue
    if [ "$SIMULATED_CSPACE" = true ]; then echo "Next: ./bmu aws sim-secrets --env $ENV"; break; fi
    echo "Next: ./bmu aws reader-secret $museum --env $ENV"
  done
}

gh_get() {  # gh_get PATH: a GitHub API read, signed in with gh if it's there, otherwise anonymously; empty on failure
  if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    gh api "$1" 2>/dev/null || true
  else
    curl -fsS -H "Accept: application/vnd.github+json" "https://api.github.com/$1" 2>/dev/null || true
  fi
}

# The GitHub environments must exist, with their rules, before the roles that trust them (BP8): GitHub makes an
# environment without rules the first time a job names it.
check_github_environments() {
  local name json branches problems="" problem
  for name in "$ENV-plan" "$ENV"; do
    json="$(gh_get "repos/$PIPELINE_REPO/environments/$name")"
    if [ -z "$json" ]; then problems="$problems
  $name: not found"; continue; fi
    branches="$(gh_get "repos/$PIPELINE_REPO/environments/$name/deployment-branch-policies")"
    [ -n "$branches" ] || branches='{}'
    problem="$(NAME="$name" ENVIRONMENT="$ENV" REAL="$([ "$SIMULATED_CSPACE" = true ] && echo false || echo true)" \
      ALLOW="$ALLOW_SELF_REVIEW" CONF="$CONF" BRANCHES="$branches" python3 -c '
import json, os, sys
env, branches = json.load(sys.stdin), json.loads(os.environ["BRANCHES"])
policy = env.get("deployment_branch_policy") or {}
names = [(b.get("name"), b.get("type", "branch")) for b in branches.get("branch_policies", [])]
problems = []
if not policy.get("custom_branch_policies") or names != [("main", "branch")]:
    problems.append("deployments from main only (Deployment branches and tags: main)")
reviewers = [r for r in env.get("protection_rules", []) if r.get("type") == "required_reviewers"]
if os.environ["NAME"] == os.environ["ENVIRONMENT"]:
    if not reviewers or not reviewers[0].get("reviewers"):
        problems.append("a required reviewer")
    elif not reviewers[0].get("prevent_self_review"):
        if os.environ["ALLOW"] == "true":
            print("note: self-review is allowed (ALLOW_SELF_REVIEW=true in " + os.environ["CONF"]
                  + "; BP8: QA and dev only)", file=sys.stderr)
        elif os.environ["REAL"] == "true":
            problems.append("Prevent self-review (it has UC Berkeley data; BP8 allows it only with ALLOW_SELF_REVIEW=true)")
        else:
            print("note: self-review is allowed (an environment with the simulated CollectionSpace)", file=sys.stderr)
print("; ".join(problems))' <<<"$json")"
    [ -z "$problem" ] || problems="$problems
  $name needs: $problem"
  done
  [ -z "$problems" ] && return 0
  die "The GitHub environments aren't ready (repository Settings › Environments; deploy/README.md, The deploy pipeline):$problems
Set them up first: the pipeline's roles trust them. Nothing was changed."
}

# The roles trust only tokens whose sub claim is "<this>:environment:<name>". GitHub's settings for the repository
# decide how it begins: repo:<owner>/<name>, or, with immutable subjects, the owner's and repository's IDs too
# (repo:<owner>@<id>/<name>@<id>), which a repository made again under the same name doesn't have.
github_subject() {
  local subject
  subject="$(gh_get "repos/$PIPELINE_REPO/actions/oidc/customization/sub" | REPO="$PIPELINE_REPO" python3 -c '
import json, os, sys
try:
    sub = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
if sub.get("use_default", True):
    print(sub.get("sub_claim_prefix") or "repo:" + os.environ["REPO"])' 2>/dev/null || true)"
  case "$subject" in
    repo:*) echo "$subject" ;;
    *) die "Couldn't read how GitHub's OIDC tokens name $PIPELINE_REPO
(repos/$PIPELINE_REPO/actions/oidc/customization/sub): gh must be signed in as an admin of the repository.
If the repository uses its own claim keys (use_default false), the pipeline's roles don't support it.
Nothing was changed." ;;
  esac
}

confirm_real_data_account() {  # for an environment with a real CollectionSpace: the account typed, and saved for the build
  [ "$SIMULATED_CSPACE" != true ] || return 0
  acknowledge_real_data
  put_setting REAL_DATA_ACCOUNT "$ACCOUNT_ID"
}

set_github_secrets() {  # the roles' ARNs as the GitHub environments' AWS_ROLE_ARN, and the region as AWS_REGION
  local mode env ok=""
  echo
  echo "The deploy workflow signs in with these roles: each GitHub environment needs its role's ARN as the secret"
  echo "AWS_ROLE_ARN (a secret, so the account number is masked in the logs) and the region as the variable AWS_REGION."
  if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    # Ends in ": " so that it shows through tfsummary, which passes on only prompts that do.
    read -r -p "Set them now with gh, signed in as you? Type y or n: " ok || ok=""
  fi
  for mode in plan apply; do
    env="$ENV"; [ "$mode" = apply ] || env="$ENV-plan"
    case "$ok" in
      y|Y|yes)
        tf pipeline output -raw "${mode}_role_arn" | gh secret set AWS_ROLE_ARN --repo "$PIPELINE_REPO" --env "$env"
        gh variable set AWS_REGION --repo "$PIPELINE_REPO" --env "$env" --body "$AWS_REGION" ;;
      *)
        echo "  terraform -chdir=deploy/terraform/pipeline output -raw ${mode}_role_arn |"
        echo "    gh secret set AWS_ROLE_ARN --repo $PIPELINE_REPO --env $env"
        echo "  gh variable set AWS_REGION --repo $PIPELINE_REPO --env $env --body $AWS_REGION" ;;
    esac
  done
}

pipeline_root() {  # pipeline_root [destroy]
  load_env
  [ "$SETTINGS" = ssm ] ||
    die "The pipeline reads the settings of '$ENV' from SSM (BP4): add SETTINGS=ssm to $LOCAL, then
./bmu aws settings push --env $ENV"
  check_account; need_terraform; ensure_state_bucket
  tf_init pipeline
  local create subject parts
  create="$(oidc_provider_create pipeline)" || exit 1
  # Deleting needs no answer from GitHub: any subject will do.
  if [ "${1:-}" = destroy ]; then subject="repo:$PIPELINE_REPO"; else subject="$(github_subject)" || exit 1; fi
  parts="$(python3 deploy/iam/split-policy.py --json)" || die "deploy/iam/split-policy.py couldn't split the policy."
  local vars=(-var "account_id=$ACCOUNT_ID" -var "region=$AWS_REGION" -var "environment=$ENV" -var "env_name=$BMU_ENV_NAME"
              -var "create_oidc_provider=$create" -var "github_subject=$subject" -var "policy_parts=$parts"
              -var "simulated_cspace=$SIMULATED_CSPACE")
  case "${1:-}" in
    "") ;;
    destroy)
      echo "This deletes the deploy pipeline of '$ENV' in account $ACCOUNT_ID: the roles GitHub Actions assumes,"
      echo "the CodeBuild projects and their role, the saved plans and the builds' logs. The environment stays."
      [ "$create" = false ] || echo "It also deletes GitHub's OIDC provider, which this pipeline made: if anything else"
      [ "$create" = false ] || echo "in the account uses it (CI's ECR Public role, another app's pipeline), answer no."
      # shellcheck disable=SC2046
      tf pipeline destroy -input=false $(approve) "${vars[@]}"
      echo "Done. Delete the GitHub environments $ENV-plan and $ENV too."
      return ;;
    *) die "./bmu aws pipeline [destroy]" ;;
  esac
  check_github_environments
  confirm_real_data_account
  echo "The roles trust GitHub's tokens for $subject:environment:$ENV-plan and :$ENV."
  if [ "$create" = true ]; then echo "GitHub's OIDC provider: this pipeline makes (or keeps) it."
  else echo "GitHub's OIDC provider: the account's own (this pipeline doesn't make another)."
  fi
  echo "Terraform shows its plan (the OIDC roles, the CodeBuild projects, their role and policies, a log group and the"
  echo "bucket of saved plans) and asks."
  # shellcheck disable=SC2046
  tf pipeline apply -input=false $(approve) "${vars[@]}"
  set_github_secrets
  echo
  echo "Next: Actions › Deploy › Run workflow, from main, with the environment $ENV. From now on the pipeline deploys"
  echo "'$ENV'; ./bmu aws deploy here is break-glass."
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
  pause) pause_resume false ;;
  resume) pause_resume true ;;
  allow-my-ip)
    load_env
    ip="$(my_ip)/32"
    case ",$ALLOWED_CIDRS," in *",$ip,"*) echo "$ip is already allowed." ; exit 0 ;; esac
    new="${ALLOWED_CIDRS:+$ALLOWED_CIDRS,}$ip"
    # The deployer can't change a setting in SSM: the administrator (or SETTINGS_PROFILE) sets it (BP4, BP6).
    [ "$SETTINGS" = files ] ||
      die "'$ENV' keeps its settings in SSM. To allow $ip, the account's administrator (or SETTINGS_PROFILE) runs ./bmu aws settings set --env $ENV ALLOWED_CIDRS \"$new\", and the next deploy applies it."
    save_local ALLOWED_CIDRS "$new"; ALLOWED_CIDRS="$new"
    echo "Allowed: $new"
    prepare; tf_init app
    case "$(deployed_image)" in ""|*"No outputs"*|*Warning*) echo "Saved; it applies at the first deploy." ;; *) reapply "$(was_running)" ;; esac ;;
  init) prepare; tf registry init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="key=bmu/$BMU_ENV_NAME/registry.tfstate" -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true"
        tf app init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="key=bmu/$BMU_ENV_NAME/app.tfstate" -backend-config="region=$AWS_REGION" -backend-config="use_lockfile=true" ;;
  reader-secret) reader_secret "${1:-}" ;;
  ci-role) ci_role ;;
  rehearsal-vpc) rehearsal_vpc "${1:-}" ;;
  settings) settings "$@" ;;
  pipeline) pipeline_root "${1:-}" ;;
  pipeline-plan) pipeline_plan ;;
  pipeline-apply) pipeline_apply ;;
  sim-secrets)
    load_env
    [ "$SIMULATED_CSPACE" = true ] ||
      die "'$ENV' uses a real CollectionSpace: its read-only accounts are set with ./bmu aws reader-secret."
    check_account; need_terraform; tf_init app; need_deployed
    sim_reader_secret
    echo "Done: the simulator's read-only account is set (nothing is shown)." ;;
  destroy) destroy ;;
  help|-h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" ;;
  *) die "Unknown command '$CMD'. ./bmu aws help lists them." ;;
esac
