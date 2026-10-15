# codecommit-analyzer

CodeCommit のリポジトリ群を Claude（Amazon Bedrock）で読み解き、SRE 向けの解析レポートを S3 に残す。
対話は AgentCore Runtime、重い解析は SQS → ECS Fargate。Terraform + Python。

```
操作者 ⇄ AgentCore Runtime ──tool──▶ SQS ──▶ Fargate worker ──▶ Bedrock (Claude) ──▶ S3
            │ Memory（会話）                      │ CodeCommit (別リージョン)     DynamoDB (jobs)
            └ S3 の結果を文脈に
```

## なぜこの形か

- **同期 120s で落ちた**プロトタイプの反省。AgentCore Runtime の上限はそこに無く、boto3 の既定 `read_timeout=60` × 再試行が疑い筆頭。切り分け手順と対策は [docs/diagnose-timeout.md](docs/diagnose-timeout.md)。
- **解析と対話を分ける**。解析は分〜時間の非同期ジョブ（冪等・DLQ・状態テーブル）、対話はセッション＋Memory でストリーミング。
- **ソースを国外に出さない**。`jp.anthropic.claude-opus-5-5` は東京⇄大阪で閉じる。Fable 5.1 は `jp.` が無く、アカウントで AWS review の opt-in が要る（[設計](docs/design.md)）。

## 構成

| path | 中身 |
|---|---|
| `terraform/` | VPC・endpoints・SQS/DLQ・S3・DynamoDB・ECS Fargate（0〜N autoscale）・AgentCore Runtime/Memory・IAM |
| `worker/` | SQS → clone → 選別・分割 → Claude (map-reduce, prompt cache) → S3。JSON ログ・ハートビート |
| `agent/` | AgentCore Runtime のエントリポイント（Strands）。tools: analyze_repo / job_status / list_analyses / get_analysis |
| `scripts/` | `wsl-setup.sh`・`batch-analyze.sh`・`analyze-prompt.md`（手元で回す）、`install-hooks.sh`＋`hooks/post-commit`（コミットごとに差分で更新）、`diagnose_timeout.py`（120s の切り分け）、`enqueue.py`（手投入） |
| `docs/` | [claude-code-on-bedrock](docs/claude-code-on-bedrock.md) · [design](docs/design.md) · [diagnose-timeout](docs/diagnose-timeout.md) · [runbook](docs/runbook.md) |

## 使う

```bash
make validate test lint        # AWS 不要
# 以降は docs/runbook.md
```

## 公開 repo の規律

- アカウント ID・repo 名・VPC ID・社内文脈は commit しない。`terraform.tfvars` / `backend.tf` は gitignore、`*.example` だけ置く。
- CI は AWS に触らない（lint・test・validate・gitleaks）。
- pre-commit: gitleaks / terraform fmt+validate / ruff。

## まず手元で：Claude Code を Bedrock で使う（基盤は要らない）

```bash
bash scripts/wsl-setup.sh <sso-profile>              # WSL に Claude Code + Bedrock 設定
AWS_PROFILE=<sso-profile> scripts/batch-analyze.sh   # 全 repo を headless で解析 → out/
```

手順・モデルの選び方（Fable 5.1 と Opus 5.5）は [docs/claude-code-on-bedrock.md](docs/claude-code-on-bedrock.md)。
この基盤（`terraform/`）は「チームで共有・定期実行・PC 無しで動く」が要るようになってから。

## License

MIT
