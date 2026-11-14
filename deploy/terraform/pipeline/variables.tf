variable "account_id" {
  description = "The environment's AWS account; Terraform refuses to run against any other."
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

variable "environment" {
  description = "The ./bmu aws environment (personal-rehearsal, ucb-qa): the GitHub environments' names (<environment>-plan and <environment>) and the pipeline's (pipeline-bmu-<environment>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,19}$", var.environment))
    error_message = "environment must be 2 to 20 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "env_name" {
  description = "The environment's BMU_ENV_NAME: its settings in SSM (/bmu-<env_name>/settings/) and its Terraform state (bmu/<env_name>/)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "repository" {
  description = "The GitHub repository whose deploy workflow may start the builds, and which the builds check out (public: no credentials)."
  type        = string
  default     = "ets-berkeley-edu/cspace-bulk-media-uploader"
}

variable "github_subject" {
  description = "The start of the sub claim in GitHub's OIDC tokens for the repository, before :environment:<name>: repo:<owner>/<name>, or repo:<owner>@<id>/<name>@<id> with immutable subjects. ./bmu aws pipeline reads it from GitHub."
  type        = string

  validation {
    condition     = can(regex("^repo:[^:*?]+$", var.github_subject))
    error_message = "github_subject must be repo: and the repository, as GitHub names it, with no colon or wildcard."
  }
}

variable "create_oidc_provider" {
  description = "true makes GitHub's OIDC provider; false uses the account's own (there can be only one, BP9). ./bmu aws pipeline decides."
  type        = bool
}

# The parts exactly as Operations attaches them to the deployer: ./bmu aws makes them with
# deploy/iam/split-policy.py --json, as for the rehearsal's deployer, so the build has the same permissions.
variable "policy_parts" {
  description = "The deployer policy's parts, each a policy document (JSON), from deploy/iam/split-policy.py --json."
  type        = list(string)

  validation {
    condition     = length(var.policy_parts) >= 1 && length(var.policy_parts) <= 9
    error_message = "policy_parts needs 1 to 9 policy documents (IAM attaches at most 10 managed policies to a role, and the build role has one inline)."
  }

  validation {
    condition     = alltrue([for p in var.policy_parts : length(p) <= 6144 && can(jsondecode(p).Statement)])
    error_message = "Each of policy_parts is a policy document of at most 6,144 characters (deploy/iam/split-policy.py)."
  }
}

variable "simulated_cspace" {
  description = "true where the environment runs the simulated CollectionSpace: the build then also gets bmu-simulator-dns-policy.json (its private DNS name), as the rehearsal's deployer does. Never in UC Berkeley's account."
  type        = bool
  default     = false
}

variable "codebuild_image" {
  description = "The CodeBuild image, by its versioned name: Amazon Linux 2023 on ARM, with Docker, Python 3 and the AWS CLI."
  type        = string
  default     = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
}
