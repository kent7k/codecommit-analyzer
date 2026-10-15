output "ecr_repository_url" {
  value = aws_ecr_repository.agent.repository_url
}

output "agent_runtime_arn" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}

output "memory_id" {
  value = aws_bedrockagentcore_memory.this.id
}

output "role_arn" {
  value = aws_iam_role.agent.arn
}
