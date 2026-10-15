variable "project" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "queue_arn" {
  type = string
}

variable "queue_url" {
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

variable "image_tag" {
  type = string
}

variable "idle_timeout_seconds" {
  type = number
}

variable "max_lifetime_seconds" {
  type = number
}

variable "memory_event_expiry_days" {
  type = number
}

variable "log_retention_days" {
  type = number
}
