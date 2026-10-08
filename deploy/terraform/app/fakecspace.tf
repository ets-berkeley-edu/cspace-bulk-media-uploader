# The simulated CollectionSpace (backend/fakecspace), for an environment without access to a real one
# (SIMULATED_CSPACE=true in its settings; off by default). Nothing here exists when simulated_cspace is false.
#
# One task with its data in memory: a pause, deploy or restart starts it empty, while the BMU's tables keep their
# jobs. The web app and the worker find it by name through a private DNS namespace (Cloud Map), and only they can
# connect to it. Its own image and repository (../registry), so the production image never contains it.

locals {
  # PAHMA's address with the simulator. ./bmu aws passes it as tenants = {pahma = ...} (deploy/aws.sh, sim_url);
  # variables.tf checks it.
  fakecspace_url = "http://fakecspace.${local.name}.internal:8180"
  simulated      = var.simulated_cspace ? 1 : 0
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  count       = local.simulated
  name        = "${local.name}.internal"
  description = "Names inside the BMU's VPC: the simulated CollectionSpace"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "fakecspace" {
  count = local.simulated
  name  = "fakecspace"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main[0].id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

resource "aws_security_group" "fakecspace" {
  count       = local.simulated
  name        = "${local.name}-fakecspace"
  description = "Simulated CollectionSpace. Only the web app and the worker can connect."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-fakecspace" }
}

resource "aws_vpc_security_group_ingress_rule" "fakecspace_from_web" {
  count                        = local.simulated
  security_group_id            = aws_security_group.fakecspace[0].id
  description                  = "From the web app"
  referenced_security_group_id = aws_security_group.web.id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

resource "aws_vpc_security_group_ingress_rule" "fakecspace_from_worker" {
  count                        = local.simulated
  security_group_id            = aws_security_group.fakecspace[0].id
  description                  = "From the worker"
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 8180
  to_port                      = 8180
}

# Out: its image from ECR and its logs (the task has a public IP, like the others, because there's no NAT gateway).
resource "aws_vpc_security_group_egress_rule" "fakecspace_out" {
  count             = local.simulated
  security_group_id = aws_security_group.fakecspace[0].id
  description       = "ECR and CloudWatch Logs"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_cloudwatch_log_group" "fakecspace" {
  count             = local.simulated
  name              = "/bmu/${var.env_name}/fakecspace"
  retention_in_days = 30
}

# No task role: the simulator calls no AWS service. The execution role pulls its image and writes its logs.
resource "aws_ecs_task_definition" "fakecspace" {
  count                    = local.simulated
  family                   = "${local.name}-fakecspace"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  # No command: the image's own, uvicorn on port 8180 (deploy/fakecspace.Dockerfile).
  container_definitions = jsonencode([{
    name         = "fakecspace"
    image        = var.fakecspace_image_uri
    essential    = true
    portMappings = [{ containerPort = 8180, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.fakecspace[0].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "fakecspace"
      }
    }
  }])
}

resource "aws_ecs_service" "fakecspace" {
  count           = local.simulated
  name            = "fakecspace"
  cluster         = aws_ecs_cluster.main.id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.fakecspace[0].arn
  desired_count   = var.running ? 1 : 0
  propagate_tags  = "SERVICE"

  # One copy at a time: its data is in memory, so two would disagree.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  availability_zone_rebalancing      = "DISABLED"
  wait_for_steady_state              = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = true
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.fakecspace[0].id]
  }

  service_registries {
    registry_arn = aws_service_discovery_service.fakecspace[0].arn
  }

  depends_on = [aws_route_table_association.public]
}
