resource "aws_db_subnet_group" "postgres" {
  name       = "${var.project}-db"
  subnet_ids = data.aws_subnets.default.ids
}

# PG16 on RDS ships pgvector (the first migration runs CREATE EXTENSION) and
# defaults rds.force_ssl to 1, so no custom parameter group is needed.
resource "aws_db_instance" "postgres" {
  identifier     = "${var.project}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "hax"
  username = var.db_master_username
  password = var.db_master_password

  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.db.id]
  # Same AZ as the box: cross-AZ traffic is billed per GB.
  availability_zone   = aws_instance.box.availability_zone
  publicly_accessible = false

  backup_retention_period = 7
  apply_immediately       = true
  deletion_protection     = false
  # A demo database: destroy should not leave a billable snapshot behind. The
  # 7-day automated backups cover mistakes while it runs.
  skip_final_snapshot = true
}
