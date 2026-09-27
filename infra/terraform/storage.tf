resource "random_id" "uploads" {
  byte_length = 4
}

# Versioning off: a deleted document must actually be gone (user data is
# sensitive by default), and upload keys are never overwritten in place.
resource "aws_s3_bucket" "uploads" {
  bucket = "${var.project}-uploads-${random_id.uploads.hex}"
  # A demo bucket: destroy must remove it even when it holds uploads.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
