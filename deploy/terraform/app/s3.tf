locals {
  staging_bucket = "${local.name}-staging-${local.account_id}-${var.region}"
  logs_bucket    = "${local.name}-s3-logs-${local.account_id}-${var.region}"
}

# ---- S3 access logs for the staging bucket ------------------------------------------------------------------------
resource "aws_s3_bucket" "logs" {
  bucket        = local.logs_bucket
  force_destroy = !var.protect_data
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # S3 can't deliver access logs to a bucket with SSE-KMS by default
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }
  }
}

data "aws_iam_policy_document" "logs_bucket" {
  statement {
    sid       = "S3ServerAccessLogs"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:s3:::${local.staging_bucket}"]
    }
  }

  statement {
    sid       = "TlsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.logs.arn, "${aws_s3_bucket.logs.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "logs" {
  bucket = aws_s3_bucket.logs.id
  policy = data.aws_iam_policy_document.logs_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.logs]
}

# ---- staging bucket: uploaded files, thumbnails, large runs' audit detail ----------------------------------------------
resource "aws_s3_bucket" "staging" {
  bucket        = local.staging_bucket
  force_destroy = !var.protect_data
}

resource "aws_s3_bucket_ownership_controls" "staging" {
  bucket = aws_s3_bucket.staging.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "staging" {
  bucket = aws_s3_bucket.staging.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.staging.arn
    }
  }
}

# The worker reads the exact version that was checked.
resource "aws_s3_bucket_versioning" "staging" {
  bucket = aws_s3_bucket.staging.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_logging" "staging" {
  bucket = aws_s3_bucket.staging.id

  target_bucket = aws_s3_bucket.logs.id
  target_prefix = "staging/"

  depends_on = [aws_s3_bucket_policy.logs]
}

# Presigned POSTs from the BMU's own address only.
resource "aws_s3_bucket_cors_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id

  cors_rule {
    id              = "browser-uploads"
    allowed_methods = ["POST"]
    allowed_origins = ["https://${aws_cloudfront_distribution.main.domain_name}"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id

  # Large runs' per-row audit detail (Storage.put_audit_detail), kept a year. The task roles can add these files
  # but not delete them; if one is written over, its earlier version is kept for the year too.
  rule {
    id     = "expire-audit-detail"
    status = "Enabled"

    filter {
      prefix = "audit/"
    }

    expiration {
      days = 365
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }

  # The BMU deletes staged files itself, every version (Storage.delete_object; design: Retention and audit). This
  # is the backstop for a version left behind (a file written over, or a delete that couldn't list the versions):
  # gone after a day, with any leftover delete marker. Staged files only, so audit files keep their versions.
  rule {
    id     = "remove-deleted-versions"
    status = "Enabled"

    filter {
      prefix = "staging/"
    }

    expiration {
      expired_object_delete_marker = true
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.staging]
}

data "aws_iam_policy_document" "staging_bucket" {
  statement {
    sid       = "TlsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.staging.arn, "${aws_s3_bucket.staging.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Every PutObject must name SSE-KMS and the staging key: with IfExists, a request that names no encryption is
  # refused too. The browser's uploads and the app's own writes (Storage.put_bytes) both name them.
  statement {
    sid       = "OnlyKmsEncryptedUploads"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.staging.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEqualsIfExists"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid       = "OnlyTheStagingKey"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.staging.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEqualsIfExists"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.staging.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "staging" {
  bucket = aws_s3_bucket.staging.id
  policy = data.aws_iam_policy_document.staging_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.staging]
}
