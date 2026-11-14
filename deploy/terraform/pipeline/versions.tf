# The deploy pipeline's AWS side, for one environment (docs/design.md, Deploys; BP2, BP3, BP9, BP11): the two roles
# GitHub Actions assumes, GitHub's OIDC provider where the account has none (oidc.tf), the plan and apply CodeBuild
# projects, their build role, log group and the bucket of saved plans (build.tf). Applied by the account's
# administrator with ./bmu aws pipeline, never by the deployer or the build: it makes the build's own role. Its state is
# bmu/<env>/pipeline.tfstate, which the build may not write. Modelled on Serena's (cspace-media-server,
# deploy/terraform/pipeline).
#
# Nothing here is named bmu-* or tagged project=bmu: the deployer policy may create and change what carries either, and
# the build has that policy. The names are pipeline-bmu-<environment>-…, which Serena's pipeline-<environment>-… in the
# same account can't collide with.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket, key and region come from ./bmu aws (deploy/aws.sh): the account's state bucket, bmu/<env>/pipeline.tfstate.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # refuse to touch any other account, whatever credentials are in use

  default_tags {
    tags = {
      purpose     = "bmu-pipeline"
      environment = var.env_name
    }
  }
}

data "aws_partition" "current" {}

locals {
  name      = "pipeline-bmu-${var.environment}"
  partition = data.aws_partition.current.partition
  # The projects' ARNs, written out (the roles trust them before they exist).
  project_arn = {
    for mode in ["plan", "apply"] :
    mode => "arn:${local.partition}:codebuild:${var.region}:${var.account_id}:project/${local.name}-${mode}"
  }
}
