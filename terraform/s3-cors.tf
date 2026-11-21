resource "aws_s3_bucket_cors_configuration" "app_storage" {
  bucket = aws_s3_bucket.app_storage.id

  cors_rule {
    allowed_origins = var.frontend_origins
    allowed_methods = ["PUT", "GET", "HEAD"]
    allowed_headers = [
      "content-type",
      "x-amz-meta-filename",
      "x-amz-meta-uploaded-at",
      "content-disposition",
    ]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}