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
  description = "IPv4 addresses or CIDR ranges allowed to open the BMU, e.g. [\"203.0.113.7/32\"]. With front_door cloudfront, everyone else gets 403 from CloudFront; with alb, the load balancer's security group admits only these, and the staging bucket takes uploads only from these (s3.tf)."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : can(cidrhost(c, 0)) && !strcontains(c, ":")])
    error_message = "allowed_cidrs needs at least one IPv4 CIDR range, such as 203.0.113.7/32 (IPv6 isn't supported: the distribution is IPv4-only)."
  }

  # With alb, each range is a rule in the load balancer's security group, which holds at most 60 inbound rules.
  validation {
    condition     = var.front_door != "alb" || length(distinct(var.allowed_cidrs)) <= 60
    error_message = "With front_door alb, allowed_cidrs holds at most 60 ranges: each is a rule in the load balancer's security group (AWS's limit is 60)."
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

  # Basic Auth is never sent in the clear (design: Other security notes): only the simulator may be http://.
  validation {
    condition     = var.simulated_cspace || alltrue([for url in values(var.tenants) : startswith(url, "https://")])
    error_message = "Each server in tenants must be https:// (the BMU sends each user's password to it); only the simulated CollectionSpace is http://."
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
  description = "The BMU's own VPC's address range (a /16); not used with vpc_id."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(regex("^10\\.\\d{1,3}\\.0\\.0/16$", var.vpc_cidr))
    error_message = "vpc_cidr must be a 10.x.0.0/16 range."
  }
}

# An existing VPC (network.tf), such as Operations' shared dev/QA VPC. Its IDs identify the account's network, so they
# come from the environment's .local.conf, which isn't committed. Empty: the BMU creates its own VPC (vpc_cidr).
variable "vpc_id" {
  description = "An existing VPC to deploy into, or empty for the BMU's own VPC."
  type        = string
  default     = ""

  validation {
    condition     = var.vpc_id == "" || can(regex("^vpc-[0-9a-f]+$", var.vpc_id))
    error_message = "vpc_id must be a VPC's ID, such as vpc-0123456789abcdef0, or empty."
  }
}

variable "app_subnet_ids" {
  description = "With vpc_id: the private subnets the tasks run in, behind the VPC's NAT gateway, in at least two zones."
  type        = list(string)
  default     = []

  validation {
    condition     = var.vpc_id == "" ? length(var.app_subnet_ids) == 0 : length(var.app_subnet_ids) >= 2
    error_message = "With vpc_id, app_subnet_ids needs at least two subnets, in different zones; without it, none."
  }

  validation {
    condition     = alltrue([for s in var.app_subnet_ids : can(regex("^subnet-[0-9a-f]+$", s))])
    error_message = "Each of app_subnet_ids must be a subnet's ID, such as subnet-0123456789abcdef0."
  }
}

variable "lb_subnet_ids" {
  description = "With vpc_id: the load balancer's subnets, in at least two zones: private ones for front_door cloudfront (an internal load balancer; empty: the app subnets), public ones for alb (internet-facing; required)."
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.lb_subnet_ids) == 0 || (var.vpc_id != "" && length(var.lb_subnet_ids) >= 2)
    error_message = "lb_subnet_ids needs vpc_id, and at least two subnets in different zones (or none, for the app subnets)."
  }

  validation {
    condition     = alltrue([for s in var.lb_subnet_ids : can(regex("^subnet-[0-9a-f]+$", s))])
    error_message = "Each of lb_subnet_ids must be a subnet's ID, such as subnet-0123456789abcdef0."
  }
}

variable "create_gateway_endpoints" {
  description = "With vpc_id: true adds S3 and DynamoDB gateway endpoints to the app subnets' route tables; false where the VPC has them already. (The BMU's own VPC always has them.)"
  type        = bool
  default     = false

  validation {
    condition     = !var.create_gateway_endpoints || var.vpc_id != ""
    error_message = "create_gateway_endpoints is for an existing VPC (vpc_id); the BMU's own VPC always has them."
  }
}

variable "protect_data" {
  description = "true for an environment whose data matters: the tables can't be deleted, and the buckets can't be destroyed while they hold objects. false lets ./bmu aws destroy remove everything."
  type        = bool
  default     = false
}

