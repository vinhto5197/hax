data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
}

resource "aws_instance" "box" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids = [aws_security_group.box.id]
  iam_instance_profile   = aws_iam_instance_profile.box.name
  user_data              = file("${path.module}/user-data.sh")

  # Encrypted like RDS and the buckets: this disk holds .env and Redis's data.
  # Cannot be turned on in place, so it has to be set before the first apply.
  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_gb
    encrypted   = true
  }

  # IMDSv2 only: a session token is required, so an SSRF in any container
  # cannot read the instance-role credentials with a plain GET. Hop limit 2
  # lets containers on the Docker bridge (one extra hop) still reach IMDS.
  # Burstable credits throttle rather than bill when exhausted: a runaway
  # ingest cannot become a surprise line item.
  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  lifecycle {
    # Neither a newer Canonical AMI (the lookup is "most recent") nor a change
    # in the subnet set may replace the box: both destroy Caddy's certificates
    # and the Redis volume. OS patching is apt on the box; a new AMI is a
    # deliberate `-replace`.
    ignore_changes = [ami, subnet_id]
  }

  tags = {
    Name = "${var.project}-box"
  }
}

resource "aws_eip" "box" {
  domain = "vpc"
}

resource "aws_eip_association" "box" {
  instance_id   = aws_instance.box.id
  allocation_id = aws_eip.box.id
}
