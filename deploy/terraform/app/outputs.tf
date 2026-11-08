output "url" {
  description = "The BMU's address."
  value       = "https://${local.app_domain}"
}

output "front_door" {
  description = "cloudfront or alb, for ./bmu aws, which refuses to change a deployed environment's front door (deploy/aws.sh, check_front_door)."
  value       = var.front_door
}

output "domain_name" {
  description = "With front_door alb: the BMU's name, whose DNS record points at alb_dns_name. Empty with cloudfront."
  value       = var.domain_name
}

output "cluster_name" {
  description = "The ECS cluster; its services are web and worker."
  value       = aws_ecs_cluster.main.name
}

output "image_uri" {
  description = "The image the services run."
  value       = var.image_uri
}

output "running" {
  description = "Whether the services run (false after ./bmu aws pause)."
  value       = var.running
}

output "tenants" {
  description = "The museums this environment serves, each with its CollectionSpace server."
  value       = var.tenants
}

output "museums" {
  description = "The same as tenants, as \"museum=server museum=server\" for ./bmu aws, which refuses to change a deployed museum's server (deploy/aws.sh, check_museums)."
  value       = join(" ", [for m, url in var.tenants : "${m}=${url}"])
}

output "simulated_cspace" {
  description = "Whether the environment runs the simulated CollectionSpace (fakecspace.tf)."
  value       = var.simulated_cspace
}

output "fakecspace_image_uri" {
  description = "The simulated CollectionSpace's image; empty without it."
  value       = var.fakecspace_image_uri
}

output "allowed_cidrs" {
  description = "Addresses allowed to open the BMU."
  value       = var.allowed_cidrs
}

output "staging_bucket" {
  value = aws_s3_bucket.staging.id
}

output "web_log_group" {
  value = aws_cloudwatch_log_group.web.name
}

output "worker_log_group" {
  value = aws_cloudwatch_log_group.worker.name
}

output "reader_secrets" {
  description = "Each museum's secret holding its read-only CollectionSpace account's sign-in; set with ./bmu aws reader-secret <museum>."
  value       = { for m, secret in aws_secretsmanager_secret.reader : m => secret.name }
}

output "alb_dns_name" {
  description = "The load balancer's DNS name: the target of domain_name's DNS record (front_door alb; Operations adds it), or of origin_domain's CNAME (cloudfront, HTTPS to the internal load balancer)."
  value       = aws_lb.main.dns_name
}
