data "aws_caller_identity" "current" {}

# CloudWatch log group for both services
resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.app_name}/backend"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.app_name}/worker"
  retention_in_days = 30
}

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = var.app_name
  tags = { Name = var.app_name }
}

# ── Backend Task Definition ──────────────────────────────────────────────────

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.app_name}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512   # 0.5 vCPU
  memory                   = 1024  # 1GB

  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name  = "backend"
    image = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"

    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]

    # Secrets injected from Secrets Manager — never in plaintext
    secrets = [
      { name = "DB__PASSWORD",           valueFrom = "${aws_secretsmanager_secret.app.arn}:DB__PASSWORD::" },
      { name = "OPENROUTER_API_KEY",     valueFrom = "${aws_secretsmanager_secret.app.arn}:OPENROUTER_API_KEY::" },
      { name = "GOOGLE_REVIEWS_API_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:GOOGLE_REVIEWS_API_KEY::" },
      { name = "SECRET_KEY",             valueFrom = "${aws_secretsmanager_secret.app.arn}:SECRET_KEY::" },
    ]

    environment = [
      { name = "APP_ENV",        value = "production" },
      { name = "DB__HOST",       value = aws_db_instance.main.address },
      { name = "DB__PORT",       value = tostring(aws_db_instance.main.port) },
      { name = "DB__NAME",       value = "customer_voice_ai" },
      { name = "DB__USERNAME",   value = "postgres" },
      { name = "CELERY__BROKER_URL",      value = "redis://${aws_elasticache_cluster.main.cache_nodes[0].address}:6379/0" },
      { name = "CELERY__RESULT_BACKEND",  value = "redis://${aws_elasticache_cluster.main.cache_nodes[0].address}:6379/1" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "backend"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}

# ── Worker Task Definition ───────────────────────────────────────────────────

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.app_name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024  # 1 vCPU — ML inference needs more CPU
  memory                   = 2048  # 2GB — sentence-transformers model fits here

  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name  = "worker"
    image = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"

    # Override the CMD from Dockerfile — worker runs Celery, not uvicorn
    command = ["celery", "-A", "workers.celery_app", "worker", "--loglevel=INFO", "--autoscale=4,1"]

    secrets = [
      { name = "DB__PASSWORD",           valueFrom = "${aws_secretsmanager_secret.app.arn}:DB__PASSWORD::" },
      { name = "OPENROUTER_API_KEY",     valueFrom = "${aws_secretsmanager_secret.app.arn}:OPENROUTER_API_KEY::" },
      { name = "GOOGLE_REVIEWS_API_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:GOOGLE_REVIEWS_API_KEY::" },
      { name = "SECRET_KEY",             valueFrom = "${aws_secretsmanager_secret.app.arn}:SECRET_KEY::" },
    ]

    environment = [
      { name = "APP_ENV",        value = "production" },
      { name = "DB__HOST",       value = aws_db_instance.main.address },
      { name = "DB__PORT",       value = tostring(aws_db_instance.main.port) },
      { name = "DB__NAME",       value = "customer_voice_ai" },
      { name = "DB__USERNAME",   value = "postgres" },
      { name = "CELERY__BROKER_URL",     value = "redis://${aws_elasticache_cluster.main.cache_nodes[0].address}:6379/0" },
      { name = "CELERY__RESULT_BACKEND", value = "redis://${aws_elasticache_cluster.main.cache_nodes[0].address}:6379/1" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
}

# ── ECS Services ─────────────────────────────────────────────────────────────

resource "aws_ecs_service" "backend" {
  name            = "${var.app_name}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  # Rolling deploy — keeps old task running until new one is healthy
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true  # auto-rollback if new tasks fail health checks
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name            = "${var.app_name}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}
