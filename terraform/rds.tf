resource "aws_db_subnet_group" "main" {
  name       = "${var.app_name}-db"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${var.app_name}-db-subnet-group" }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.app_name}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t3.micro"

  allocated_storage     = 20
  max_allocated_storage = 100  # auto-scales up to 100GB

  db_name  = "customer_voice_ai"
  username = "postgres"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  # pgvector is installed via: CREATE EXTENSION IF NOT EXISTS vector;
  # run by alembic migration on first deploy — no custom parameter group needed

  # No public access — only reachable from inside the VPC
  publicly_accessible = false

  # Backups
  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  # Prevent accidental deletion
  deletion_protection     = true
  skip_final_snapshot     = false
  final_snapshot_identifier = "${var.app_name}-final-snapshot"

  tags = { Name = "${var.app_name}-db" }
}
