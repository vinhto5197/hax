output "elastic_ip" {
  description = "Point the domain's A record here."
  value       = aws_eip.box.public_ip
}

output "rds_endpoint" {
  description = "host:port for DATABASE_URL / MIGRATIONS_DATABASE_URL."
  value       = aws_db_instance.postgres.endpoint
}

output "s3_bucket" {
  description = "S3_BUCKET for the box's .env."
  value       = aws_s3_bucket.uploads.id
}

output "instance_id" {
  value = aws_instance.box.id
}

output "ssm_command" {
  description = "Open a shell on the box."
  value       = "aws ssm start-session --target ${aws_instance.box.id}"
}

output "app_url" {
  value = "https://${var.domain}"
}

output "deploy_role_arn" {
  description = "GitHub Actions secret AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.deploy.arn
}
