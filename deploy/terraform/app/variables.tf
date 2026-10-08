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

variable "tenants" {
  description = "The museums (CollectionSpace tenants) this environment serves, each with its CollectionSpace server: {pahma = \"https://pahma.qa.collectionspace.org\"}. Each needs backend/bmu/tenants/<museum>.yaml (./bmu aws checks)."
  type        = map(string)

  validation {
    condition     = length(var.tenants) > 0
    error_message = "tenants needs at least one museum."
  }

  validation {
    condition     = alltrue([for m in keys(var.tenants) : can(regex("^[a-z][a-z0-9]{1,19}$", m))])
    error_message = "Each museum's name in tenants is 2 to 20 lowercase letters or digits, starting with a letter (it is part of key aliases, secret names and S3 prefixes)."
  }

  validation {
    condition     = alltrue([for url in values(var.tenants) : can(regex("^https?://[A-Za-z0-9.-]+(:[0-9]+)?$", url))])
    error_message = "Each server in tenants must be an address alone, such as https://pahma.qa.collectionspace.org (no path, no trailing /)."
  }

  validation {
    condition     = !var.simulated_cspace || var.tenants == tomap({ pahma = "http://fakecspace.bmu-${var.env_name}.internal:8180" })
    error_message = "With simulated_cspace, tenants must be the simulator's PAHMA alone: {pahma = \"http://fakecspace.bmu-<env_name>.internal:8180\"} (fakecspace.tf)."
  }
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

variable "simulated_cspace" {
  description = "true runs the simulated CollectionSpace (backend/fakecspace) in the environment, and the BMU uses it (fakecspace.tf). For trying the BMU without a CollectionSpace account; never for data that matters."
  type        = bool
  default     = false

  validation {
    condition     = !(var.simulated_cspace && var.protect_data)
    error_message = "simulated_cspace can't be used with protect_data: the simulator's data is lost on every restart, and its accounts' passwords are public."
  }
}

variable "fakecspace_image_uri" {
  description = "The simulated CollectionSpace's image, <repository URL>:<tag> (./bmu aws deploy builds and pushes it). Empty when simulated_cspace is false."
  type        = string
  default     = ""

  validation {
    condition     = !var.simulated_cspace || length(var.fakecspace_image_uri) > 0
    error_message = "simulated_cspace needs fakecspace_image_uri."
  }
}

# Task sizes (Fargate: each cpu value allows only some memory values; see the ECS documentation).
variable "web_cpu" {
  description = "The web app's task CPU units (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "web_memory" {
  description = "The web app's task memory in MiB."
  type        = number
  default     = 1024
}

variable "worker_cpu" {
  description = "The worker's task CPU units (1024 = 1 vCPU): it runs one thread per museum (backend/bmu/worker.py)."
  type        = number
  default     = 1024
}

variable "worker_memory" {
  description = "The worker's task memory in MiB. Files up to 2 GB are streamed through it."
  type        = number
  default     = 2048
}
