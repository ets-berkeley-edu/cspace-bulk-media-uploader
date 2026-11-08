# terraform test (run from deploy/terraform/app after terraform init -backend=false). Plans against a simulated AWS
# provider: nothing is created and no sign-in is needed.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-west-2a", "us-west-2b", "us-west-2c"]
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }
}

variables {
  account_id    = "123456789012"
  region        = "us-west-2"
  env_name      = "dev"
  image_uri     = "123456789012.dkr.ecr.us-west-2.amazonaws.com/bmu-dev:abc1234"
  allowed_cidrs = ["203.0.113.7/32", "198.51.100.0/24"]
  tenants       = { pahma = "https://pahma.qa.collectionspace.org" }
}

run "names_and_sizes" {
  command = plan

  assert {
    condition     = aws_ecs_cluster.main.name == "bmu-dev"
    error_message = "The cluster is named bmu-<env>; ./bmu aws status and logs rely on it."
  }

  assert {
    condition     = sort([for t in aws_dynamodb_table.main : t.name]) == tolist(["bmu-dev-audit", "bmu-dev-credentials", "bmu-dev-jobs", "bmu-dev-sessions"])
    error_message = "The four tables are named <BMU_TABLE_PREFIX>-jobs, -sessions, -credentials and -audit."
  }

  assert {
    condition     = aws_s3_bucket.staging.bucket == "bmu-dev-staging-123456789012-us-west-2"
    error_message = "The staging bucket's name includes the account and region, so it is unique."
  }

  assert {
    condition     = aws_ecs_service.web.desired_count == 1 && aws_ecs_service.worker.desired_count == 1
    error_message = "One web task and one worker run by default."
  }

  assert {
    condition     = aws_subnet.public[0].cidr_block == "10.40.0.0/24" && aws_subnet.private[1].cidr_block == "10.40.11.0/24"
    error_message = "Public subnets are 10.40.0-1.0/24 and private ones 10.40.10-11.0/24."
  }

  assert {
    condition     = length(aws_vpc.main) == 1 && aws_ecs_service.web.network_configuration[0].assign_public_ip && length(aws_vpc_endpoint.s3) == 1 && length(aws_vpc_endpoint.dynamodb) == 1
    error_message = "Without vpc_id, the BMU creates its own VPC: tasks with public IPs, and S3 and DynamoDB gateway endpoints."
  }
}

run "paused" {
  command = plan

  variables {
    running = false
  }

  assert {
    condition     = aws_ecs_service.web.desired_count == 0 && aws_ecs_service.worker.desired_count == 0
    error_message = "./bmu aws pause (running = false) stops both services."
  }
}

run "passwords_are_not_backed_up_and_demo_is_off" {
  command = plan

  assert {
    condition     = !aws_dynamodb_table.main["sessions"].point_in_time_recovery[0].enabled && !aws_dynamodb_table.main["credentials"].point_in_time_recovery[0].enabled
    error_message = "The tables holding encrypted passwords have no point-in-time recovery."
  }

  assert {
    condition     = aws_dynamodb_table.main["jobs"].point_in_time_recovery[0].enabled && aws_dynamodb_table.main["audit"].point_in_time_recovery[0].enabled
    error_message = "Jobs and audit entries have point-in-time recovery."
  }

  assert {
    condition     = local.app_environment["BMU_DEMO"] == "false" && local.app_environment["BMU_CRYPTO_MODE"] == "kms" && local.app_environment["BMU_COOKIE_SECURE"] == "true"
    error_message = "In AWS: Demo tools off, KMS encryption, secure cookies."
  }
}

