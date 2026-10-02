# Separate roles for the web app and the worker (design: Concurrency, IAM and security). The session and job keys are
# granted in their key policies (kms.tf), not here.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:ecs:${var.region}:${local.account_id}:*"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "ecs_execution_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Lets ECS pull the image and write the logs; the app's own permissions are the task roles below.
resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_execution_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

locals {
  item_read_write = [
    "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
    "dynamodb:ConditionCheckItem", "dynamodb:Query", "dynamodb:Scan",
    "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
  ]
  read_write_tables = [
    aws_dynamodb_table.main["jobs"].arn,
    "${aws_dynamodb_table.main["jobs"].arn}/index/*",
    aws_dynamodb_table.main["sessions"].arn,
    aws_dynamodb_table.main["credentials"].arn,
  ]
}

# Both roles get the same data permissions in this first round. The prototype's web app also reads staged files (it
# makes TIFF thumbnails, design: Status) and deletes them (deleted documents); in the design those reads belong to
# the thumbnail Lambda. The worker's sweeper also deletes idle sessions.
data "aws_iam_policy_document" "task_data" {
  statement {
    sid       = "JobsSessionsCredentials"
    actions   = local.item_read_write
    resources = local.read_write_tables
  }

  statement {
    sid       = "AuditAddOnly"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.main["audit"].arn]
  }

  # Without it, a missing object reads as 403, not 404.
  statement {
    sid       = "StagingList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.staging.arn]
  }

  statement {
    sid       = "StagingObjects"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.staging.arn}/*"]
  }

  statement {
    sid       = "StagingKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.staging.arn]
  }
}

resource "aws_iam_role" "web" {
  name               = "${local.name}-web"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "web" {
  name   = "bmu-web"
  role   = aws_iam_role.web.id
  policy = data.aws_iam_policy_document.task_data.json
}

resource "aws_iam_role" "worker" {
  name               = "${local.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "bmu-worker"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.task_data.json
}
