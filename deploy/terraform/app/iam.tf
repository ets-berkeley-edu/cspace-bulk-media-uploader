# Separate roles for the web app and the worker (design: Concurrency, IAM and security).

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

# What each task role may do with the BMU's data (design: Concurrency, IAM and security). Each role gets only the
# actions its code uses; backend/tests/test_deploy.py checks the two lists against this file.
#
#               web app                                   worker
#   jobs        read and write                            read and write
#   sessions    get, put, update, delete                  scan and delete (the sweeper removes idle sessions)
#   credentials put (Submit job) and delete (Edit,        get, delete, condition check (claiming a job)
#               deleting a job); never read
#   audit       put only                                  put only
#   S3 staging/ put (signs uploads, thumbnails),          get and delete
#               get (TIFF thumbnails, until that is a
#               Lambda) and delete (deleted documents)
#   S3 audit/   put only                                  put only
#
# Neither role can delete or read an audit file, or change an audit item. The session and job keys are granted in
# their key policies (kms.tf), not here.
locals {
  jobs_actions = [
    "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
    "dynamodb:ConditionCheckItem", "dynamodb:Query", "dynamodb:Scan",
    "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
  ]
  jobs_resources = [
    aws_dynamodb_table.main["jobs"].arn,
    "${aws_dynamodb_table.main["jobs"].arn}/index/*",
  ]
  staged_objects = "${aws_s3_bucket.staging.arn}/staging/*"
  audit_objects  = "${aws_s3_bucket.staging.arn}/audit/*"
}

# The part both roles share.
data "aws_iam_policy_document" "task_common" {
  statement {
    sid       = "Jobs"
    actions   = local.jobs_actions
    resources = local.jobs_resources
  }

  statement {
    sid       = "AuditAddOnly"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.main["audit"].arn]
  }

  # ListBucket: without it, a missing object reads as 403, not 404. ListBucketVersions: deleting a staged file
  # removes every version of it (Storage.delete_object).
  statement {
    sid       = "StagingList"
    actions   = ["s3:ListBucket", "s3:ListBucketVersions"]
    resources = [aws_s3_bucket.staging.arn]
  }

  # Large runs' per-row detail and big deletions' CSID lists (Storage.put_audit_detail): added, never read or deleted.
  statement {
    sid       = "AuditFilesAddOnly"
    actions   = ["s3:PutObject"]
    resources = [local.audit_objects]
  }

  statement {
    sid       = "StagingKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.staging.arn]
  }
}

data "aws_iam_policy_document" "web" {
  source_policy_documents = [data.aws_iam_policy_document.task_common.json]

  statement {
    sid       = "Sessions"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.main["sessions"].arn]
  }

  # The read-only CollectionSpace account for interns' checks: only the web app reads it, and only this one secret.
  statement {
    sid       = "ReaderSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.reader.arn]
  }

  # Saved with Submit job, deleted on Edit and when a job is deleted. The web app never reads a job's sign-in, and
  # the job key's policy doesn't let it decrypt one.
  statement {
    sid       = "CredentialsPutAndDelete"
    actions   = ["dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.main["credentials"].arn]
  }

  # Put: the uploads it signs for the browser, and thumbnails. Get: TIFF thumbnails and the stored thumbnails (in
  # the design the reads belong to the thumbnail Lambda). Delete: deleted documents and replaced files.
  statement {
    sid       = "StagedFiles"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject", "s3:DeleteObjectVersion"]
    resources = [local.staged_objects]
  }
}

data "aws_iam_policy_document" "worker" {
  source_policy_documents = [data.aws_iam_policy_document.task_common.json]

  # The sweeper removes sessions that are idle or past their limit; the worker never reads one.
  statement {
    sid       = "SessionsSweep"
    actions   = ["dynamodb:Scan", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.main["sessions"].arn]
  }

  statement {
    sid       = "CredentialsReadAndDelete"
    actions   = ["dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:ConditionCheckItem"]
    resources = [aws_dynamodb_table.main["credentials"].arn]
  }

  # It reads staged files to send them to CollectionSpace and deletes them afterwards; it never adds one.
  statement {
    sid       = "StagedFiles"
    actions   = ["s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject", "s3:DeleteObjectVersion"]
    resources = [local.staged_objects]
  }
}

resource "aws_iam_role" "web" {
  name               = "${local.name}-web"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "web" {
  name   = "bmu-web"
  role   = aws_iam_role.web.id
  policy = data.aws_iam_policy_document.web.json
}

resource "aws_iam_role" "worker" {
  name               = "${local.name}-worker"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "bmu-worker"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}
