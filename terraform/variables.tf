variable "project" {
  description = "リソース名の接頭辞"
  type        = string
  default     = "cc-analyzer"
}

variable "aws_region" {
  description = "解析基盤を置くリージョン（Bedrock を呼ぶリージョン）"
  type        = string
  default     = "ap-northeast-1"
}

variable "target_aws_region" {
  description = "解析対象の CodeCommit があるリージョン"
  type        = string
  default     = "ap-northeast-3"
}

variable "codecommit_repository_names" {
  description = "解析を許す CodeCommit リポジトリ名。空なら target リージョンの全リポジトリ（最小権限なら列挙する）"
  type        = list(string)
  default     = []
}

variable "bedrock_model_id" {
  description = <<-EOT
    Bedrock のモデル ID（推論プロファイル）。
    jp.  = 東京/大阪の中で完結（ソースコードを国外に出さない）
    global. = 全リージョンに流れる（レイテンシ/スループット優先）
    `aws bedrock list-inference-profiles --region ap-northeast-1` で存在を確かめてから使う。
  EOT
  type        = string
  default     = "jp.anthropic.claude-opus-5-5"
}

variable "bedrock_foundation_model_ids" {
  description = "推論プロファイルが経由する基盤モデル ID（IAM の許可対象）。プロファイルを変えたらここも揃える"
  type        = list(string)
  default     = ["anthropic.claude-opus-5-5"]
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "az_count" {
  description = "private subnet を置く AZ の数"
  type        = number
  default     = 2
}

variable "enable_nat" {
  description = "NAT Gateway を置く。VPC endpoint は同リージョン限定なので、別リージョンの CodeCommit へは NAT が要る"
  type        = bool
  default     = true
}

variable "worker_cpu" {
  description = "Fargate タスクの vCPU（1024 = 1vCPU）"
  type        = number
  default     = 2048
}

variable "worker_memory" {
  description = "Fargate タスクのメモリ MiB"
  type        = number
  default     = 4096
}

variable "worker_ephemeral_storage_gib" {
  description = "clone 先のディスク。モノレポがあれば上げる（21〜200）"
  type        = number
  default     = 30
}

variable "worker_max_tasks" {
  description = "キュー深さで増やすタスク数の上限。Bedrock の TPM/RPM クォータに合わせる"
  type        = number
  default     = 3
}

variable "worker_image_tag" {
  type    = string
  default = "latest"
}

variable "agent_image_tag" {
  type    = string
  default = "latest"
}

variable "job_visibility_timeout_seconds" {
  description = "SQS 可視性タイムアウト。worker はハートビートで延長するので初期値は短めでよい"
  type        = number
  default     = 900
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "agent_idle_timeout_seconds" {
  description = "AgentCore Runtime セッションの idle 終了（60〜28800）"
  type        = number
  default     = 1800
}

variable "agent_max_lifetime_seconds" {
  description = "AgentCore Runtime セッションの最大寿命（60〜28800）"
  type        = number
  default     = 14400
}

variable "memory_event_expiry_days" {
  description = "AgentCore Memory の短期イベント保持日数（7〜365）"
  type        = number
  default     = 30
}
