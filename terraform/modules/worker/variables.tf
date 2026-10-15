variable "project" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "target_aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "queue_arn" {
  type = string
}

variable "queue_url" {
  type = string
}

variable "queue_name" {
  type = string
}

variable "dlq_arn" {
  type = string
}

variable "results_bucket" {
  type = string
}

variable "results_bucket_arn" {
  type = string
}

variable "jobs_table_name" {
  type = string
}

variable "jobs_table_arn" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "bedrock_model_id" {
  type = string
}

variable "bedrock_invoke_arns" {
  type = list(string)
}

variable "codecommit_repo_arns" {
  type = list(string)
}

variable "cpu" {
  type = number
}

variable "memory" {
  type = number
}

variable "ephemeral_storage_gib" {
  type = number
}

variable "max_tasks" {
  type = number
}

variable "image_tag" {
  type = string
}

variable "log_retention_days" {
  type = number
}
