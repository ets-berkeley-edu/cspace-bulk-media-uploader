# The design's key policies (Authentication: Envelope encryption): the session key is used only by the web role; the
# job key encrypts for the web role and decrypts for the worker role only. The account can manage the two keys (and
# delete them) but not use them or grant their use (no kms:CreateGrant), so an administrator can't decrypt a saved
# password without first changing the key policy, which CloudTrail records.

locals {
  key_admin_actions = [
    "kms:CreateAlias", "kms:Describe*", "kms:Enable*", "kms:List*", "kms:Put*", "kms:Update*", "kms:Revoke*",
    "kms:Disable*", "kms:Get*", "kms:Delete*", "kms:TagResource", "kms:UntagResource",
    "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion", "kms:RotateKeyOnDemand",
  ]
  account_root = "arn:${local.partition}:iam::${local.account_id}:root"
}

data "aws_iam_policy_document" "session_key" {
  statement {
    sid       = "AccountManagesTheKeyButCannotUseIt"
    actions   = local.key_admin_actions
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.account_root]
    }
  }

  statement {
    sid       = "WebAppEncryptsAndDecryptsSessions"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.web.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:purpose"
      values   = ["session"]
    }
  }
}

resource "aws_kms_key" "session" {
  description             = "BMU ${var.env_name} - encrypts passwords in sign-in sessions"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.session_key.json
}

resource "aws_kms_alias" "session" {
  name          = "alias/${local.name}-session"
  target_key_id = aws_kms_key.session.key_id
}

data "aws_iam_policy_document" "job_key" {
  statement {
    sid       = "AccountManagesTheKeyButCannotUseIt"
    actions   = local.key_admin_actions
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.account_root]
    }
  }

  statement {
    sid       = "WebAppEncryptsOnly"
    actions   = ["kms:GenerateDataKey"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.web.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:purpose"
      values   = ["job"]
    }
  }

  statement {
    sid       = "WorkerDecryptsOnly"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.worker.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:purpose"
      values   = ["job"]
    }
  }
}

resource "aws_kms_key" "job" {
  description             = "BMU ${var.env_name} - encrypts each queued job's saved sign-in"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.job_key.json
}

resource "aws_kms_alias" "job" {
  name          = "alias/${local.name}-job"
  target_key_id = aws_kms_key.job.key_id
}

# SSE-KMS for staged files and thumbnails; used through S3 only (the task roles' policies in iam.tf).
data "aws_iam_policy_document" "staging_key" {
  statement {
    sid       = "AccountPoliciesControlUse"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.account_root]
    }
  }
}

resource "aws_kms_key" "staging" {
  description             = "BMU ${var.env_name} - encrypts staged files in S3"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.staging_key.json
}

resource "aws_kms_alias" "staging" {
  name          = "alias/${local.name}-staging"
  target_key_id = aws_kms_key.staging.key_id
}
