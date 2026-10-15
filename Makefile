.PHONY: help init plan apply fmt validate test lint build-worker build-agent push diagnose

AWS_REGION ?= ap-northeast-1
TF_DIR     := terraform

help: ## このヘルプ
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

init: ## terraform init（backend.tf を用意してから）
	cd $(TF_DIR) && terraform init

plan: ## terraform plan
	cd $(TF_DIR) && terraform plan -out=tfplan

apply: ## terraform apply（plan 済みの tfplan）
	cd $(TF_DIR) && terraform apply tfplan

fmt: ## terraform fmt / ruff format
	cd $(TF_DIR) && terraform fmt -recursive
	cd worker && uv run ruff format .
	cd agent && uv run ruff format .

validate: ## terraform validate（backend 不要）
	cd $(TF_DIR) && terraform init -backend=false -input=false >/dev/null && terraform validate

test: ## worker の単体テスト（AWS 不要）
	cd worker && uv run pytest -q

lint: ## ruff
	cd worker && uv run ruff check .
	cd agent && uv run ruff check .

build-worker: ## worker イメージ（arm64）
	docker build --platform linux/arm64 -t codecommit-analyzer-worker:local worker

build-agent: ## agent イメージ（arm64・AgentCore Runtime は arm64 必須）
	docker build --platform linux/arm64 -t codecommit-analyzer-agent:local agent

diagnose: ## 120s の切り分け（docs/diagnose-timeout.md）
	cd worker && uv run python ../scripts/diagnose_timeout.py
