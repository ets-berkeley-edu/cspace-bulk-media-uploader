# The BMU in AWS

`./bmu aws` deploys the BMU to an AWS account and looks after it. The deployment is the same app as the local
prototype: the image is built from this repository and runs on ECS Fargate. Demo tools are always off.

- **One environment per account.** Each environment has a settings file in `deploy/environments/`.
  - `personal-dev.conf` is Richard's personal account and the default.
  - `ucb-dev.conf` is the UC Berkeley account. It is ready to fill in but not set up yet.
- **Infrastructure as code.** Everything is created by Terraform (`deploy/terraform/`), so nothing has to be
  clicked together in the console, and the whole environment can be deleted and created again.
- **No keys or passwords in files.** You sign in with IAM Identity Center (`aws sso login`). The app's own
  secrets are KMS keys that never leave AWS.

## Commands

| Command | What it does |
| --- | --- |
| `./bmu aws deploy` | Builds the image and pushes it, then shows Terraform's plan and, after you type `yes`, applies it and waits until the app is up. Prints the address and saves it for `./bmu open aws`. |
| `./bmu aws plan` | Shows what a deploy of the running image would change, without changing anything. |
| `./bmu aws status` | Shows the address, the running tasks, the deployed image and the allowed addresses. |
| `./bmu aws url` | Prints the address. |
| `./bmu aws logs web` / `worker` | Follows a service's logs, starting with the last 30 minutes. |
| `./bmu aws pause` / `resume` | Stops or starts both services to save money. The data stays. Terraform shows the change and asks first. |
| `./bmu aws allow-my-ip` | Adds this computer's current address to the allowlist, and applies it. |
| `./bmu aws destroy` | Deletes everything in AWS for the environment, data included. It asks for the environment's name first. |

**Picking the environment.** Add `--env NAME`, or set `BMU_AWS_ENV`. The default is `personal-dev`.

**Skipping the question.** `BMU_AWS_YES=1` applies without Terraform's `yes` prompt.

## First deploy

**What you need on the Mac**
- Docker Desktop, running.
- AWS CLI v2.
- Terraform 1.10 or later: `brew tap hashicorp/tap && brew install hashicorp/tap/terraform`.
- A signed-in profile: `aws sso login --profile bmu-personal`. The sign-in lasts 8 hours.

**Then run** `./bmu aws deploy`.

1. **Account check.** It shows the AWS account the profile is signed in to and asks whether that's the right
   one. It saves your answer in `deploy/environments/personal-dev.local.conf`, which isn't committed, and from
   then on refuses to deploy to any other account.
2. **Allowlist.** It adds this computer's public address to the allowlist, in the same file. Everyone else gets
   a 403 from CloudFront.
3. **State bucket.** It creates the bucket that holds Terraform's state, once per account (see Terraform
   below).
4. **Image repository.** It creates the image repository, which takes about a minute.
5. **Image.** It builds the image for ARM (Graviton) and pushes it. The Docker login token goes straight from
   the AWS CLI to Docker.
6. **The BMU.** Terraform lists the 66 resources it will create and asks; type `yes`. The first time takes
   about **15–25 minutes**, mostly CloudFront. It finishes when the web app and the worker are running, then
   prints the address (`https://<something>.cloudfront.net`).

**Signing in.** Sign in with your PAHMA QA account. Jobs create real records on the QA tenant, and they stay.

**Later deploys.** Run the same command. Terraform shows only what changed, which takes about 3–5 minutes. Each
deploy pushes a new image tag (commit and time), so `./bmu aws status` shows which code is running.

## What it creates

**`deploy/terraform/registry`**
- The image repository. It keeps the 10 newest images, scanned on push.

**`deploy/terraform/app`, all in one region**

