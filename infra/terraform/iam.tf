data "aws_iam_policy_document" "box_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "box" {
  name               = "${var.project}-box"
  assume_role_policy = data.aws_iam_policy_document.box_assume.json
}

resource "aws_iam_role_policy_attachment" "box_ssm" {
  role       = aws_iam_role.box.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# The containers reach S3 through the instance role (IMDS), so no static AWS
# keys live in the box's .env. ListBucket is what lets storage._ensure_bucket's
# HeadBucket return 200 instead of 403.
data "aws_iam_policy_document" "box_s3" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.uploads.arn]
  }
}

resource "aws_iam_role_policy" "box_s3" {
  name   = "${var.project}-uploads"
  role   = aws_iam_role.box.id
  policy = data.aws_iam_policy_document.box_s3.json
}

resource "aws_iam_instance_profile" "box" {
  name = "${var.project}-box"
  role = aws_iam_role.box.name
}