run "each_museum_has_its_reader_secret_staging_key_and_prefixes" {
  command = plan

  variables {
    tenants = { pahma = "https://pahma.qa.collectionspace.org", bampfa = "https://bampfa.qa.collectionspace.org" }
  }

  assert {
    condition     = sort([for s in aws_secretsmanager_secret.reader : s.name]) == tolist(["bmu-dev/cspace-reader/bampfa", "bmu-dev/cspace-reader/pahma"])
    error_message = "Each museum's read-only account has its secret, bmu-<env>/cspace-reader/<museum>."
  }

  assert {
    condition     = alltrue([for s in aws_secretsmanager_secret.reader : s.recovery_window_in_days == 0])
    error_message = "A trial environment's secrets are deleted at once, so the environment can be created again."
  }

  assert {
    condition     = sort([for a in aws_kms_alias.staging : a.name]) == tolist(["alias/bmu-dev-staging-bampfa", "alias/bmu-dev-staging-pahma"])
    error_message = "Each museum has its staging key, alias/bmu-<env>-staging-<museum>."
  }

  assert {
    condition     = tolist(local.museum_objects["bampfa"]) == tolist(["arn:aws:s3:::bmu-dev-staging-123456789012-us-west-2/staging/bampfa/*", "arn:aws:s3:::bmu-dev-staging-123456789012-us-west-2/audit/bampfa/*"])
    error_message = "A museum's key may be used only for objects under its own staging/ and audit/ prefixes."
  }

  assert {
    condition     = jsondecode(local.app_environment["BMU_TENANTS"]) == { bampfa = "https://bampfa.qa.collectionspace.org", pahma = "https://pahma.qa.collectionspace.org" }
    error_message = "The app is told the museums and their servers (BMU_TENANTS)."
  }

  assert {
    # (The keys' and secrets' ARNs are known only after apply, so only their museums are checked here;
    # backend/tests/test_deploy.py checks the settings' form.)
    condition     = sort(keys(aws_kms_key.staging)) == tolist(["bampfa", "pahma"]) && sort(keys(aws_secretsmanager_secret.reader)) == tolist(["bampfa", "pahma"])
    error_message = "Each museum has a staging key and a read-only account's secret, which the app is told of."
  }

  assert {
    condition     = output.museums == "bampfa=https://bampfa.qa.collectionspace.org pahma=https://pahma.qa.collectionspace.org"
    error_message = "./bmu aws reads the museums and their servers from the museums output (deploy/aws.sh, check_museums)."
  }

  assert {
    condition     = !one(aws_s3_bucket_server_side_encryption_configuration.staging.rule).bucket_key_enabled
    error_message = "S3 Bucket Keys are off, so CloudTrail records each file's use of its museum's key."
  }
}

run "the_worker_has_one_vcpu_for_its_threads" {
  command = plan

  assert {
    condition     = aws_ecs_task_definition.worker.cpu == "1024" && aws_ecs_task_definition.worker.memory == "2048" && aws_ecs_task_definition.web.cpu == "256" && aws_ecs_task_definition.web.memory == "1024"
    error_message = "By default the worker has 1 vCPU and 2 GB (one thread per museum), the web app 0.25 vCPU and 1 GB."
  }
}

run "allowlist_is_written_into_the_function" {
  command = plan

  assert {
    condition     = strcontains(aws_cloudfront_function.allowlist[0].code, "var ALLOWED = \"203.0.113.7/32,198.51.100.0/24\";")
    error_message = "The CloudFront function holds the allowed addresses."
  }

  assert {
    condition     = !aws_cloudfront_distribution.main[0].is_ipv6_enabled
    error_message = "The distribution is IPv4-only, because the allowlist is IPv4."
  }
}

run "data_can_be_protected" {
  command = plan

  variables {
    protect_data = true
  }

  assert {
    condition     = alltrue([for t in aws_dynamodb_table.main : t.deletion_protection_enabled]) && !aws_s3_bucket.staging.force_destroy
    error_message = "protect_data = true turns on table deletion protection and stops destroy from emptying the buckets."
  }
}

run "an_empty_allowlist_is_refused" {
  command = plan

  variables {
    allowed_cidrs = []
  }

  expect_failures = [var.allowed_cidrs]
}

run "an_ipv6_address_is_refused" {
  command = plan

  variables {
    allowed_cidrs = ["2001:db8::/32"]
  }

  expect_failures = [var.allowed_cidrs]
}

run "a_bad_address_is_refused" {
  command = plan

  variables {
    allowed_cidrs = ["not-an-address"]
  }

  expect_failures = [var.allowed_cidrs]
}

