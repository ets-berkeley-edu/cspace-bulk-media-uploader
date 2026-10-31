# terraform test (run from deploy/terraform/ci after terraform init -backend=false). Plans against a simulated AWS
# provider: nothing is created and no sign-in is needed.

mock_provider "aws" {
  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }
}

variables {
  account_id = "123456789012"
  region     = "us-west-2"
}

run "the_role_trusts_only_this_repository_and_can_only_get_a_pull_token" {
  command = plan

  assert {
    condition     = local.allowed_subject == ["repo:ets-berkeley-edu@283538/cspace-bulk-media-uploader@1391463041:*"]
    error_message = "The role must trust only the BMU's repository."
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 1
    error_message = "By default the OIDC provider is created."
  }

  assert {
    condition     = aws_iam_role.ecr_public_pull.max_session_duration == 3600
    error_message = "Sessions last an hour at most."
  }
}

run "an_existing_oidc_provider_is_used_not_created" {
  command = plan

  variables {
    create_oidc_provider = false
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "With create_oidc_provider = false nothing new is created for OIDC."
  }
}

run "a_wildcard_repository_is_refused" {
  command = plan

  variables {
    repositories = ["repo:ets-berkeley-edu@283538/*"]
  }

  expect_failures = [var.repositories]
}

run "a_subject_without_ids_is_refused" {
  command = plan

  variables {
    repositories = ["repo:ets-berkeley-edu/cspace-bulk-media-uploader"]
  }

  expect_failures = [var.repositories]
}
