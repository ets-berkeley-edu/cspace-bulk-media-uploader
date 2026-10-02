resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "BMU load balancer. The CloudFront VPC origin connects from inside the VPC."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_vpc" {
  security_group_id = aws_security_group.alb.id
  description       = "CloudFront VPC origin"
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

# The only way out of the load balancer: the web app's port.
resource "aws_vpc_security_group_egress_rule" "alb_to_web" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To the web app"
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_security_group" "web" {
  name        = "${local.name}-web"
  description = "BMU web app tasks. Only the load balancer can connect."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-web" }
}

resource "aws_vpc_security_group_ingress_rule" "web_from_alb" {
  security_group_id            = aws_security_group.web.id
  description                  = "From the load balancer"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_egress_rule" "web_out" {
  security_group_id = aws_security_group.web.id
  description       = "CollectionSpace and AWS services"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "BMU worker tasks. Nothing can connect to them (no inbound rules)."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-worker" }
}

resource "aws_vpc_security_group_egress_rule" "worker_out" {
  security_group_id = aws_security_group.worker.id
  description       = "CollectionSpace and AWS services"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