variable "simulated_cspace" {
  description = "true runs the simulated CollectionSpace (the fakecspace package) in the environment, and the BMU uses it (fakecspace.tf). For trying the BMU without a CollectionSpace account; never for data that matters."
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

# HTTPS from CloudFront to the load balancer (review 5.2), with front_door cloudfront only. The VPC origin keeps that hop inside AWS's network, but it
# is plain HTTP until the load balancer has a certificate, which needs a domain name the team controls (the load
# balancer's own *.elb.amazonaws.com name can't get one). Set both to turn it on: then the load balancer listens on
# 443 only, with that certificate, and CloudFront connects with HTTPS only and checks the certificate against
# origin_domain. origin_domain needs a DNS record (CNAME) pointing to the load balancer (output alb_dns_name).
# The front door (design: AWS deployment). cloudfront: CloudFront (HTTPS at a *.cloudfront.net address, the IP
# allowlist in a CloudFront function) in front of an internal load balancer, as in a personal account. alb: no
# CloudFront (UC Berkeley's account, stage 2): an internet-facing load balancer in the VPC's public subnets, HTTPS
# only on domain_name with an ACM certificate (../registry), its security group admitting allowed_cidrs, and the
# regional WAF (waf.tf). A deployed environment's front door never changes: ./bmu aws refuses it (destroy first).
variable "front_door" {
  description = "cloudfront or alb (see above)."
  type        = string
  default     = "cloudfront"

  validation {
    condition     = contains(["cloudfront", "alb"], var.front_door)
    error_message = "front_door must be cloudfront or alb."
  }

  # The BMU's own VPC has no public subnets for a load balancer: alb goes in an existing VPC's (network.tf).
  validation {
    condition     = var.front_door != "alb" || (var.vpc_id != "" && length(var.lb_subnet_ids) >= 2)
    error_message = "front_door alb needs vpc_id and lb_subnet_ids: the VPC's public subnets, in two zones, for the internet-facing load balancer."
  }
}

variable "domain_name" {
  description = "With front_door alb: the BMU's name, such as bmu-qa.example.berkeley.edu, matching certificate_arn. Its DNS record (Operations') points at the load balancer (output alb_dns_name). Empty with cloudfront."
  type        = string
  default     = ""

  validation {
    condition     = (var.domain_name != "") == (var.front_door == "alb")
    error_message = "domain_name is needed with front_door alb, and only then."
  }

  validation {
    condition     = var.domain_name == "" || can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.domain_name))
    error_message = "domain_name must be a domain name alone, in lowercase, such as bmu-qa.example.berkeley.edu."
  }
}

variable "certificate_arn" {
  description = "With front_door alb: domain_name's ACM certificate, in the environment's region (../registry, output certificate_arn). Empty with cloudfront."
  type        = string
  default     = ""

  validation {
    condition     = (var.certificate_arn != "") == (var.front_door == "alb")
    error_message = "certificate_arn is needed with front_door alb, and only then."
  }

  validation {
    condition     = var.certificate_arn == "" || can(regex("^arn:aws[a-z-]*:acm:[a-z0-9-]+:[0-9]{12}:certificate/", var.certificate_arn))
    error_message = "certificate_arn must be an ACM certificate's ARN."
  }
}

variable "origin_domain" {
  description = "The load balancer's own domain name, matching origin_certificate_arn, e.g. bmu-dev-origin.example.berkeley.edu. Empty: CloudFront reaches the load balancer with HTTP inside AWS's network."
  type        = string
  default     = ""

  validation {
    condition     = var.origin_domain == "" || var.front_door == "cloudfront"
    error_message = "origin_domain is for front_door cloudfront only: with alb, the load balancer's name is domain_name."
  }

  validation {
    condition     = var.origin_domain == "" || can(regex("^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", var.origin_domain))
    error_message = "origin_domain must be a domain name alone, in lowercase, such as bmu-dev-origin.example.berkeley.edu."
  }
}

variable "origin_certificate_arn" {
  description = "An ACM certificate in the environment's region for origin_domain (DNS-validated). Set with origin_domain, or leave both empty."
  type        = string
  default     = ""

  validation {
    condition     = (var.origin_certificate_arn == "") == (var.origin_domain == "")
    error_message = "Set origin_domain and origin_certificate_arn together, or neither."
  }

  validation {
    condition     = var.origin_certificate_arn == "" || can(regex("^arn:aws[a-z-]*:acm:[a-z0-9-]+:[0-9]{12}:certificate/", var.origin_certificate_arn))
    error_message = "origin_certificate_arn must be an ACM certificate's ARN."
  }
}

variable "waf_enabled" {
  description = "true puts a regional AWS WAF on the load balancer, with front_door alb only (waf.tf; about $10 a month plus $0.60 per million requests). ./bmu aws turns it on with PROTECT_DATA there unless WAF_ENABLED says otherwise."
  type        = bool
  default     = false

  validation {
    condition     = !var.waf_enabled || var.front_door == "alb"
    error_message = "waf_enabled is for front_door alb only: a CloudFront environment has no WAF."
  }
}

variable "waf_managed_rules" {
  description = "What AWS's managed rule sets in the WAF do with a match: count (log it only; the first week) or block."
  type        = string
  default     = "count"

  validation {
    condition     = contains(["count", "block"], var.waf_managed_rules)
    error_message = "waf_managed_rules must be count or block."
  }
}

variable "waf_login_limit" {
  description = "Sign-in requests one address may make in 5 minutes before the WAF blocks it (AWS's minimum is 10)."
  type        = number
  default     = 20

  validation {
    condition     = var.waf_login_limit >= 10
    error_message = "waf_login_limit must be at least 10 (AWS's minimum for a rate rule)."
  }
}

variable "waf_request_limit" {
  description = "Requests of any kind one address may make in 5 minutes before the WAF blocks it. The editor polls and checks, so keep it generous."
  type        = number
  default     = 3000

  validation {
    condition     = var.waf_request_limit >= 100
    error_message = "waf_request_limit must be at least 100: the editor alone makes many requests."
  }
}
