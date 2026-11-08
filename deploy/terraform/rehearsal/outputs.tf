# Read by ./bmu aws rehearsal-vpc, which saves vpc_id, app_subnet_ids and lb_subnet_ids in the environment's .local.conf.

output "vpc_id" {
  value = aws_vpc.main.id
}

output "app_subnet_ids" {
  description = "The private subnets, for APP_SUBNET_IDS."
  value       = join(",", aws_subnet.private[*].id)
}

output "lb_subnet_ids" {
  description = "The public subnets, for LB_SUBNET_IDS: the internet-facing load balancer (FRONT_DOOR=alb), as in Operations' VPC."
  value       = join(",", aws_subnet.public[*].id)
}

output "deployer_role_arn" {
  value = aws_iam_role.deployer.arn
}
