output "queue_url" {
  value = module.queue.queue_url
}

output "dlq_url" {
  value = module.queue.dlq_url
}

output "results_bucket" {
  value = module.storage.results_bucket
}

output "jobs_table_name" {
  value = module.storage.jobs_table_name
}

output "worker_ecr_repository_url" {
  value = module.worker.ecr_repository_url
}

output "agent_ecr_repository_url" {
  value = module.agent.ecr_repository_url
}

output "agent_runtime_arn" {
  value = module.agent.agent_runtime_arn
}

output "memory_id" {
  value = module.agent.memory_id
}

output "ecs_cluster_name" {
  value = module.worker.cluster_name
}
