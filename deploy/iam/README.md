# The deployer's permissions (for Operations)

The IAM policy the person running `./bmu aws` (Terraform included) needs in a UC Berkeley AWS account, for the
BMU's stage 2 (`../environments/ucb-qa.conf`): a QA deployment in an existing VPC (`../README.md`, "Deploying
into an existing VPC") that uses PAHMA's QA CollectionSpace. Its front door is an internet-facing load balancer on
the BMU's own name with an ACM certificate and a regional WAF; there is no CloudFront.

Nothing here is secret: no account numbers, network IDs, addresses or keys. Account IDs are wildcards (`*`), and
every write is limited to resources named `bmu-*` (log groups `/bmu/*` and `aws-waf-logs-bmu-*`) or tagged
`project=bmu` wherever AWS allows it. Terraform tags everything it creates `project=bmu` (its default tags).

| File | What |
| --- | --- |
| `bmu-deployer-policy.json` | The whole policy: the only copy, reviewed with the Terraform it permits. About 12,300 characters without whitespace |
| `split-policy.py` | Splits it into the customer managed policies to attach (below) |
| `bmu-simulator-dns-policy.json` | **Not for Operations.** Route 53 and Cloud Map for the simulated CollectionSpace's private DNS name, given only to the rehearsal's role (below) |

## The ask

Create an IAM role **`rtl-BmuQaDeployer`**, with the same trust as `rtl-SerenaStage2Deployer` (assumed from the
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
- **Kept, as Serena's:** the internet-facing load balancer and its web ACL (`LoadBalancerWebAcl`), the ACM
  certificate (`CertificateCreateTagged`, `CertificateTagged`), the regional WAF without IP sets (`Waf`), its logs
  (`WafLogDelivery`, and `aws-waf-logs-bmu-*` in `Logs`), and the `acm:` and `wafv2:` reads. The load balancer
  statements don't limit the scheme, so they allow an internet-facing one.
- **Removed**, because the BMU doesn't use them: CloudFront (the BMU has none in this account, so `cloudfront:*` is
  no longer exempt from the region Deny either), WAF IP sets, alarms (CloudWatch and SNS), SSM parameters, and the ETL
  token secrets' resource policies, with the reads for CloudFront, SNS and SSM.
- **Added**, because the BMU's architecture differs: the staging bucket takes uploads straight from the browser
  (`s3:PutBucketCORS`) and logs its access to a second `bmu-*` bucket (`s3:PutBucketLogging`).

Like Serena's stage 2 policy, it can't create or change a VPC, subnets, routes or gateways. In the existing VPC it
can create security groups and their rules, and the S3 and DynamoDB gateway endpoints (only when
`CREATE_GATEWAY_ENDPOINTS=true`), all tagged `project=bmu`.

## Where it can't be narrower

- ACM certificates have generated IDs: they are created and changed only with the `project=bmu` tag. Web ACLs are
  limited by name (`bmu-*`); AWS's managed rule groups are named in `Waf` because a web ACL refers to them. WAF log
  delivery and CloudWatch Logs resource policies have no resource to scope to.
- Security groups, their rules and gateway endpoints have generated IDs; they are limited by tag, and can be
  created in any VPC (the VPC is Operations', so it can't carry the BMU's tag).
- ECS task definitions and KMS key creation have no name-based resource to scope to (keys are limited by tag
  afterwards; their aliases by name).
- Read-only `Describe`, `Get` and `List` calls are allowed account-wide: Terraform reads many attributes of each
  resource, the exact list changes with provider versions, and they return only metadata.
- `iam:PassRole` is limited to `bmu-*` roles and to ECS tasks; the only managed policy that can be attached is
  `AmazonECSTaskExecutionRolePolicy`.
- The deployer can read and write the BMU's own secrets (`bmu-*`): `./bmu aws` sets them without showing or storing
  them. The KMS key policies keep the deployer from using the BMU's keys to read saved passwords or staged files
  (`../README.md`, Key policies).

## Not covered

- **DNS.** There is no Route 53 or Cloud Map in this policy. Route 53 appears only in the region Deny's exemptions
  (it is a global service), which allow nothing on their own. Operations adds the certificate's validation record
  once, and the BMU's name pointing at the load balancer, repointed after each destroy (BQ32).
- **The simulated CollectionSpace.** Its private DNS name (Cloud Map) needs Route 53 permissions that can't be limited
  to its own zone (hosted zones have generated IDs), so they aren't in this policy: only the rehearsal's role gets
  them (`bmu-simulator-dns-policy.json`). The UC Berkeley environment uses PAHMA's QA CollectionSpace, never the
  simulator; a deploy with `SIMULATED_CSPACE=true` as this role fails with `AccessDenied` on Route 53.
- **`./bmu aws ci-role`** (CI's ECR Public role and the GitHub OIDC provider) isn't for this role.
- **A deploy pipeline** (GitHub OIDC and CodeBuild), as for Serena: later.
- The role can't list its own policies (its IAM reads are limited to `bmu-*` roles). That's expected.

## Also needed from Operations, outside the policy

- **Service-linked roles.** If guardrails stop the deployer creating them: `AWSServiceRoleForECS`,
  and `AWSServiceRoleForElasticLoadBalancing`. They most likely exist in the account already.
- **The VPC's IDs.** The VPC, two private subnets in different zones behind its NAT gateway, and two public subnets
  for the load balancer, for `VPC_ID`, `APP_SUBNET_IDS` and `LB_SUBNET_IDS` in the environment's `.local.conf` (never
  committed); and whether the VPC already has S3 and DynamoDB gateway endpoints on the private subnets' route tables
  (`CREATE_GATEWAY_ENDPOINTS`). vpc-devqa has an S3 one on them, and no DynamoDB one.
- **The name and its DNS.** The BMU's name (`bmu-qa.<domain>`, for `DOMAIN_NAME`), the certificate's validation
  record (printed by the first `./bmu aws deploy`), and the name's record pointing at the load balancer.

## Rehearsed in a personal account first

`../terraform/rehearsal` makes a role with only this policy, attached as the same parts (plus, inline,
`bmu-simulator-dns-policy.json` for the simulator), and `./bmu aws` deploys the
BMU as that role into a VPC like Operations' in a personal account, with the simulated CollectionSpace
(`../README.md`, Rehearsing the deploy in your own account; `docs/testing-checklist.md`, section 24). What it can't
show: guardrails of UC Berkeley's account (service control policies, a permissions boundary), and anything already in
that account, such as the service-linked roles.

## When a deploy fails with `AccessDenied`

Note the action and resource in `docs/testing-checklist.md` (the section for the deploy into an existing VPC). The fix
goes into `bmu-deployer-policy.json` in a pull request; regenerate the parts and send Operations the part that
changed.

What the deploy creates is in [`../README.md`](../README.md) ("What it creates") and in `../terraform/`.