| Piece | Details |
| --- | --- |
| Network | A VPC with two public subnets (the tasks) and two private subnets (the load balancer). No NAT gateway: the tasks have public IPs for outbound HTTPS to CollectionSpace and AWS, and nothing can connect in. S3 and DynamoDB traffic stays inside AWS through free gateway endpoints. |
| CloudFront | The HTTPS address (`*.cloudfront.net`). It forwards to an **internal** load balancer through a VPC origin, so the hop to the load balancer never crosses the internet. A CloudFront Function lets in only the allowed IPv4 addresses. Error answers are never cached. Built app files under `/assets/` are cached. |
| Load balancer | Internal; health check `/api/health`. |
| ECS Fargate | Cluster `bmu-<env>` with two services. Both run on ARM. The tasks are replaced one by one on deploy and rolled back automatically if they don't start. |
| DynamoDB | `bmu-<env>-jobs`, `-sessions`, `-credentials` and `-audit`: the same keys, index and TTL as the local tables (a test checks this). Point-in-time recovery is on for jobs and audit, and off for the two tables that hold encrypted passwords. |
| S3 | Staging bucket `bmu-<env>-staging-<account>-<region>`: SSE-KMS with its own key, versioning, all public access blocked, TLS only, KMS-encrypted uploads only, and CORS for the BMU's address only. The BMU deletes every version of a staged file; a rule removes any version left behind after a day. Audit files (`audit/`) keep their versions for a year. Access logs go to `bmu-<env>-s3-logs-…`, kept 90 days. |
| KMS | Three keys: session, job and staging. Rotation is on. See the key policies below. |
| IAM | Separate roles for the web app and the worker, each with only what its code uses. The web app can save and delete a job's sign-in but not read it; the worker can read and delete it. Only the web app adds staged files; both can read and delete them (the web app makes the TIFF thumbnails). Both can add audit entries and audit files, and neither can read, change or delete them. The worker role has no access to the session key and can only decrypt with the job key. |
| CloudWatch Logs | `/bmu/<env>/web` and `/bmu/<env>/worker`, kept 30 days. |

**The two services**
- **`web`**: 0.25 vCPU and 1 GB. Runs uvicorn on port 8000 and serves the built Vue app with the API.
- **`worker`**: 0.5 vCPU and 2 GB. Runs `python -m bmu.worker`. One at a time: the old task stops before the
  new one starts.

**Key policies** (design: Envelope encryption)
- The session key: `GenerateDataKey` and `Decrypt` for the web role.
- The job key: `GenerateDataKey` for the web role and `Decrypt` for the worker role.
- Both are limited to the matching `purpose` in the encryption context.
- The account can manage these two keys and delete them, but can't use them or grant their use.
  An administrator can't decrypt a saved password without first changing the key policy, which CloudTrail
  records.

**Tags.** Every resource is tagged `project=bmu` and `environment=<env>`, so Cost Explorer can show the BMU's
costs.

## Terraform

- **Two configurations.** `registry` (the image repository) and `app` (everything else). The image has to be
  pushed between them, so they are applied in turn.
- **Versions.** Terraform 1.10 or later and the AWS provider 6.x. `.terraform.lock.hcl` in each folder pins the
  exact provider version (6.67.0 now) for Macs and Linux.
- **State.** Terraform's record of what it created lives in S3, in the same account:
  `s3://bmu-tfstate-<account>-<region>/bmu/<env>/registry.tfstate` and `app.tfstate`. The bucket is versioned
  and private, and a lock file beside the state stops two applies at once. `./bmu aws` creates the bucket and
  passes these settings to `terraform init`, so nothing account-specific is in the code.
- **One account only.** Each configuration is told the environment's account number and refuses to run against
  any other. `./bmu aws` also ignores access keys left in the shell, so only the profile's sign-in is used.
- **Settings.** `./bmu aws` passes the environment's settings (`deploy/environments/`) as variables;
  `app/variables.tf` lists them. `protect_data = true` (set `PROTECT_DATA=true` in the settings file) is for an
  environment whose data matters: tables can't be deleted, and `destroy` won't empty the buckets.
- **Running Terraform yourself.** `./bmu aws init` initializes both folders against the environment's state.
  After that, `terraform -chdir=deploy/terraform/app state list` and other read-only commands work as usual,
  with `AWS_PROFILE` set. For changes, use `./bmu aws deploy`, which supplies the variables.

## Cost

These are rough us-west-2 prices.

