provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project    = var.project
      managed_by = "terraform"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

# Not every us-east-1 AZ offers Graviton sizes; restricting the subnets to the
# AZs that do keeps the box (and RDS placement) off an AZ that would fail at
# apply time.
data "aws_ec2_instance_type_offerings" "box" {
  location_type = "availability-zone"
  filter {
    name   = "instance-type"
    values = [var.instance_type]
  }
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
  filter {
    name   = "availability-zone"
    values = data.aws_ec2_instance_type_offerings.box.locations
  }
}
