# Remote-state storage for the root module. This module itself keeps local
# state: it creates the backend, so it cannot live in it. Apply once; keep its
# terraform.tfstate (gitignored) or re-import if lost.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

variable "project" {
  type    = string
  default = "hax"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project    = var.project
      managed_by = "terraform"
    }
  }
}

resource "random_id" "state" {
  byte_length = 4
}

resource "aws_s3_bucket" "state" {
  bucket = "${var.project}-tfstate-${random_id.state.hex}"

  # State holds the RDS master password and every resource id; losing the
  # bucket orphans the whole stack from Terraform.
  lifecycle {
    prevent_destroy = true
  }
}

# Versioning on: a corrupted or bad state write can be rolled back.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}
