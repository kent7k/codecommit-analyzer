# codecommit-analyzer

[![ci](https://github.com/kent7k/codecommit-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/kent7k/codecommit-analyzer/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.12-blue)
![terraform](https://img.shields.io/badge/terraform-%E2%89%A51.9-844FBA)

**ドキュメントの無い CodeCommit リポジトリ群を、Claude（Amazon Bedrock）で SRE 向けに読み解く。**

配属先にドキュメントが無く、まず「何がどこで、どう動いているか」を掴みたい。そのための道具を 3 段で用意した。小さい段から使い始めて、必要になったら次の段へ進めばいい。

| 段 | 何をする | 要るもの | 入口 |
|---|---|---|---|
| **1. 手元で対話** | WSL の Claude Code を Bedrock につなぎ、repo を読みながら質問する | WSL・AWS SSO | [`scripts/wsl-setup.sh`](scripts/wsl-setup.sh) |
| **2. 手元で一括・自動** | 全 repo を headless で解析して `ANALYSIS.md` を作る。以後はコミットのたびに差分だけ更新する | 段 1 | [`scripts/batch-analyze.sh`](scripts/batch-analyze.sh) / [`scripts/install-hooks.sh`](scripts/install-hooks.sh) |
| **3. AWS 上の基盤** | 誰が push しても・定期でも・PC が無くても解析が回る。結果は S3、対話は AgentCore | AWS アカウント（作成権限） | [`terraform/`](terraform/) |

**段 1〜2 で足りるうちは段 3 を作らない。**

---

## 目次

- [クイックスタート（段 1〜2）](#クイックスタート段-12)
- [モデルの選び方](#モデルの選び方)
- [出力：ANALYSIS.md](#出力analysismd)
- [コミットのたびに更新する](#コミットのたびに更新する)
- [AWS 上の基盤（段 3）](#aws-上の基盤段-3)
- [「120 秒で落ちる」について](#120-秒で落ちるについて)
- [リポジトリ構成](#リポジトリ構成)
- [開発](#開発)
- [セキュリティと公開の規律](#セキュリティと公開の規律)
- [FAQ](#faq)

---

## クイックスタート（段 1〜2）

WSL（Ubuntu）で：

```bash
git clone https://github.com/kent7k/codecommit-analyzer && cd codecommit-analyzer

# 1) Claude Code + AWS CLI + git-remote-codecommit を入れ、Bedrock につなぐ
bash scripts/wsl-setup.sh <sso-profile>

# 2) 対象リージョンの全 repo を clone → 解析 → out/INDEX.md
AWS_PROFILE=<sso-profile> scripts/batch-analyze.sh

# 3) 以後はコミットのたびに差分だけ解析し直す
scripts/install-hooks.sh repos/*
```

1 つの repo を対話で読むだけなら、こうする：

```bash
git clone --depth 1 codecommit::ap-northeast-3://<repo> && cd <repo>
claude
> この repo を SRE 向けに読み解いて。まず README と IaC から。
```

`wsl-setup.sh` が `~/.claude/settings.json` に書き込む設定：

```json
{
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_REGION": "ap-northeast-1",
    "AWS_PROFILE": "<sso-profile>",
    "ANTHROPIC_MODEL": "jp.anthropic.claude-opus-5-5"
  },
  "awsAuthRefresh": "aws sso login --profile <sso-profile>"
}
```

IAM に要る権限：`bedrock:InvokeModel`、`bedrock:InvokeModelWithResponseStream`、`bedrock:ListInferenceProfiles`、`codecommit:GitPull`、`codecommit:ListRepositories`。

### batch-analyze.sh の主な変数

| 変数 | 既定 | 意味 |
|---|---|---|
| `AWS_PROFILE` | （必須） | SSO プロファイル |
| `TARGET_AWS_REGION` | `ap-northeast-3` | CodeCommit のリージョン |
| `MODEL` | `jp.anthropic.claude-opus-5-5` | 主モデル |
| `FALLBACK_MODEL` | なし | 混雑時の切り替え先（`claude -p --fallback-model`） |
| `PARALLEL` | `1` | 同時実行数。Bedrock の TPM/RPM クォータに合わせる |
| `PROMPT_FILE` | `scripts/analyze-prompt.md` | 解析プロンプト（章立て固定） |
| `ROOT` / `OUT` | `./repos` / `./out` | clone 先 / 結果の置き場 |

---

## モデルの選び方

2026-10 時点で、東京から Bedrock 経由で呼べる Claude を良い順に並べた：

| | モデル | ID | データの行き先 | 使う条件 |
|---|---|---|---|---|
| 🥇 | **Claude Fable 5.1** | `global.anthropic.claude-fable-5-1` | `global.` のみ＝**国外に出る** | アカウントの Data Retention を `aws_review` に opt-in する（会社の判断）。refusal 率が高め |
| 🥈 | **Claude Opus 5.5** | `jp.anthropic.claude-opus-5-5` | 東京⇄大阪で閉じる | 今すぐ使える |
| 🥉 | Claude Opus 5.5 | `global.anthropic.claude-opus-5-5` | 国外に出る | `jp.` が混んでいるときの逃げ道 |

**推奨の進め方：** Opus 5.5（`jp.`）で始め、Fable 5.1 の利用承認は並行して取りに行く。承認が下りたら主モデルを Fable にし、Opus 5.5 をフォールバックにする。

```bash
MODEL=global.anthropic.claude-fable-5-1 FALLBACK_MODEL=jp.anthropic.claude-opus-5-5 \
  AWS_PROFILE=<sso-profile> scripts/batch-analyze.sh
```

自分のアカウントで今使えるモデルの確認：

```bash
aws bedrock list-inference-profiles --region ap-northeast-1 \
  --query 'inferenceProfileSummaries[].inferenceProfileId' --output text | tr '\t' '\n' | grep claude
```

出典：[Fable 5.1 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-fable-5-1.html) · [Opus 5.5 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html) · [Claude Code on Amazon Bedrock](https://docs.claude.com/en/docs/claude-code/amazon-bedrock)

---

## 出力：ANALYSIS.md

各 repo の直下に、次の章立てで書き出す（プロンプトは [`scripts/analyze-prompt.md`](scripts/analyze-prompt.md)）：

```
## 目的
## アーキテクチャ          … 1 段落 + 主要コンポーネント（パス付き）
## エントリポイント
## 外部依存                … AWS サービス・DB・キュー・外部 API
## ランタイム・ビルド
## デプロイ・運用          … CI/CD・環境変数・設定の在り処
## 観測                    … ログ・メトリクス・アラート（無ければ「無い」）
## リスク                  … 秘密らしき値は値を書かず場所だけ
## 未解決の問い            … 推測はここへ
## オンボーディングの順    … 最初の 1 日で読む順
```

`out/` には各 repo の写しと、一覧の `INDEX.md` を置く。

---

## コミットのたびに更新する

```bash
scripts/install-hooks.sh repos/*            # まとめて
scripts/install-hooks.sh ~/src/some-repo    # 個別に
```

```
git commit ──▶ post-commit ──(バックグラウンド)──▶ claude -p
                                 │ 初回:   全文を解析
                                 │ 2 回目〜: 前回解析した commit からの diff だけ
                                 ▼
                            ANALYSIS.md（unstaged のまま置く）
```

- コミットは待たせない。前回の解析がまだ走っていれば今回は飛ばし、次のコミットで拾う
- 既存の post-commit（gitleaks 等）は置き換えず、1 行足して連結する
- 結果は unstaged のまま置く。中身を確かめてから次のコミットに含める

| 操作 | 方法 |
|---|---|
| ログ | `<repo>/.git/claude-analyze.log` |
| 一時停止 | `CLAUDE_ANALYZE=0 git commit …` |
| モデル変更 | `CLAUDE_ANALYZE_MODEL=global.anthropic.claude-fable-5-1` |
| プロンプト | `~/.config/codecommit-analyzer/{analyze,update}-prompt.md` |
| 外す | `rm <repo>/.git/hooks/claude-analyze.post-commit` |

自分以外の push まで拾いたくなったら、段 3（CodeCommit trigger → EventBridge → SQS）へ進む。

---

## AWS 上の基盤（段 3）

```
対話経路（軽い・秒〜分）                      解析経路（重い・分〜時間）
操作者 ⇄ AgentCore Runtime (stream ≤60min)     tool: analyze_repo
           ├ AgentCore Memory: 会話履歴            → SQS (main + DLQ)
           ├ S3: 解析結果を文脈に                    → ECS Fargate worker (private subnet, ARM64)
           └ Bedrock: 回答                            ├ git clone --depth 1 ← CodeCommit (別リージョン, NAT 経由)
                                                      ├ 選別・分割 → Bedrock (map-reduce, prompt cache)
                                                      ├ DynamoDB jobs: 状態・トークン数
                                                      └ S3: analysis.json / README.md / latest.json
```

| 部品 | 設計上の判断 |
|---|---|
| ネットワーク | 専用 VPC。同リージョンのサービスは VPC endpoint を使い、別リージョンの CodeCommit だけ NAT を通す（endpoint は同リージョン限定のため） |
| キュー | SQS + DLQ（2 回失敗で DLQ、DLQ にはアラーム）。処理中はハートビートで可視性を延長する |
| ワーカー | Fargate ARM64 2vCPU/4GiB。キューの深さに応じて 0〜N タスク。本当の上限は Bedrock のクォータ |
| 冪等 | `job_id = sha256(repo, ref)`。同じ commit の結果が S3 にあれば読まない（二重課金を防ぐ） |
| 解析 | ツリー一覧を 1h prompt cache → 200K 字ずつ部分解析 → 統合。結果は JSON（機械向け）と Markdown（人向け） |
| 対話 | AgentCore Runtime（Strands）。履歴は AgentCore Memory、解析結果は S3 から読む |
| 観測 | JSON 1 行ログ（`hop`・`latency_ms`・tokens）、CloudWatch metrics、ADOT → AgentCore Observability |

```bash
cp terraform/backend.tf.example terraform/backend.tf
cp terraform/terraform.tfvars.example terraform/terraform.tfvars   # repo 名・モデルを埋める
make init plan apply
```

イメージの push、動かし方、障害時の対応は [docs/runbook.md](docs/runbook.md)、設計判断と捨てた案は [docs/design.md](docs/design.md) にある。

> **状態：** `terraform validate`・worker のユニットテスト・lint までは通している。実アカウントへの apply とイメージの build はまだ確かめていない。

---

## 「120 秒で落ちる」について

最初のプロトタイプは同期処理で約 120 秒で落ちた。AgentCore Runtime の上限は同期 15 分・ストリーミング 60 分・非同期 8 時間なので、そこには当たっていない。

**一番疑わしいのは boto3 の既定値**：`read_timeout=60` で 1 回再試行すると、合計 ≈120 秒で `ReadTimeoutError` になる。Opus 級のモデルは 1 回の応答に 60 秒以上かかることがある。

切り分けスクリプト（既定 / 長い timeout / ストリーミングの 3 通りで比べる）：

```bash
AWS_PROFILE=<sso-profile> AWS_REGION=ap-northeast-1 \
  uv run --project worker python scripts/diagnose_timeout.py --prompt-file <落ちたときの入力>
```

判定表と対策の一覧は [docs/diagnose-timeout.md](docs/diagnose-timeout.md)。段 1〜2 の Claude Code は常にストリーミングで動くので、この経路を通らない。

---

## リポジトリ構成

```
.
├── scripts/
│   ├── wsl-setup.sh          # 段 1: WSL に Claude Code + Bedrock
│   ├── batch-analyze.sh      # 段 2: 全 repo を headless で解析
│   ├── analyze-prompt.md     #       解析プロンプト（章立て固定）
│   ├── install-hooks.sh      # 段 2: post-commit を入れる
│   ├── hooks/post-commit     #       差分で ANALYSIS.md を更新
│   ├── diagnose_timeout.py   # 120s の切り分け
│   └── enqueue.py            # 段 3: 手でジョブを投入
├── terraform/                # 段 3: VPC・SQS・S3・DynamoDB・ECS・AgentCore・IAM
│   └── modules/{network,queue,storage,worker,agent}
├── worker/                   # 段 3: Fargate worker（Python・Anthropic SDK）
├── agent/                    # 段 3: AgentCore Runtime（Strands）
└── docs/
    ├── claude-code-on-bedrock.md
    ├── design.md
    ├── diagnose-timeout.md
    └── runbook.md
```

---

## 開発

```bash
make help        # 一覧
make test        # worker のユニットテスト（AWS 不要）
make lint        # ruff
make validate    # terraform validate（backend 不要）
make fmt
```

必要なもの：[uv](https://docs.astral.sh/uv/)、Terraform ≥ 1.9（AWS provider ≥ 6.25）、Docker（arm64 build、段 3 のみ）。

CI（GitHub Actions）は lint・test・`terraform validate`・gitleaks だけを走らせ、**AWS には触らない**。

---

## セキュリティと公開の規律

この repo は公開している。社内の情報は一切含めない。

- アカウント ID・repo 名・VPC ID・社内の文脈は commit しない。`terraform.tfvars` と `backend.tf` は gitignore し、`*.example` だけを置く
- 認証は SSO プロファイルで行い、鍵をファイルに置かない
- pre-commit：gitleaks / terraform fmt + validate / ruff
- 解析プロンプトは「秘密らしき値は書かず、存在と場所だけ」と指示している
- 段 3 の IAM は最小権限：CodeCommit は repo の ARN を列挙、Bedrock は推論プロファイルと基盤モデルの ARN に限定、S3 と DynamoDB は対象リソースだけ
- `global.` の推論プロファイルはデータが国外に流れる。社内ソースを扱うなら、使う前に会社の方針を確認する

---

## FAQ

**Q. `aws bedrock-runtime` を CLI で叩くのと何が違う？**
CLI はモデルを 1 回呼ぶだけ。Claude Code はファイルを読み、grep し、コマンドを打ち、その結果を見てまた考える、をループするエージェントで、Bedrock をそのモデルの借り先として使う。

**Q. Fable 5.1 を選ぶと 403 / 400 が返る。**
403 はアクセス未許可か SCP、400 は Data Retention が `aws_review` になっていないのが典型。`jp.anthropic.claude-opus-5-5` に戻せば動く。

**Q. 費用はどれくらい？**
repo の大きさで決まる。段 3 は jobs テーブルにジョブごとの入出力トークン数を記録し、CloudWatch metrics にも出す。段 2 は `PARALLEL` と差分更新で抑えられる。単価は [Bedrock の料金ページ](https://aws.amazon.com/bedrock/pricing/) で確認する。

**Q. 段 3 は今すぐ要る？**
要らない。チームで共有する・定期で回す・PC が無くても動く、のどれかが必要になってからで十分。

---

## License

[MIT](LICENSE)
