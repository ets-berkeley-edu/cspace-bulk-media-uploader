# terraform test (run from deploy/terraform/rehearsal after terraform init -backend=false). Plans the rehearsal's VPC
# and deployer against a simulated AWS provider: nothing is created and no sign-in is needed. The policy parts here are
# stand-ins; ../../../backend/tests/test_deploy.py checks the real ones.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_AdministratorAccess_0123456789abcdef/someone"
    }
  }

  mock_data "aws_iam_session_context" {
    defaults = {
      issuer_arn = "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/us-west-2/AWSReservedSSO_AdministratorAccess_0123456789abcdef"
    }
  }

  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-west-2c", "us-west-2a", "us-west-2b"]
    }
  }

  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/rehearsal-devqar-deployer"
    }
  }
}

variables {
  account_id = "123456789012"
  region     = "us-west-2"
  env_name   = "devqar"
  policy_parts = [
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"A\",\"Effect\":\"Allow\",\"Action\":\"ecs:ListClusters\",\"Resource\":\"*\"}]}",
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"B\",\"Effect\":\"Allow\",\"Action\":\"ecr:DescribeRegistry\",\"Resource\":\"*\"}]}",
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"C\",\"Effect\":\"Allow\",\"Action\":\"kms:ListKeys\",\"Resource\":\"*\"}]}",
  ]
}

run "a_vpc_like_operations" {
  command = plan

  assert {
    condition     = [for s in aws_subnet.private : s.availability_zone] == ["us-west-2a", "us-west-2b"] && [for s in aws_subnet.public : s.availability_zone] == ["us-west-2a", "us-west-2b"]
    error_message = "Two public and two private subnets, in the same two zones."
  }

  assert {
    condition     = length(setintersection([for s in aws_subnet.public : s.cidr_block], [for s in aws_subnet.private : s.cidr_block])) == 0
    error_message = "The subnets don't overlap."
  }

  assert {
    condition     = one(aws_route_table.private.route).cidr_block == "0.0.0.0/0" && one(aws_route_table.private.route).gateway_id == null
    error_message = "The private subnets go out through the NAT gateway, not the internet gateway."
  }
}

run "a_deployer_with_only_the_policys_parts" {
  command = plan

  assert {
    condition     = !startswith(aws_iam_role.deployer.name, "bmu-") && alltrue([for p in aws_iam_policy.part : !startswith(p.name, "bmu-")])
    error_message = "Neither the deployer's role nor its policies are bmu-*, which the policy itself may change."
  }

  assert {
    condition     = jsondecode(aws_iam_role.deployer.assume_role_policy).Statement[0].Principal.AWS == "arn:aws:iam::123456789012:role/aws-reserved/sso.amazonaws.com/us-west-2/AWSReservedSSO_AdministratorAccess_0123456789abcdef"
    error_message = "Only the administrator role that applies this configuration may assume the deployer."
  }

  assert {
    condition     = length(aws_iam_policy.part) == 3 && alltrue([for i, p in aws_iam_policy.part : p.policy == var.policy_parts[i]]) && length(aws_iam_role_policy_attachment.part) == 3
    error_message = "Each part becomes one managed policy, unchanged, attached to the deployer."
  }

  assert {
    condition     = aws_iam_role.deployer.max_session_duration == 3600
    error_message = "Sessions of an hour, as rtl-BmuQaDeployer's (role chaining allows no more)."
  }
}

run "a_part_over_the_limit_is_refused" {
  command = plan

  variables {
    policy_parts = [format("{\"Version\":\"2012-10-17\",\"Statement\":[],\"Pad\":\"%s\"}", join("", [for i in range(1000) : "xxxxxxx"]))]
  }

  expect_failures = [var.policy_parts]
}
