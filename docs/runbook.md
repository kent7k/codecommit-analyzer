# Runbook

## 前提

- Terraform ≥ 1.9、AWS provider ≥ 6.25（`aws_bedrockagentcore_*`）
- uv、Docker（buildx で arm64）
- AWS 認証は SSO プロファイル（鍵をファイルに置かない）
- Bedrock のモデルアクセス：コンソールで Anthropic のモデルを有効化済み
- `aws bedrock list-inference-profiles --region ap-northeast-1 | grep opus-5-5` で `jp.` が見える

## 初回

```bash
cp terraform/backend.tf.example terraform/backend.tf          # state の置き場
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# tfvars を埋める（repo 名の列挙・モデル）
make init plan apply                                           # 1 回目は ECR と IAM まで通る（イメージ無しでも apply 可）
```

イメージを push：

```bash
REGION=ap-northeast-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

WORKER=$(cd terraform && terraform output -raw worker_ecr_repository_url)
docker build --platform linux/arm64 -t $WORKER:latest worker && docker push $WORKER:latest

AGENT=$(cd terraform && terraform output -raw agent_ecr_repository_url)
docker build --platform linux/arm64 -t $AGENT:latest agent && docker push $AGENT:latest
```

AgentCore Runtime は push 後に `terraform apply` し直す（イメージの digest を取り直すため）か、
`aws bedrock-agentcore-control update-agent-runtime` でイメージを指し直す。

## 動かす

worker だけ試す：

```bash
QUEUE_URL=$(cd terraform && terraform output -raw queue_url) \
  uv run --project worker python scripts/enqueue.py <repo-name> --ref main
aws dynamodb get-item --table-name $(cd terraform && terraform output -raw jobs_table_name) \
  --key '{"job_id":{"S":"<job_id>"}}'
aws s3 ls s3://$(cd terraform && terraform output -raw results_bucket)/repos/<repo-name>/
```

対話（AgentCore）：

```bash
ARN=$(cd terraform && terraform output -raw agent_runtime_arn)
aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn $ARN \
  --runtime-session-id "$(uuidgen)-$(uuidgen)" \
  --payload '{"prompt":"<repo-name> を解析して","actor_id":"me"}' /dev/stdout
```

## 観測

- CloudWatch Logs `/cc-analyzer/worker`：`filter hop like /llm/ | stats avg(latency_ms) by hop`
- CloudWatch metrics namespace `cc-analyzer`：tokens・duration・failed
- AgentCore Observability：アカウントで Transaction Search を 1 回有効化
- DLQ アラーム `cc-analyzer-dlq-not-empty`

## 失敗したら

| 症状 | 見る所 | 直し |
|---|---|---|
| DLQ に入った | jobs テーブルの `error_class` / `error` | 原因を直して DLQ から redrive |
| `status=failed, error_class=RefusedError` | モデルの refusal。再試行しない | 入力を見直す（秘密っぽい文字列・攻撃コード等） |
| `ThrottlingException` が続く | Service Quotas の Bedrock TPM/RPM | `worker_max_tasks` を下げる or クォータ申請 |
| clone が失敗 | NAT と `codecommit:GitPull` の ARN | `codecommit_repository_names` |
| AgentCore が 403 | Runtime の role・`bedrock:InvokeModel` の ARN | `bedrock_foundation_model_ids` |
| 120s で落ちる | `docs/diagnose-timeout.md` | |

## 壊す

```bash
cd terraform && terraform destroy
```

S3 は `force_destroy=false`。結果を消していいなら先に `aws s3 rm --recursive`。