run "the_museums_are_recorded_for_the_server_check" {
  command = plan

  variables {
    tenants = { pahma = "https://cspace.example.org" }
  }

  assert {
    condition     = output.tenants == tomap({ pahma = "https://cspace.example.org" }) && output.museums == "pahma=https://cspace.example.org"
    error_message = "./bmu aws reads the museums from the state to refuse a change of a museum's server (deploy/aws.sh, check_museums)."
  }
}

run "a_server_address_with_a_path_or_trailing_slash_is_refused" {
  command = plan

  variables {
    tenants = { pahma = "https://cspace.example.org/" }
  }

  expect_failures = [var.tenants]
}

run "no_museum_is_refused" {
  command = plan

  variables {
    tenants = {}
  }

  expect_failures = [var.tenants]
}

run "a_museum_name_that_cant_be_part_of_a_name_is_refused" {
  command = plan

  variables {
    tenants = { "Pahma QA" = "https://pahma.qa.collectionspace.org" }
  }

  expect_failures = [var.tenants]
}

run "the_simulated_collectionspace_is_off_by_default" {
  command = plan

  assert {
    condition     = length(aws_ecs_service.fakecspace) == 0 && length(aws_service_discovery_private_dns_namespace.main) == 0 && length(aws_security_group.fakecspace) == 0
    error_message = "Without simulated_cspace, nothing of the simulator is created."
  }

  assert {
    condition     = local.app_environment["BMU_CSPACE_SIMULATED"] == "false" && output.fakecspace_image_uri == ""
    error_message = "Without simulated_cspace, the app is told CollectionSpace is real."
  }
}

run "the_simulated_collectionspace_runs_in_the_environment" {
  command = plan

  variables {
    simulated_cspace     = true
    tenants              = { pahma = "http://fakecspace.bmu-dev.internal:8180" }
    fakecspace_image_uri = "123456789012.dkr.ecr.us-west-2.amazonaws.com/bmu-dev-fakecspace:abc1234"
  }

  assert {
    condition     = aws_ecs_service.fakecspace[0].desired_count == 1 && aws_ecs_task_definition.fakecspace[0].cpu == "256"
    error_message = "One small simulator task runs."
  }

  assert {
    condition     = aws_service_discovery_private_dns_namespace.main[0].name == "bmu-dev.internal" && aws_service_discovery_service.fakecspace[0].name == "fakecspace"
    error_message = "The simulator is found as fakecspace.bmu-<env>.internal."
  }

  assert {
    condition     = var.tenants["pahma"] == local.fakecspace_url && local.app_environment["BMU_CSPACE_SIMULATED"] == "true"
    error_message = "The BMU uses the simulator's address and knows it is the simulator."
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.fakecspace_from_web[0].from_port == 8180 && aws_vpc_security_group_ingress_rule.fakecspace_from_worker[0].from_port == 8180
    error_message = "Only the web app and the worker can connect to the simulator, on its port."
  }
}

run "the_simulator_is_paused_with_the_others" {
  command = plan

  variables {
    simulated_cspace     = true
    tenants              = { pahma = "http://fakecspace.bmu-dev.internal:8180" }
    fakecspace_image_uri = "123456789012.dkr.ecr.us-west-2.amazonaws.com/bmu-dev-fakecspace:abc1234"
    running              = false
  }

  assert {
    condition     = aws_ecs_service.fakecspace[0].desired_count == 0
    error_message = "./bmu aws pause stops the simulator too."
  }
}

run "the_simulator_is_refused_where_data_is_protected" {
  command = plan

  variables {
    simulated_cspace     = true
    tenants              = { pahma = "http://fakecspace.bmu-dev.internal:8180" }
    fakecspace_image_uri = "x:1"
    protect_data         = true
  }

  expect_failures = [var.simulated_cspace]
}

run "the_simulator_needs_its_image" {
  command = plan

  variables {
    simulated_cspace = true
    tenants          = { pahma = "http://fakecspace.bmu-dev.internal:8180" }
  }

  expect_failures = [var.fakecspace_image_uri]
}

