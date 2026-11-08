# The deployer's permissions (for Operations)

The IAM policy the person running `./bmu aws` (Terraform included) needs in a UC Berkeley AWS account, for a dev/QA
deployment of the BMU in an existing VPC (`../README.md`, "Deploying into an existing VPC") with the simulated
CollectionSpace: no museum data and no CollectionSpace credentials. Nothing here is secret: no account numbers,
network IDs, addresses or keys. Account IDs are wildcards (`*`), and every write is limited to resources named
`bmu-*` (log groups `/bmu/*`) or tagged `project=bmu` wherever AWS allows it. Terraform tags everything it creates
`project=bmu` (its default tags).

| File | What |
| --- | --- |
| `bmu-deployer-policy.json` | The whole policy: the only copy, reviewed with the Terraform it permits. About 13,200 characters without whitespace |
| `split-policy.py` | Splits it into the customer managed policies to attach (below) |

## The ask

Create an IAM role **`rtl-BmuDeployer`**, with the same trust as `rtl-SerenaStage2Deployer` (assumed from the
deployer's IAM Identity Center session; 1-hour sessions), and attach the policy's parts as customer managed policies.
It is a new, separate policy, modelled on Serena's stage 2 deployer policy, which doesn't change.

**The parts.** A role's inline policies hold at most 10,240 characters and a customer managed policy at most 6,144
(whitespace not counted), so the policy goes in as three managed policies. They are made from
`bmu-deployer-policy.json` each time, never stored:

```bash
python3 deploy/iam/split-policy.py
```

It writes `deploy/iam/out/bmu-deployer-policy-part1.json` to `-part3.json` (not committed), split between whole
statements, each part starting with the same region Deny, so that no part on its own allows anything outside
us-west-2. `--check` only checks that it fits; `backend/tests/test_deploy.py` checks the same in CI.

**Don't name the role `bmu-…`.** The policy lets the deployer create and change `bmu-*` roles (the web app's, the
worker's and the tasks' execution role), so a role with such a name could change its own permissions.

## How it was made

From Serena's stage 2 deployer policy (`ets-berkeley-edu/cspace-media-server`, `deploy/iam/serena-deployer-policy.json`):

- `serena` replaced by `bmu`; the Terraform state bucket is `bmu-tfstate-*`.
- **Removed**, because the BMU doesn't use them: the regional WAF and its logs, ACM certificates, the load balancer's
  web ACL, alarms (CloudWatch and SNS), SSM parameters, and the ETL token secrets' resource policies, with the reads
  for SNS, SSM, WAF and ACM.
- **Added**, because the BMU's architecture differs: CloudFront reaches an **internal** load balancer through a
  **VPC origin** (`CloudFrontVpcOrigin`, `CloudFrontVpcOriginTags`, and `vpcorigin.cloudfront.amazonaws.com` among
  the service-linked roles), and the staging bucket takes uploads straight from the browser (`s3:PutBucketCORS`) and
  logs its access to a second `bmu-*` bucket (`s3:PutBucketLogging`).

Like Serena's stage 2 policy, it can't create or change a VPC, subnets, routes or gateways. In the existing VPC it
can create security groups and their rules, and the S3 and DynamoDB gateway endpoints (only when
`CREATE_GATEWAY_ENDPOINTS=true`), all tagged `project=bmu`.

## Where it can't be narrower

- CloudFront functions' tags are limited by name, but creating functions and response headers policies, and VPC
  origins, needs `Resource: "*"`: they are identified by generated IDs. Distributions are limited by their
  `project=bmu` tag.
- Security groups, their rules and gateway endpoints have generated IDs too; they are limited by tag, and can be
  created in any VPC (the VPC is Operations', so it can't carry the BMU's tag).
- ECS task definitions and KMS key creation have no name-based resource to scope to (keys are limited by tag
  afterwards; their aliases by name).
- The simulated CollectionSpace's private DNS name (Cloud Map, `SimulatorOnlyServiceDiscovery`) is created with the
  deployer's own Route 53 permissions, on hosted zones with generated IDs, so `Resource: "*"`; Route 53 refuses to
  delete a hosted zone that still has records. Without the simulator these permissions aren't used.
- Read-only `Describe`, `Get` and `List` calls are allowed account-wide: Terraform reads many attributes of each
  resource, the exact list changes with provider versions, and they return only metadata.
- `iam:PassRole` is limited to `bmu-*` roles and to ECS tasks; the only managed policy that can be attached is
  `AmazonECSTaskExecutionRolePolicy`.
- The deployer can read and write the BMU's own secrets (`bmu-*`): `./bmu aws` sets them without showing or storing
  them. The KMS key policies keep the deployer from using the BMU's keys to read saved passwords or staged files
  (`../README.md`, Key policies).

## Not covered

- **The WAF.** The BMU's WAF is CloudFront-scoped, which AWS keeps in us-east-1; the region Deny blocks it, and the
  policy has no WAF permissions. A dev/QA environment runs without it (`WAF_ENABLED=false`, the default without
  `PROTECT_DATA`). It comes with production.
- **`./bmu aws ci-role`** (CI's ECR Public role and the GitHub OIDC provider) isn't for this role.
- **A deploy pipeline** (GitHub OIDC and CodeBuild), as for Serena: later.
- The role can't list its own policies (its IAM reads are limited to `bmu-*` roles). That's expected.

## Also needed from Operations, outside the policy

- **Service-linked roles.** If guardrails stop the deployer creating them: `AWSServiceRoleForECS`,
  `AWSServiceRoleForElasticLoadBalancing` and CloudFront's for VPC origins (`vpcorigin.cloudfront.amazonaws.com`).
  They most likely exist in the account already.
- **The VPC's IDs.** The VPC and two private subnets in different zones behind its NAT gateway, for
  `VPC_ID` and `APP_SUBNET_IDS` in the environment's `.local.conf` (never committed); and whether the VPC already has
  S3 and DynamoDB gateway endpoints on those subnets' route tables (`CREATE_GATEWAY_ENDPOINTS`).

## Rehearsed in a personal account first

`../terraform/rehearsal` makes a role with only this policy, attached as the same parts, and `./bmu aws` deploys the
BMU as that role into a VPC like Operations' in a personal account, with the simulated CollectionSpace
(`../README.md`, Rehearsing the deploy in your own account; `docs/testing-checklist.md`, section 24). What it can't
show: guardrails of UC Berkeley's account (service control policies, a permissions boundary), and anything already in
that account, such as the service-linked roles.

## When a deploy fails with `AccessDenied`

Note the action and resource in `docs/testing-checklist.md` (the section for the deploy into an existing VPC). The fix
goes into `bmu-deployer-policy.json` in a pull request; regenerate the parts and send Operations the part that
changed.

What the deploy creates is in [`../README.md`](../README.md) ("What it creates") and in `../terraform/`.
