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

# A staging key per museum (design: One deployment for several museums): SSE-KMS for the museum's staged files,
# thumbnails and audit files, used through S3 only (the task roles' policies in iam.tf; the bucket policy in s3.tf
# makes each museum's prefixes use its key). With S3 Bucket Keys off, S3 asks KMS for each object, with the object's
# ARN as the encryption context: so CloudTrail records every file's use of its museum's key, and the key refuses
# any use for an object outside its museum's prefixes, or outside S3. Deleting a museum's key makes everything of
# that museum unreadable.
locals {
  # The objects each museum's key may encrypt and decrypt: aws:s3:arn in S3's encryption context.
  museum_objects = {
    for m in keys(var.tenants) : m => [
      "arn:${local.partition}:s3:::${local.staging_bucket}/staging/${m}/*",
      "arn:${local.partition}:s3:::${local.staging_bucket}/audit/${m}/*",
    ]
  }
}

data "aws_iam_policy_document" "staging_key" {
  for_each = var.tenants

  statement {
    sid       = "AccountPoliciesControlUse"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.account_root]
    }
  }

  # A missing encryption context (a direct call, not through S3) doesn't match either, so it is refused too.
  statement {
    sid       = "OnlyThisMuseumsObjects"
    effect    = "Deny"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotLike"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = local.museum_objects[each.key]
    }
  }
}

resource "aws_kms_key" "staging" {
  for_each                = var.tenants
  description             = "BMU ${var.env_name} - encrypts ${each.key}'s staged files and audit files in S3"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.staging_key[each.key].json
}

resource "aws_kms_alias" "staging" {
  for_each      = var.tenants
  name          = "alias/${local.name}-staging-${each.key}"
  target_key_id = aws_kms_key.staging[each.key].key_id
}