run "with_the_simulator_the_bmu_must_use_its_address" {
  command = plan

  variables {
    simulated_cspace     = true
    fakecspace_image_uri = "x:1"
  }

  expect_failures = [var.tenants]
}

run "the_simulator_is_pahma_alone" {
  command = plan

  variables {
    simulated_cspace     = true
    fakecspace_image_uri = "x:1"
    tenants              = { pahma = "http://fakecspace.bmu-dev.internal:8180", bampfa = "https://bampfa.qa.collectionspace.org" }
  }

  expect_failures = [var.tenants]
}

# ---- review 29 October 2026, section 5 -------------------------------------------------------------------------------

run "a_real_collectionspace_must_be_https" {
  command = plan

  variables {
    tenants = { pahma = "http://pahma.qa.collectionspace.org" }
  }

  expect_failures = [var.tenants]
}

run "without_an_origin_domain_cloudfront_reaches_the_load_balancer_with_http" {
  command = plan

  assert {
    condition     = length(aws_lb_listener.http) == 1 && length(aws_lb_listener.https) == 0
    error_message = "Without origin_domain the load balancer listens on 80 only."
  }

  assert {
    condition     = aws_cloudfront_vpc_origin.alb[0].vpc_origin_endpoint_config[0].origin_protocol_policy == "http-only"
    error_message = "Without origin_domain CloudFront uses HTTP to the load balancer."
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_from_cloudfront[0].from_port == 80
    error_message = "Without origin_domain the load balancer admits CloudFront on 80."
  }
}

run "with_an_origin_domain_the_hop_to_the_load_balancer_is_https_only" {
  command = plan

  variables {
    origin_domain          = "bmu-dev-origin.example.berkeley.edu"
    origin_certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
  }

  assert {
    condition     = length(aws_lb_listener.http) == 0 && length(aws_lb_listener.https) == 1
    error_message = "With origin_domain the load balancer listens on 443 only."
  }

  assert {
    condition     = aws_lb_listener.https[0].certificate_arn == var.origin_certificate_arn && startswith(aws_lb_listener.https[0].ssl_policy, "ELBSecurityPolicy-TLS13")
    error_message = "The HTTPS listener uses the certificate and a TLS 1.2+ policy."
  }

  assert {
    condition     = aws_cloudfront_vpc_origin.alb[0].vpc_origin_endpoint_config[0].origin_protocol_policy == "https-only"
    error_message = "With origin_domain CloudFront uses HTTPS only to the load balancer."
  }

  assert {
    condition     = one([for o in aws_cloudfront_distribution.main[0].origin : o.domain_name]) == "bmu-dev-origin.example.berkeley.edu"
    error_message = "CloudFront checks the certificate against origin_domain."
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_from_cloudfront[0].from_port == 443 && aws_vpc_security_group_ingress_rule.alb_from_cloudfront[0].to_port == 443
    error_message = "The load balancer admits CloudFront on 443 only (one rule: the prefix list fills the group)."
  }
}

run "an_origin_domain_needs_its_certificate" {
  command = plan

  variables {
    origin_domain = "bmu-dev-origin.example.berkeley.edu"
  }

  expect_failures = [var.origin_certificate_arn]
}

run "no_waf_by_default" {
  command = plan

  assert {
    condition     = length(aws_wafv2_web_acl.main) + length(aws_wafv2_web_acl_association.alb) + length(aws_cloudwatch_log_group.waf) == 0
    error_message = "The WAF is off unless waf_enabled."
  }
}

run "a_cloudfront_environment_has_no_waf" {
  command = plan

  variables {
    waf_enabled = true
  }

  expect_failures = [var.waf_enabled]
}

run "keys_wait_30_days_before_deletion_where_data_is_protected" {
  command = plan

  variables {
    protect_data = true
  }

  assert {
    condition     = aws_kms_key.session.deletion_window_in_days == 30 && aws_kms_key.job.deletion_window_in_days == 30 && alltrue([for k in aws_kms_key.staging : k.deletion_window_in_days == 30])
    error_message = "With protect_data every key has the longest deletion window, 30 days."
  }
}

