# BMU container image repository. Its own configuration (and state), so the image can be pushed before the app
# configuration (../app) starts tasks that run it. Applied by ./bmu aws deploy.

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

variable "account_id" {
  description = "The AWS account this environment belongs to; Terraform refuses to run against any other."
  type        = string

  validation {
    condition     = can(regex("^\\d{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account number."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "env_name" {
  description = "Environment name within the account, used in every resource name (bmu-<env>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "simulated_cspace" {
  description = "true also creates the simulated CollectionSpace's repository (../app/fakecspace.tf)."
  type        = bool
  default     = false
}

resource "aws_ecr_repository" "app" {
  name                 = "bmu-${var.env_name}"
  image_tag_mutability = "IMMUTABLE" # every deploy pushes a new tag (commit and time)
  force_delete         = true        # ./bmu aws destroy removes the images with the repository

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# The simulated CollectionSpace's image: its own repository, so the BMU's image never contains the simulator.
resource "aws_ecr_repository" "fakecspace" {
  count                = var.simulated_cspace ? 1 : 0
  name                 = "bmu-${var.env_name}-fakecspace"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "fakecspace" {
  count      = var.simulated_cspace ? 1 : 0
  repository = aws_ecr_repository.fakecspace[0].name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 3 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
      action       = { type = "expire" }
    }]
  })
}

output "repository_url" {
  description = "Where ./bmu aws deploy pushes the image."
  value       = aws_ecr_repository.app.repository_url
}

output "fakecspace_repository_url" {
  description = "Where ./bmu aws deploy pushes the simulated CollectionSpace's image; empty without it."
  value       = var.simulated_cspace ? aws_ecr_repository.fakecspace[0].repository_url : ""
}
