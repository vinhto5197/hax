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
  # Same AZ as the box (cross-AZ traffic is billed per GB), taken from the
  # subnet, never from the instance: see data.aws_subnet.box.
  availability_zone   = data.aws_subnet.box.availability_zone
  publicly_accessible = false

  backup_retention_period = var.db_backup_retention_days
  apply_immediately       = true
  deletion_protection     = false
  # A demo database: destroy should not leave a billable snapshot behind. The
  # automated backups (db_backup_retention_days) cover mistakes while it runs
  # and outlive the instance if it is ever deleted.
  skip_final_snapshot      = true
  delete_automated_backups = false

  # The one resource holding user data. Terraform refuses to destroy it until
  # this block is removed on purpose; a full `terraform destroy` needs that too.
  lifecycle {
    prevent_destroy = true
  }
}
