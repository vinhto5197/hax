variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "hax"
}

variable "region" {
  description = "AWS region. The S3 backend region in versions.tf must match."
  type        = string
  default     = "us-east-1"
}

variable "domain" {
  description = "Public hostname the box serves (DNS is managed outside AWS)."
  type        = string
}

variable "instance_type" {
  description = "EC2 size for the box. Must be arm64: the AMI and images are arm64."
  type        = string
  default     = "t4g.small"
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

# Also the schema owner named in rds-bootstrap.sql's ALTER DEFAULT PRIVILEGES;
# change both together.
variable "db_master_username" {
  description = "RDS master user; owns the schema and runs migrations."
  type        = string
  default     = "hax"
}

variable "db_master_password" {
  description = "RDS master password. Lives in terraform.tfvars only (and in state)."
  type        = string
  sensitive   = true
}

variable "db_allocated_gb" {
  description = "RDS storage in GB (gp3)."
  type        = number
  default     = 20
}

variable "root_volume_gb" {
  description = "Box root volume in GB (gp3); holds images, container logs and Caddy's certs."
  type        = number
  default     = 20
}
