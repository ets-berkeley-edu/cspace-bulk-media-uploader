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

run "allowlist_is_written_into_the_function" {
  command = plan

  assert {
    condition     = strcontains(aws_cloudfront_function.allowlist.code, "var ALLOWED = \"203.0.113.7/32,198.51.100.0/24\";")
    error_message = "The CloudFront function holds the allowed addresses."
  }

  assert {
    condition     = !aws_cloudfront_distribution.main.is_ipv6_enabled
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
