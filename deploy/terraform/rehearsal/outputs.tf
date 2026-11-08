# Read by ./bmu aws rehearsal-vpc, which saves vpc_id and app_subnet_ids in the environment's .local.conf.

output "vpc_id" {
  value = aws_vpc.main.id
}

output "app_subnet_ids" {
  description = "The private subnets, for APP_SUBNET_IDS (the internal load balancer goes there too)."
  value       = join(",", aws_subnet.private[*].id)
}

output "deployer_role_arn" {
  value = aws_iam_role.deployer.arn
}
