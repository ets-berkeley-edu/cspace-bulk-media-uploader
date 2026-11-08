locals {
  # The front door (variables.tf, front_door).
  cloudfront = var.front_door == "cloudfront"
  alb        = var.front_door == "alb"

  # The BMU's address: CloudFront's, or the name on the load balancer's certificate.
  app_domain = local.cloudfront ? aws_cloudfront_distribution.main[0].domain_name : var.domain_name

  # HTTPS from CloudFront to the load balancer when it has its own certificate (variables.tf, origin_domain).
  origin_tls  = local.cloudfront && var.origin_domain != ""
  origin_port = local.origin_tls ? 443 : 80
}

# Internal behind CloudFront (its VPC origin reaches it in private subnets); internet-facing in the VPC's public
# subnets with front_door alb.
resource "aws_lb" "main" {
  name               = local.name
  internal           = local.cloudfront
  load_balancer_type = "application"
  subnets            = local.lb_subnet_ids
  security_groups    = [aws_security_group.alb.id]

  idle_timeout               = 120
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "web" {
  name                 = "${local.name}-web"
  vpc_id               = local.vpc_id
  target_type          = "ip"
  protocol             = "HTTP"
  port                 = 8000
  deregistration_delay = 30

  health_check {
    path                = "/api/health"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# Plain HTTP only from CloudFront's VPC origin, inside AWS's network, while the load balancer has no certificate.
resource "aws_lb_listener" "http" {
  count             = local.cloudfront && !local.origin_tls ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  protocol          = "HTTP"
  port              = 80

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

# With front_door alb, the only listener: HTTPS on domain_name, no port 80 at all (not even a redirect).
resource "aws_lb_listener" "https" {
  count             = local.alb || local.origin_tls ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  protocol          = "HTTPS"
  port              = 443
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = local.alb ? var.certificate_arn : var.origin_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
