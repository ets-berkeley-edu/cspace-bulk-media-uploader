resource "aws_cloudwatch_log_group" "web" {
  name              = "/bmu/${var.env_name}/web"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/bmu/${var.env_name}/worker"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "main" {
  name = local.name
}

locals {
  # The app's settings (backend/bmu/config.py); backend/tests/test_deploy.py checks that each one exists.
  app_environment = {
    BMU_CSPACE_URL         = var.cspace_url
    BMU_TENANT             = var.tenant
    BMU_ENV_LABEL          = var.env_label
    BMU_AWS_REGION         = var.region
    BMU_TABLE_PREFIX       = local.name
    BMU_S3_BUCKET          = aws_s3_bucket.staging.id
    BMU_S3_KMS_KEY_ID      = aws_kms_key.staging.arn
    BMU_CRYPTO_MODE        = "kms"
    BMU_KMS_SESSION_KEY_ID = aws_kms_key.session.arn
    BMU_KMS_JOB_KEY_ID     = aws_kms_key.job.arn
    BMU_COOKIE_SECURE      = "true"
    BMU_ALWAYS_RUN_TIME    = tostring(var.always_run_time)
    BMU_DEMO               = "false" # never in AWS
    BMU_READER_SECRET_ID   = aws_secretsmanager_secret.reader.arn # only the web role may read it (iam.tf)
  }
  container_environment = [for name, value in local.app_environment : { name = name, value = value }]
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.web.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  # No command: the image's own, uvicorn on port 8000.
  container_definitions = jsonencode([{
    name         = "web"
    image        = var.image_uri
    essential    = true
    environment  = local.container_environment
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.web.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "web"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048 # files up to 2 GB are streamed through it (the web app makes the TIFF thumbnails)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.image_uri
    essential   = true
    command     = ["python", "-m", "bmu.worker"]
    stopTimeout = 120
    environment = local.container_environment
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.main.id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = var.running ? 1 : 0
  propagate_tags  = "SERVICE"

  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  wait_for_steady_state              = true # apply finishes when the new tasks are healthy, or fails

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = true
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.web.id]
  }

  load_balancer {
    container_name   = "web"
    container_port   = 8000
    target_group_arn = aws_lb_target_group.web.arn
  }

  depends_on = [aws_lb_listener.http, aws_iam_role_policy.web, aws_route_table_association.public]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  launch_type     = "FARGATE"
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.running ? 1 : 0
  propagate_tags  = "SERVICE"

  # One worker at a time: the old one stops before the new one starts. (Zone rebalancing needs room to start a
  # second task, so it is off.)
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
    security_groups  = [aws_security_group.worker.id]
  }

  depends_on = [aws_iam_role_policy.worker, aws_route_table_association.public]
}
