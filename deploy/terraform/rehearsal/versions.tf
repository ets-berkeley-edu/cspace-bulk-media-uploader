# The rehearsal (personal accounts only): what Operations provides in UC Berkeley's account, made in a developer's own
# account, so that the BMU can be deployed there first as a role with only the deployer policy
# (../../iam/bmu-deployer-policy.json; docs/testing-checklist.md, section 24). A VPC like Operations' dev/QA VPC
# (network.tf) and the deployer role (deployer.tf). Applied by ./bmu aws rehearsal-vpc with the account's administrator
# profile, never by the deployer it makes; the app configuration stays as it is. Nothing here is tagged project=bmu:
# Operations' VPC doesn't carry the BMU's tag either.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket, key and region come from ./bmu aws (deploy/aws.sh): the account's state bucket, bmu/<env>/rehearsal.tfstate.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # refuse to touch any other account, whatever credentials are in use

  default_tags {
    tags = {
      purpose     = "bmu-deployer-rehearsal"
      environment = var.env_name
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name = "rehearsal-${var.env_name}"
}
