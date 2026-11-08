# AWS WAF on the load balancer, regional, with front_door alb only (review 4.2 and 5; variables.tf, waf_enabled; BQ26,
# BQ28). CollectionSpace doesn't lock an account after failed sign-ins, so the BMU must not become a way to guess
# passwords: the web app limits failed sign-ins per username (backend/bmu/app.py, _sign_in), and this limits them per
# address, before they reach the app. A second rule limits every request per address. Both count over 5 minutes, by
# source address (users reach the load balancer directly: no proxy in front), and block the address while it is over.
# AWS's IP reputation, common and known-bad-inputs rule sets run in count mode first (waf_managed_rules): switch to
# block after a week of logs. Logs keep the path and redact the query string and the Cookie header (the session).
# Off by default for throwaway environments; ./bmu aws turns it on with PROTECT_DATA unless WAF_ENABLED says otherwise.

locals {
  # Priority 3 onwards, after the two rate rules.
  waf_managed_rule_sets = [
    { name = "ip-reputation", group = "AWSManagedRulesAmazonIpReputationList" },
    { name = "common", group = "AWSManagedRulesCommonRuleSet" },
    { name = "known-bad-inputs", group = "AWSManagedRulesKnownBadInputsRuleSet" },
  ]
}

resource "aws_wafv2_web_acl" "main" {
  count = var.waf_enabled ? 1 : 0
  name  = local.name
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "sign-in-rate"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit                 = var.waf_login_limit
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"

        scope_down_statement {
          byte_match_statement {
            search_string         = "/api/login"
            positional_constraint = "STARTS_WITH"

            field_to_match {
              uri_path {}
            }

            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-sign-in-rate"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "request-rate"
    priority = 2

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit                 = var.waf_request_limit
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-request-rate"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = local.waf_managed_rule_sets

    content {
      name     = rule.value.name
      priority = 3 + rule.key

      override_action {
        dynamic "count" {
          for_each = var.waf_managed_rules == "count" ? [1] : []
          content {}
        }

        dynamic "none" {
          for_each = var.waf_managed_rules == "block" ? [1] : []
          content {}
        }
      }

      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = rule.value.group

          # Saving a job's documents can send more than the rule set's 8 KB body limit (as Serena's uploads).
          dynamic "rule_action_override" {
            for_each = rule.value.group == "AWSManagedRulesCommonRuleSet" ? [1] : []

            content {
              name = "SizeRestrictions_BODY"

              action_to_use {
                count {}
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${local.name}-${rule.value.name}"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  count        = var.waf_enabled ? 1 : 0
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main[0].arn
}

# WAF's log group's name must start with aws-waf-logs-.
resource "aws_cloudwatch_log_group" "waf" {
  count             = var.waf_enabled ? 1 : 0
  name              = "aws-waf-logs-${local.name}"
  retention_in_days = 30
}

data "aws_iam_policy_document" "waf_logs" {
  count = var.waf_enabled ? 1 : 0

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.waf[0].arn}:*"]

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:logs:${var.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_cloudwatch_log_resource_policy" "waf" {
  count           = var.waf_enabled ? 1 : 0
  policy_name     = "${local.name}-waf-logs"
  policy_document = data.aws_iam_policy_document.waf_logs[0].json
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  count                   = var.waf_enabled ? 1 : 0
  resource_arn            = aws_wafv2_web_acl.main[0].arn
  log_destination_configs = [aws_cloudwatch_log_group.waf[0].arn]

  redacted_fields {
    query_string {}
  }

  redacted_fields {
    single_header {
      name = "cookie"
    }
  }

  depends_on = [aws_cloudwatch_log_resource_policy.waf]
}
