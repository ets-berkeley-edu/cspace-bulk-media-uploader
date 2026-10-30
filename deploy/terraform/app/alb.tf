resource "aws_lb" "main" {
  name               = local.name
  internal           = true
  load_balancer_type = "application"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.alb.id]

  idle_timeout               = 120
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "web" {
  name                 = "${local.name}-web"
  vpc_id               = aws_vpc.main.id
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

locals {
  # HTTPS from CloudFront to the load balancer when it has its own certificate (variables.tf, origin_domain).
  origin_tls  = var.origin_domain != ""
  origin_port = local.origin_tls ? 443 : 80
}

resource "aws_lb_listener" "http" {
  count             = local.origin_tls ? 0 : 1
  load_balancer_arn = aws_lb.main.arn
  protocol          = "HTTP"
  port              = 80

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener" "https" {
  count             = local.origin_tls ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  protocol          = "HTTPS"
  port              = 443
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.origin_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
