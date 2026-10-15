# 既定のプロバイダ = 解析基盤を置くリージョン（Bedrock・SQS・Fargate・S3）
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}

# 解析対象 CodeCommit があるリージョン（IAM の ARN 組み立てにだけ使う）
provider "aws" {
  alias  = "target"
  region = var.target_aws_region
}

data "aws_caller_identity" "current" {}
