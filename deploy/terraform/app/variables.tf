variable "account_id" {
  description = "The AWS account this environment belongs to; Terraform refuses to run against any other."
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
  description = "Environment name within the account, used in every resource name (bmu-<env>-...)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.env_name))
    error_message = "env_name must be 2 to 16 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "image_uri" {
  description = "The image both services run, <repository URL>:<tag> (./bmu aws deploy builds and pushes it)."
  type        = string
}

variable "allowed_cidrs" {
  description = "IPv4 addresses or CIDR ranges allowed to open the BMU, e.g. [\"203.0.113.7/32\"]. Everyone else gets 403 from CloudFront."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "allowed_cidrs needs at least one IPv4 CIDR range, such as 203.0.113.7/32 (IPv6 isn't supported: the distribution is IPv4-only)."
  }
}

variable "cspace_url" {
  description = "CollectionSpace server, without /cspace-services."
  type        = string
  default     = "https://pahma.qa.collectionspace.org"
}

variable "tenant" {
  description = "The BMU tenant configuration to load."
  type        = string
  default     = "pahma"
}

variable "env_label" {
  description = "Shown on the sign-in page, in the header and in the browser tab's title."
  type        = string
  default     = "AWS · dev · PAHMA QA"
}

variable "always_run_time" {
  description = "true makes every moment a run time, so queued jobs start at once (testing only)."
  type        = bool
  default     = false
}

variable "running" {
  description = "false stops both services (./bmu aws pause) to save money; the data stays."
  type        = bool
  default     = true
}

variable "vpc_cidr" {
  description = "The VPC's address range (a /16)."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(regex("^10\\.\\d{1,3}\\.0\\.0/16$", var.vpc_cidr))
    error_message = "vpc_cidr must be a 10.x.0.0/16 range."
  }
}

variable "protect_data" {
  description = "true for an environment whose data matters: the tables can't be deleted, and the buckets can't be destroyed while they hold objects. false lets ./bmu aws destroy remove everything."
  type        = bool
  default     = false
}