# An existing VPC (network.tf), such as Operations' shared dev/QA VPC. The IDs are made up.
run "in_an_existing_vpc_nothing_of_the_network_is_created" {
  command = plan

  variables {
    vpc_id         = "vpc-00000000000000001"
    app_subnet_ids = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
  }

  override_data {
    target = data.aws_vpc.existing
    values = { id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  assert {
    condition = (length(aws_vpc.main) + length(aws_internet_gateway.main) + length(aws_subnet.public) + length(aws_subnet.private)
    + length(aws_route_table.public) + length(aws_route_table.private) + length(aws_vpc_endpoint.s3) + length(aws_vpc_endpoint.dynamodb)) == 0
    error_message = "In an existing VPC the BMU creates no VPC, gateway, subnets, route tables or (by default) gateway endpoints."
  }

  assert {
    condition = (!aws_ecs_service.web.network_configuration[0].assign_public_ip && !aws_ecs_service.worker.network_configuration[0].assign_public_ip
      && toset(aws_ecs_service.web.network_configuration[0].subnets) == toset(var.app_subnet_ids)
    && toset(aws_ecs_service.worker.network_configuration[0].subnets) == toset(var.app_subnet_ids))
    error_message = "The tasks run in the given private subnets without public IPs (out through the VPC's NAT gateway)."
  }

  assert {
    condition     = aws_lb.main.internal && toset(aws_lb.main.subnets) == toset(var.app_subnet_ids)
    error_message = "Without lb_subnet_ids, the internal load balancer goes in the app subnets."
  }

  assert {
    condition = (aws_security_group.alb.vpc_id == var.vpc_id && aws_security_group.web.vpc_id == var.vpc_id
    && aws_security_group.worker.vpc_id == var.vpc_id && aws_lb_target_group.web.vpc_id == var.vpc_id)
    error_message = "The security groups and the target group are in the given VPC."
  }
}

run "in_an_existing_vpc_the_load_balancer_can_have_its_own_subnets_and_endpoints_can_be_added" {
  command = plan

  variables {
    vpc_id                   = "vpc-00000000000000001"
    app_subnet_ids           = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
    lb_subnet_ids            = ["subnet-0000000000000000c", "subnet-0000000000000000d"]
    create_gateway_endpoints = true
    simulated_cspace         = true
    tenants                  = { pahma = "http://fakecspace.bmu-dev.internal:8180" }
    fakecspace_image_uri     = "123456789012.dkr.ecr.us-west-2.amazonaws.com/bmu-dev-fakecspace:abc1234"
  }

  override_data {
    target = data.aws_vpc.existing
    values = { id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_route_table.app
    values = { id = "rtb-0000000000000000a" }
  }

  assert {
    condition     = toset(aws_lb.main.subnets) == toset(var.lb_subnet_ids)
    error_message = "The load balancer goes in lb_subnet_ids when they're given."
  }

  assert {
    condition     = length(aws_vpc_endpoint.s3) == 1 && aws_vpc_endpoint.s3[0].route_table_ids == toset(["rtb-0000000000000000a"]) && length(aws_vpc_endpoint.dynamodb) == 1
    error_message = "create_gateway_endpoints adds S3 and DynamoDB endpoints to the app subnets' route tables, each table once."
  }

  assert {
    condition = (!aws_ecs_service.fakecspace[0].network_configuration[0].assign_public_ip
    && aws_service_discovery_private_dns_namespace.main[0].vpc == var.vpc_id)
    error_message = "The simulator runs like the others: in the app subnets without a public IP, its name in the given VPC."
  }
}

run "a_subnet_outside_the_vpc_is_refused" {
  command = plan

  variables {
    vpc_id         = "vpc-00000000000000001"
    app_subnet_ids = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
  }

  override_data {
    target = data.aws_vpc.existing
    values = { id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000002" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  expect_failures = [data.aws_subnet.app]
}

run "an_existing_vpc_needs_two_app_subnets" {
  command = plan

  variables {
    vpc_id         = "vpc-00000000000000001"
    app_subnet_ids = ["subnet-0000000000000000a"]
  }

  expect_failures = [var.app_subnet_ids]
}

run "subnets_without_a_vpc_are_refused" {
  command = plan

  variables {
    app_subnet_ids = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
  }

  expect_failures = [var.app_subnet_ids]
}

run "gateway_endpoints_without_a_vpc_are_refused" {
  command = plan

  variables {
    create_gateway_endpoints = true
  }

  expect_failures = [var.create_gateway_endpoints]
}

# ---- The front door (variables.tf, front_door) ----

run "by_default_cloudfront_is_the_front_door" {
  command = plan

  assert {
    condition = (length(aws_cloudfront_distribution.main) == 1 && length(aws_cloudfront_function.allowlist) == 1
      && length(aws_cloudfront_vpc_origin.alb) == 1 && aws_lb.main.internal && length(aws_vpc_security_group_ingress_rule.alb_https) == 0
    && output.front_door == "cloudfront")
    error_message = "front_door cloudfront: CloudFront, its function and VPC origin, an internal load balancer, no rules for allowed_cidrs."
  }

  assert {
    condition     = aws_security_group.alb.description == "BMU load balancer. The CloudFront VPC origin connects from inside the VPC."
    error_message = "The CloudFront environment's security group keeps its description: a new one would replace the group, which fails."
  }

  assert {
    condition     = length([for st in data.aws_iam_policy_document.staging_bucket.statement : st if st.sid == "UploadsOnlyFromTheAllowedAddressesOrTheVpc"]) == 0
    error_message = "Behind CloudFront the staging bucket has no upload address rule (its allowlist is CloudFront's)."
  }
}

run "alb_is_an_internet_facing_load_balancer_on_the_domain_with_https_only" {
  command = plan

  variables {
    front_door      = "alb"
    domain_name     = "bmu-qa.example.berkeley.edu"
    certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
    vpc_id          = "vpc-00000000000000001"
    app_subnet_ids  = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
    lb_subnet_ids   = ["subnet-0000000000000000c", "subnet-0000000000000000d"]
  }

  override_data {
    target = data.aws_vpc.existing
    values = { id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_vpc_endpoint.s3
    values = { id = "vpce-0000000000000000a" }
  }

  assert {
    condition = (length(aws_cloudfront_distribution.main) + length(aws_cloudfront_function.allowlist) + length(aws_cloudfront_vpc_origin.alb)
    + length(aws_vpc_security_group_ingress_rule.alb_from_cloudfront) + length(data.aws_ec2_managed_prefix_list.cloudfront_origin_facing)) == 0
    error_message = "front_door alb: no CloudFront distribution, function, VPC origin or prefix list rule."
  }

  assert {
    condition     = !aws_lb.main.internal && toset(aws_lb.main.subnets) == toset(var.lb_subnet_ids)
    error_message = "The load balancer is internet-facing, in lb_subnet_ids (the VPC's public subnets)."
  }

  assert {
    condition = (length(aws_lb_listener.http) == 0 && length(aws_lb_listener.https) == 1
      && aws_lb_listener.https[0].certificate_arn == var.certificate_arn
    && aws_lb_listener.https[0].ssl_policy == "ELBSecurityPolicy-TLS13-1-2-2021-06")
    error_message = "One HTTPS listener with domain_name's certificate and the TLS 1.3 policy; no HTTP listener (no port 80)."
  }

  assert {
    condition = (toset([for r in aws_vpc_security_group_ingress_rule.alb_https : r.cidr_ipv4]) == toset(var.allowed_cidrs)
    && alltrue([for r in aws_vpc_security_group_ingress_rule.alb_https : r.from_port == 443 && r.to_port == 443 && r.ip_protocol == "tcp"]))
    error_message = "The load balancer's security group admits allowed_cidrs on 443 only."
  }

  assert {
    condition     = aws_security_group.alb.description == "BMU load balancer. HTTPS from the allowed addresses only."
    error_message = "An alb environment's security group says what it admits."
  }

  assert {
    condition     = output.url == "https://bmu-qa.example.berkeley.edu" && output.front_door == "alb" && output.domain_name == var.domain_name
    error_message = "The address is the domain name."
  }

  assert {
    condition     = one(aws_s3_bucket_cors_configuration.staging.cors_rule).allowed_origins == toset(["https://bmu-qa.example.berkeley.edu"])
    error_message = "The staging bucket takes browser uploads from the domain name."
  }

  assert {
    condition = anytrue([for st in data.aws_iam_policy_document.staging_bucket.statement :
      st.sid == "UploadsOnlyFromTheAllowedAddressesOrTheVpc" && st.effect == "Deny" && toset(st.actions) == toset(["s3:PutObject"])
      && anytrue([for c in st.condition : c.test == "NotIpAddress" && c.variable == "aws:SourceIp" && toset(c.values) == toset(var.allowed_cidrs)])
    && anytrue([for c in st.condition : c.test == "StringNotEqualsIfExists" && c.variable == "aws:SourceVpce" && toset(c.values) == toset(["vpce-0000000000000000a"])])])
    error_message = "The staging bucket refuses uploads unless from allowed_cidrs or through the VPC's S3 endpoint (BQ31)."
  }

  assert {
    condition     = length(aws_wafv2_web_acl.main) == 0
    error_message = "No WAF unless waf_enabled."
  }
}

run "alb_with_the_waf_regional_on_the_load_balancer" {
  command = plan

  variables {
    front_door               = "alb"
    domain_name              = "bmu-qa.example.berkeley.edu"
    certificate_arn          = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
    vpc_id                   = "vpc-00000000000000001"
    app_subnet_ids           = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
    lb_subnet_ids            = ["subnet-0000000000000000c", "subnet-0000000000000000d"]
    create_gateway_endpoints = true
    waf_enabled              = true
  }

  override_data {
    target = data.aws_vpc.existing
    values = { id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_route_table.app
    values = { id = "rtb-0000000000000000a" }
  }

  assert {
    condition     = length(data.aws_vpc_endpoint.s3) == 0 && length(aws_vpc_endpoint.s3) == 1
    error_message = "With create_gateway_endpoints, the upload rule names the BMU's own S3 endpoint; nothing is looked up."
  }

  assert {
    condition     = aws_wafv2_web_acl.main[0].scope == "REGIONAL" && length(aws_wafv2_web_acl_association.alb) == 1
    error_message = "The WAF is regional and associated with the load balancer."
  }

  assert {
    condition = (
      [for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].limit if r.name == "sign-in-rate"] == [20] &&
      [for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].limit if r.name == "request-rate"] == [3000] &&
      alltrue([for r in aws_wafv2_web_acl.main[0].rule : length(r.action[0].block) == 1 && r.statement[0].rate_based_statement[0].aggregate_key_type == "IP" if startswith(r.name, "sign-in") || startswith(r.name, "request")])
    )
    error_message = "Sign-in is limited to 20 and all requests to 3,000 per source address in 5 minutes, both blocking."
  }

  assert {
    condition = (
      toset([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].managed_rule_group_statement[0].name if length(r.statement[0].managed_rule_group_statement) > 0])
      == toset(["AWSManagedRulesAmazonIpReputationList", "AWSManagedRulesCommonRuleSet", "AWSManagedRulesKnownBadInputsRuleSet"])
      && alltrue([for r in aws_wafv2_web_acl.main[0].rule : length(r.override_action[0].count) == 1 if length(r.statement[0].managed_rule_group_statement) > 0])
    )
    error_message = "AWS's IP reputation, common and known-bad-inputs rule sets run in count mode by default."
  }

  assert {
    condition = (aws_cloudwatch_log_group.waf[0].name == "aws-waf-logs-bmu-dev"
      && length([for f in aws_wafv2_web_acl_logging_configuration.main[0].redacted_fields : f if length(f.query_string) == 1]) == 1
      && length([for f in aws_wafv2_web_acl_logging_configuration.main[0].redacted_fields : f if length(f.single_header) == 1 && f.single_header[0].name == "cookie"]) == 1
    && length([for f in aws_wafv2_web_acl_logging_configuration.main[0].redacted_fields : f if length(f.uri_path) == 1]) == 0)
    error_message = "The WAF logs to aws-waf-logs-bmu-<env>, redacting the query string and the Cookie header, keeping the path."
  }
}

run "the_managed_rule_sets_can_block" {
  command = plan

  variables {
    front_door        = "alb"
    domain_name       = "bmu-qa.example.berkeley.edu"
    certificate_arn   = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
    vpc_id            = "vpc-00000000000000001"
    app_subnet_ids    = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
    lb_subnet_ids     = ["subnet-0000000000000000c", "subnet-0000000000000000d"]
    waf_enabled       = true
    waf_managed_rules = "block"
  }

  override_data {
    target = data.aws_vpc.existing
    values = { id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_vpc_endpoint.s3
    values = { id = "vpce-0000000000000000a" }
  }

  assert {
    condition = alltrue([for r in aws_wafv2_web_acl.main[0].rule :
    length(r.override_action[0].none) == 1 && length(r.override_action[0].count) == 0 if length(r.statement[0].managed_rule_group_statement) > 0])
    error_message = "waf_managed_rules block: the rule sets' own actions apply."
  }

  assert {
    condition = anytrue([for r in aws_wafv2_web_acl.main[0].rule : anytrue([for o in r.statement[0].managed_rule_group_statement[0].rule_action_override :
    o.name == "SizeRestrictions_BODY" && length(o.action_to_use[0].count) == 1]) if r.name == "common"])
    error_message = "The common rule set's body size rule only counts: saving a job's documents can exceed 8 KB."
  }
}

run "alb_needs_an_existing_vpc_with_load_balancer_subnets" {
  command = plan

  variables {
    front_door      = "alb"
    domain_name     = "bmu-qa.example.berkeley.edu"
    certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
  }

  expect_failures = [var.front_door]
}

run "alb_needs_its_domain_and_certificate" {
  command = plan

  variables {
    front_door     = "alb"
    vpc_id         = "vpc-00000000000000001"
    app_subnet_ids = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
    lb_subnet_ids  = ["subnet-0000000000000000c", "subnet-0000000000000000d"]
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  expect_failures = [var.domain_name, var.certificate_arn]
}

run "a_domain_is_only_for_alb" {
  command = plan

  variables {
    domain_name = "bmu-qa.example.berkeley.edu"
  }

  expect_failures = [var.domain_name]
}

run "an_origin_domain_is_only_for_cloudfront" {
  command = plan

  variables {
    front_door             = "alb"
    domain_name            = "bmu-qa.example.berkeley.edu"
    certificate_arn        = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
    vpc_id                 = "vpc-00000000000000001"
    app_subnet_ids         = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
    lb_subnet_ids          = ["subnet-0000000000000000c", "subnet-0000000000000000d"]
    origin_domain          = "bmu-dev-origin.example.berkeley.edu"
    origin_certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  expect_failures = [var.origin_domain]
}

run "alb_allows_at_most_60_ranges" {
  command = plan

  variables {
    front_door      = "alb"
    domain_name     = "bmu-qa.example.berkeley.edu"
    certificate_arn = "arn:aws:acm:us-west-2:123456789012:certificate/0f1e2d3c-4b5a-6978-8091-a2b3c4d5e6f7"
    vpc_id          = "vpc-00000000000000001"
    app_subnet_ids  = ["subnet-0000000000000000a", "subnet-0000000000000000b"]
    lb_subnet_ids   = ["subnet-0000000000000000c", "subnet-0000000000000000d"]
    allowed_cidrs   = [for i in range(61) : "10.0.${i}.0/24"]
  }

  override_data {
    target = data.aws_subnet.app
    values = { vpc_id = "vpc-00000000000000001" }
  }

  override_data {
    target = data.aws_subnet.lb
    values = { vpc_id = "vpc-00000000000000001" }
  }

  expect_failures = [var.allowed_cidrs]
}
