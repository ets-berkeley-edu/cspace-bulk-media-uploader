# The role GitHub Actions assumes to sign in to Amazon ECR Public before the bmut job pulls base images: signed-in pulls
# have a much higher limit than anonymous ones, which GitHub's shared runner addresses run out of (429 "Data limit
# exceeded"). The role can do nothing but get an ECR Public pull token. Once per account, not per environment: applied
# by ./bmu aws ci-role, its state at bmu/ci/ci.tfstate in the account's state bucket. Its ARN goes in the repository's
# Actions variable ECR_PUBLIC_ROLE_ARN (not in the repository: it holds the account number).

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket, key and region come from ./bmu aws ci-role (deploy/aws.sh).
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # refuse to touch any other account, whatever credentials are in use

  default_tags {
    tags = {
      project = "bmu"
      purpose = "ci"
    }
  }
}

variable "account_id" {
  description = "The AWS account; Terraform refuses to run against any other."
  type        = string

  validation {
    condition     = can(regex("^\\d{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account number."
  }
}

variable "region" {
  description = "AWS region for the provider (IAM itself is global)."
  type        = string
}

variable "repositories" {
  description = "GitHub repositories (owner/name) whose workflows may assume the role, on any branch or pull request."
  type        = list(string)
  default     = ["ets-berkeley-edu/cspace-bulk-media-uploader"]

  validation {
    condition     = length(var.repositories) > 0 && alltrue([for r in var.repositories : can(regex("^ets-berkeley-edu/[A-Za-z0-9._-]+$", r))])
    error_message = "repositories must name at least one ets-berkeley-edu repository, as owner/name with no wildcard."
  }
}

variable "create_oidc_provider" {
  description = "true creates the account's GitHub OIDC provider; false uses the one it already has (./bmu aws ci-role decides)."
  type        = bool
  default     = true
}

locals {
  oidc_url        = "https://token.actions.githubusercontent.com"
  oidc_provider   = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
  allowed_subject = [for r in var.repositories : "repo:${r}:*"]
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = local.oidc_url
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1
  url   = local.oidc_url
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.allowed_subject
    }
  }
}

data "aws_iam_policy_document" "pull_token" {
  statement {
    # Both are needed for an ECR Public sign-in, and neither can be narrowed to a resource.
    actions   = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "ecr_public_pull" {
  name                 = "bmu-ci-ecr-public-pull"
  description          = "GitHub Actions (OIDC): an ECR Public pull token, nothing else"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "pull_token" {
  name   = "ecr-public-pull-token"
  role   = aws_iam_role.ecr_public_pull.id
  policy = data.aws_iam_policy_document.pull_token.json
}

output "role_arn" {
  description = "For the repository's Actions variable ECR_PUBLIC_ROLE_ARN."
  value       = aws_iam_role.ecr_public_pull.arn
}
