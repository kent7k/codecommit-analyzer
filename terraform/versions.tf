terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # aws_bedrockagentcore_* は 6.x 後半で入った。古いと agent モジュールが落ちる。
      version = ">= 6.25"
    }
  }

  # backend は環境固有なので backend.tf（gitignore 済み）に置く。
  # 例: backend.tf.example
}
