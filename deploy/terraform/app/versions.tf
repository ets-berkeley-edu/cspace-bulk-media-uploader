# The BMU in AWS, one environment per state: the web app and the worker on ECS Fargate, CloudFront (HTTPS, IP allowlist)
# in front of an internal load balancer, DynamoDB, the S3 staging bucket and KMS keys. Applied by ./bmu aws deploy;
# the image comes from ../registry.
#
# Layout: tasks run in public subnets with public IPs (no NAT gateway, which would cost about $35 a month); nothing
# can reach them from outside, because their security groups take traffic only from the load balancer. The load
# balancer is internal (private subnets), reachable only through CloudFront's VPC origin, so the hop from CloudFront
# to it stays inside AWS's network. S3 and DynamoDB traffic from the tasks goes through free gateway endpoints.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Bucket, key and region come from ./bmu aws (deploy/aws.sh): one state bucket per account, one key per environment.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id] # refuse to touch any other account, whatever credentials are in use

  default_tags {
    tags = {
      project     = "bmu"
      environment = var.env_name
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name       = "bmu-${var.env_name}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)
}
