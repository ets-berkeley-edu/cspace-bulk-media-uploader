# AWS WAF in front of CloudFront (review 4.2 and 5; variables.tf, waf_enabled). CollectionSpace doesn't lock an account
# after failed sign-ins, so the BMU must not become a way to guess passwords: the web app limits failed sign-ins per
# username (backend/bmu/app.py, _sign_in), and this limits them per address, before they reach the app. A second
# rule limits every request per address. Both count over 5 minutes and block the address while it is over.
# CloudFront's WAF lives in us-east-1. Off by default for throwaway environments; ./bmu aws turns it on with
# PROTECT_DATA.

resource "aws_wafv2_web_acl" "main" {
  count    = var.waf_enabled ? 1 : 0
  provider = aws.us_east_1
  name     = local.name
  scope    = "CLOUDFRONT"

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

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}
