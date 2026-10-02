# The tables Storage.create_tables makes locally: the same keys, index and TTL (backend/tests/test_deploy.py checks).
# The two tables that hold encrypted passwords get no point-in-time recovery (design: no backups of passwords).

locals {
  tables = {
    jobs = {
      hash_key   = "PK"
      range_key  = "SK"
      attributes = { PK = "S", SK = "S", tenant = "S", created = "N" }
      gsi        = { name = "tenant", hash_key = "tenant", range_key = "created" }
      ttl        = false
      pitr       = true
    }
    sessions = {
      hash_key   = "PK"
      range_key  = null
      attributes = { PK = "S" }
      gsi        = null
      ttl        = true
      pitr       = false
    }
    credentials = {
      hash_key   = "PK"
      range_key  = null
      attributes = { PK = "S" }
      gsi        = null
      ttl        = true
      pitr       = false
    }
    audit = {
      hash_key   = "PK"
      range_key  = "SK"
      attributes = { PK = "S", SK = "S" }
      gsi        = null
      ttl        = true # entries are kept 365 days
      pitr       = true
    }
  }
}

resource "aws_dynamodb_table" "main" {
  for_each = local.tables

  name                        = "${local.name}-${each.key}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = each.value.hash_key
  range_key                   = each.value.range_key
  deletion_protection_enabled = var.protect_data

  dynamic "attribute" {
    for_each = each.value.attributes

    content {
      name = attribute.key
      type = attribute.value
    }
  }

  dynamic "global_secondary_index" {
    for_each = each.value.gsi == null ? [] : [each.value.gsi]

    content {
      name            = global_secondary_index.value.name
      projection_type = "ALL"

      key_schema {
        attribute_name = global_secondary_index.value.hash_key
        key_type       = "HASH"
      }

      key_schema {
        attribute_name = global_secondary_index.value.range_key
        key_type       = "RANGE"
      }
    }
  }

  dynamic "ttl" {
    for_each = each.value.ttl ? [1] : []

    content {
      attribute_name = "expires"
      enabled        = true
    }
  }

  point_in_time_recovery {
    enabled = each.value.pitr
  }
}