| State | Cost | Main items |
| --- | --- | --- |
| Running | About **$1.75 a day** (about $50 a month) | The load balancer (about $16 a month), the worker (about $17), the web app (about $9), two public IPv4 addresses (about $7) and the KMS keys ($3). CloudFront, DynamoDB, S3 and the logs cost cents at test volumes. |
| Paused | About **$0.65 a day** | The load balancer and the KMS keys still bill. |
| Destroyed | Nothing | — |

The `bmu-monthly` budget ($25), which you created in the Billing console when setting up the account, emails you
if a month heads past it. Pause or destroy the environment between test sessions.

## Moving to another account (UC Berkeley)

Nothing in the Terraform code names an account.

1. **Sign-in.** Set up an IAM Identity Center sign-in for the new account (`aws configure sso`) with the profile
   name in `ucb-dev.conf`.
2. **Settings.** Check the region and the label in `ucb-dev.conf`.
3. **Deploy.** Run `./bmu aws deploy --env ucb-dev`. Everything is created fresh there: its own state bucket,
   new keys, new tables and a new address. No state is moved between accounts.

The personal environment is unaffected; `./bmu aws destroy --env personal-dev` removes it when you're done with
it.

If the UCB account requires a custom domain, a different network layout, existing VPCs or a shared state
bucket, those become variables in `app/variables.tf` or settings in `deploy/aws.sh`.

## Checking the Terraform code

Neither of the first two needs an AWS sign-in.

- **`terraform validate`.** In each folder: `terraform init -backend=false && terraform validate`. It checks
  every resource and argument against the provider.
- **`terraform test`.** In `deploy/terraform/app`. It plans against a simulated AWS provider and checks names,
  the paused state, the allowlist, data protection and that bad input is refused
  (`tests/app.tftest.hcl`).
- **App checks.** `backend/tests/test_deploy.py` checks that the Terraform code matches the app: tables,
  settings, Demo tools off, key policies, and the production build in the image.
- **`./bmu aws plan`.** Against the real account: what a deploy would change.

## Not in this first round (design: Prototype plan)

- **No SQS.** The worker polls DynamoDB, as it does locally.
- **No thumbnail Lambda.** The web app makes TIFF thumbnails, as in the prototype, so its role can read staged
  files.
- **No custom domain.** No custom domain or certificate.
- **No Object Lock or CloudTrail for the audit files.** The roles can't delete them, and their versions are kept
  for a year, but an administrator still can. Object Lock and CloudTrail data events come with the UC Berkeley
  account: Object Lock would stop `./bmu aws destroy` from emptying a test account's bucket.
- **60-second requests.** CloudFront waits at most 60 seconds for an answer (more needs a quota increase). A
  request that waits longer on CollectionSpace, such as a sign-in while the QA server is slow, shows an error,
  though the app finishes it.
- **No graceful worker stop.** A deploy or pause stops the worker immediately. A job that was running is ended
  by the periodic check as "worker stopped" and can be fixed and rescheduled. Deploy between runs.

## If something goes wrong

- **"Not signed in to AWS".** Run `aws sso login --profile <profile>`.
- **The first creation fails.** Terraform stops at the resource that failed, says why, and keeps what it
  already created.
  - Running `./bmu aws deploy` again continues from there.
  - Brand-new accounts sometimes fail once while AWS creates the ECS or load-balancer service roles; the
    second try works.
  - CloudFront can also refuse new distributions until AWS has verified a new account. AWS Support resolves
    that.
- **403 "open only to listed addresses".** Your address changed: run `./bmu aws allow-my-ip`.
- **`destroy` stops at the VPC.** CloudFront removes its VPC origin's network interfaces in the background, and
  the VPC can't be deleted until they're gone. Run `./bmu aws destroy` again a few minutes later; Terraform
  continues where it stopped.
- **"Error acquiring the state lock".** An earlier run was interrupted. Check that no other deploy is running,
  then `terraform -chdir=deploy/terraform/app force-unlock <the lock ID in the message>`.
- **The app doesn't come up.** Run `./bmu aws logs web` or `./bmu aws logs worker`, and `./bmu aws status`.
