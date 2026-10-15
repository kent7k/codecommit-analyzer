locals {
  account_id = data.aws_caller_identity.current.account_id

  # CodeCommit の ARN（別リージョン）。空なら全リポジトリ。
  codecommit_repo_arns = length(var.codecommit_repository_names) == 0 ? [
    "arn:aws:codecommit:${var.target_aws_region}:${local.account_id}:*"
    ] : [
    for name in var.codecommit_repository_names :
    "arn:aws:codecommit:${var.target_aws_region}:${local.account_id}:${name}"
  ]

  # 推論プロファイル + 経由先の基盤モデル（クロスリージョンなので全リージョンを許す）
  bedrock_invoke_arns = concat(
    ["arn:aws:bedrock:${var.aws_region}:${local.account_id}:inference-profile/${var.bedrock_model_id}"],
    [for id in var.bedrock_foundation_model_ids : "arn:aws:bedrock:*::foundation-model/${id}"],
  )
}

module "network" {
  source = "./modules/network"

  project    = var.project
  vpc_cidr   = var.vpc_cidr
  az_count   = var.az_count
  enable_nat = var.enable_nat
}

module "storage" {
  source = "./modules/storage"

  project            = var.project
  log_retention_days = var.log_retention_days
}

module "queue" {
  source = "./modules/queue"

  project                    = var.project
  visibility_timeout_seconds = var.job_visibility_timeout_seconds
  kms_key_arn                = module.storage.kms_key_arn
}

module "worker" {
  source = "./modules/worker"

  project            = var.project
  aws_region         = var.aws_region
  target_aws_region  = var.target_aws_region
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  security_group_id  = module.network.worker_security_group_id

  queue_arn          = module.queue.queue_arn
  queue_url          = module.queue.queue_url
  queue_name         = module.queue.queue_name
  dlq_arn            = module.queue.dlq_arn
  results_bucket     = module.storage.results_bucket
  results_bucket_arn = module.storage.results_bucket_arn
  jobs_table_name    = module.storage.jobs_table_name
  jobs_table_arn     = module.storage.jobs_table_arn
  kms_key_arn        = module.storage.kms_key_arn

  bedrock_model_id     = var.bedrock_model_id
  bedrock_invoke_arns  = local.bedrock_invoke_arns
  codecommit_repo_arns = local.codecommit_repo_arns

  cpu                   = var.worker_cpu
  memory                = var.worker_memory
  ephemeral_storage_gib = var.worker_ephemeral_storage_gib
  max_tasks             = var.worker_max_tasks
  image_tag             = var.worker_image_tag
  log_retention_days    = var.log_retention_days
}

module "agent" {
  source = "./modules/agent"

  project    = var.project
  aws_region = var.aws_region

  queue_arn          = module.queue.queue_arn
  queue_url          = module.queue.queue_url
  results_bucket     = module.storage.results_bucket
  results_bucket_arn = module.storage.results_bucket_arn
  jobs_table_name    = module.storage.jobs_table_name
  jobs_table_arn     = module.storage.jobs_table_arn
  kms_key_arn        = module.storage.kms_key_arn

  bedrock_model_id    = var.bedrock_model_id
  bedrock_invoke_arns = local.bedrock_invoke_arns

  image_tag                = var.agent_image_tag
  idle_timeout_seconds     = var.agent_idle_timeout_seconds
  max_lifetime_seconds     = var.agent_max_lifetime_seconds
  memory_event_expiry_days = var.memory_event_expiry_days
  log_retention_days       = var.log_retention_days
}
