resource "aws_s3_bucket" "icp" {
  bucket_prefix = "${local.prefix}-icp-"
}

resource "aws_s3_bucket_public_access_block" "icp" {
  bucket = aws_s3_bucket.icp.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "icp" {
  bucket = aws_s3_bucket.icp.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "icp" {
  bucket = aws_s3_bucket.icp.id

  versioning_configuration {
    status = "Enabled"
  }
}

data "aws_iam_policy_document" "icp_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.icp.arn,
      "${aws_s3_bucket.icp.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "icp" {
  bucket = aws_s3_bucket.icp.id
  policy = data.aws_iam_policy_document.icp_bucket.json
}
