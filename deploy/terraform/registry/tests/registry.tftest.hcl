# terraform test (run from deploy/terraform/registry after terraform init -backend=false). Plans against a simulated
# AWS provider: nothing is created and no sign-in is needed.

mock_provider "aws" {}

variables {
  account_id = "123456789012"
  region     = "us-west-2"
  env_name   = "stage2"
}

run "no_certificate_without_a_domain" {
  command = plan

  assert {
    condition     = length(aws_acm_certificate.app) == 0 && output.certificate_arn == ""
    error_message = "Without domain_name (front_door cloudfront) there is no certificate."
  }
}

run "a_dns_validated_certificate_for_the_domain" {
  command = plan

  variables {
    domain_name = "bmu-qa.example.berkeley.edu"
  }

  assert {
    condition     = aws_acm_certificate.app[0].domain_name == "bmu-qa.example.berkeley.edu" && aws_acm_certificate.app[0].validation_method == "DNS"
    error_message = "With domain_name, the certificate is for it and validated by DNS (Operations adds the record)."
  }
}

run "a_domain_with_a_scheme_is_refused" {
  command = plan

  variables {
    domain_name = "https://bmu-qa.example.berkeley.edu"
  }

  expect_failures = [var.domain_name]
}
