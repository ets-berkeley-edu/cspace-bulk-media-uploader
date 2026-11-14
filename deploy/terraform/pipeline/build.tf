# The builds (BP2): two CodeBuild projects, plan and apply, on ARM Linux with Docker (privileged, for the ARM images),
# outside any VPC. Each checks out the public repository at the commit being deployed, with no connection or token, and
# runs its buildspec (deploy/pipeline/), which runs ./bmu aws pipeline-plan or pipeline-apply. One build at a time per
# project.

locals {
  state_bucket = "bmu-tfstate-${var.account_id}-${var.region}"
  settings_arn = "arn:${local.partition}:ssm:${var.region}:${var.account_id}:parameter/bmu-${var.env_name}/settings/*"
}

resource "aws_cloudwatch_log_group" "build" {
  name              = "/pipeline/bmu-${var.environment}" # not /bmu/...: the deployer policy may delete those
  retention_in_days = 365                                # every plan a reviewer read, and every apply
}

# The saved plans: written by the plan build, applied by the apply build. They hold the environment's settings
# (addresses, IDs) but no secret. Disposable: deleted after 7 days, and with the bucket.
resource "aws_s3_bucket" "plans" {
  bucket        = "${local.name}-plans-${var.account_id}-${var.region}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "plans" {
  bucket                  = aws_s3_bucket.plans.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "plans" {
  bucket = aws_s3_bucket.plans.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "plans" {
  bucket = aws_s3_bucket.plans.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "plans" {
  bucket = aws_s3_bucket.plans.id
  rule {
    id     = "plans-expire"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
  }
}

resource "aws_s3_bucket_policy" "plans" {
  bucket = aws_s3_bucket.plans.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "OnlyTls"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.plans.arn, "${aws_s3_bucket.plans.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.plans]
}

# The build's role: the deployer policy, exactly the parts Operations attaches to the deployer, and the pipeline's own
# needs. Only the two projects may use it.
resource "aws_iam_role" "build" {
  name = "${local.name}-build"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.account_id }
        ArnLike      = { "aws:SourceArn" = values(local.project_arn) }
      }
    }]
  })
}

resource "aws_iam_policy" "part" {
  count  = length(var.policy_parts)
  name   = "${local.name}-build-${count.index + 1}"
  policy = var.policy_parts[count.index]
}

resource "aws_iam_role_policy_attachment" "part" {
  count      = length(var.policy_parts)
  role       = aws_iam_role.build.name
  policy_arn = aws_iam_policy.part[count.index].arn
}

# The simulated CollectionSpace's private DNS name needs Route 53, which the deployer policy doesn't have
# (deploy/iam/README.md, Not covered): only an environment with the simulator gets it, as the rehearsal's deployer does.
resource "aws_iam_role_policy" "simulator_dns" {
  count  = var.simulated_cspace ? 1 : 0
  name   = "simulator-dns"
  role   = aws_iam_role.build.id
  policy = file("${path.module}/../../iam/bmu-simulator-dns-policy.json")
}

resource "aws_iam_role_policy" "build" {
  name = "pipeline"
  role = aws_iam_role.build.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ItsLog"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.build.arn}:*"
      },
      {
        Sid      = "SavedPlans"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.plans.arn, "${aws_s3_bucket.plans.arn}/*"]
      },
      {
        Sid      = "ItsSettings"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = local.settings_arn
      },
      {
        # Secret values never pass through a build (BP10): it needs only their metadata. Holds whatever a build runs.
        Sid      = "NoSecretValues"
        Effect   = "Deny"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecretVersionStage"]
        Resource = "*"
      },
      {
        # The settings, the account confirmed for UC Berkeley data and RUNNING among them, are an administrator's.
        Sid      = "NoParameterChanges"
        Effect   = "Deny"
        Action   = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters", "ssm:LabelParameterVersion"]
        Resource = "*"
      },
      {
        # The pipeline's own state, the rehearsal's and CI's role's are the administrator's.
        Sid    = "NotTheAdministratorsState"
        Effect = "Deny"
        Action = ["s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource = [
          "arn:${local.partition}:s3:::${local.state_bucket}/bmu/*/pipeline.tfstate*",
          "arn:${local.partition}:s3:::${local.state_bucket}/bmu/*/rehearsal.tfstate*",
          "arn:${local.partition}:s3:::${local.state_bucket}/bmu/ci/*",
        ]
      },
    ]
  })
}

resource "aws_codebuild_project" "build" {
  for_each               = local.project_arn
  name                   = "${local.name}-${each.key}"
  description            = "The BMU's ${var.environment}: the ${each.key} build (deploy/pipeline/buildspec-${each.key}.yml)."
  service_role           = aws_iam_role.build.arn
  build_timeout          = 60
  queued_timeout         = 30
  concurrent_build_limit = 1

  source {
    type            = "GITHUB"
    location        = "https://github.com/${var.repository}.git"
    git_clone_depth = 0 # the whole history: the build checks the commit is on main
    buildspec       = "deploy/pipeline/buildspec-${each.key}.yml"
  }
  source_version = "main"

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type                        = "ARM_CONTAINER"
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = var.codebuild_image
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true # Docker builds the images

    environment_variable {
      name  = "BMU_AWS_ENV"
      value = var.environment
    }
    environment_variable {
      name  = "PIPELINE_PLANS"
      value = aws_s3_bucket.plans.bucket
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.build.name
      stream_name = each.key
    }
    s3_logs {
      status = "DISABLED"
    }
  }

  depends_on = [aws_iam_role_policy.build, aws_iam_role_policy_attachment.part]
}
