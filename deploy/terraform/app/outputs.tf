output "url" {
  description = "The BMU's address."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
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
