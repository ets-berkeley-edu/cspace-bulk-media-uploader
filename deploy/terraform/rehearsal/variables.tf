variable "account_id" {
  description = "The developer's own AWS account; Terraform refuses to run against any other."
  type        = string

  validation {
    condition     = can(regex("^\\d{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account number."
  }
}

variable "region" {
  description = "AWS region."
  type        = string
}

variable "env_name" {
  description = "The rehearsal environment's BMU_ENV_NAME, in the VPC's and the deployer's names (rehearsal-<env>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "vpc_cidr" {
  description = "The VPC's range: a /16, split into two public and two private /20 subnets. Not the BMU's own VPC's (10.40.0.0/16)."
  type        = string
  default     = "10.43.0.0/16"
}

# The parts exactly as Operations attaches them: ./bmu aws makes them with deploy/iam/split-policy.py --json, so the
# rehearsal tries the same managed policies, not another split of the same policy.
variable "policy_parts" {
  description = "The deployer policy's parts, each a policy document (JSON), from deploy/iam/split-policy.py --json."
  type        = list(string)

  validation {
    condition     = length(var.policy_parts) >= 1 && length(var.policy_parts) <= 10
    error_message = "policy_parts needs 1 to 10 policy documents (IAM attaches at most 10 managed policies to a role)."
  }

  validation {
    condition     = alltrue([for p in var.policy_parts : length(p) <= 6144 && can(jsondecode(p).Statement)])
    error_message = "Each of policy_parts is a policy document of at most 6,144 characters (deploy/iam/split-policy.py)."
  }
}
