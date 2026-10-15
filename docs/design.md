# 設計

## 目的

ドキュメントの無い CodeCommit リポジトリ群を、SRE が運用できる粒度で機械的に読み解き、
結果を残して後から対話で引けるようにする。

- **解析経路**（重い・分〜時間）：一括・定期・冪等。結果は S3 に残る。
- **対話経路**（軽い・秒〜分）：AgentCore Runtime のセッション＋Memory で続きを話せる。

## 全体図

```
対話経路                                      解析経路
操作者 ⇄ AgentCore Runtime (stream ≤60min)     tool analyze_repo
           ├ AgentCore Memory: 会話履歴            → SQS (main + DLQ)
           ├ S3: 解析結果を文脈に (cache 1h)        → ECS Fargate worker (private subnet, ARM64)
           └ Bedrock: 回答                            ├ git clone --depth 1 ← CodeCommit (別リージョン, NAT)
                                                      ├ 選別・分割 → Bedrock (map-reduce, prompt cache)
                                                      ├ DynamoDB jobs: 状態・トークン
                                                      └ S3: analysis.json / README.md / latest.json
```

## 判断と理由

| 判断 | 採用 | 捨てた案と理由 |
|---|---|---|
| 重い処理の置き場 | SQS → Fargate | AgentCore Runtime 内で完結：8h・2vCPU/8GB の枠に収まるが、git や大きなディスクを持ち込むより Fargate のほうが素直。Step Functions Distributed Map：一括実行の可視性は上だが常時の流入に弱い。流入が「一括」に寄ったら切り替える |
| 状態 | DynamoDB `jobs` | SQS だけ：「今どこ？」に答えられない |
| 冪等 | `job_id = sha256(repo, ref)`、S3 に同 commit があれば skip | 二重課金を防ぐ |
| モデル | `jp.anthropic.claude-opus-5-5` | `global.`：国外へ流れる。Fable 5.1：`jp.` 無し＋アカウントで AWS review 要 opt-in＋refusal 多い（[model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-fable-5-1.html)） |
| モデル呼び出し | bedrock-runtime の Messages API 口 + Anthropic SDK | boto3 converse：prompt cache・usage・streaming を自前で組むことになる。SDK なら素のまま |
| 出力の形 | prompt で JSON Schema → pydantic 検証 → 失敗なら 1 回修復 | Bedrock の Opus 5.5 は structured outputs 未対応（model card） |
| ネットワーク | 専用 VPC、同リージョンは VPC endpoint、別リージョン CodeCommit だけ NAT | VPC endpoint は同リージョン限定。worker を大阪に置く案は Bedrock の口が細い |
| Fargate | 2vCPU/4GiB ARM64、0〜N をキュー深さで | CPU はほぼ遊ぶ。本当の上限は Bedrock の TPM/RPM |
| 失敗 | 2 回で DLQ、refusal は DLQ に送らず failed で止める | refusal は再試行しても同じ |

## 解析の作り方（map-reduce）

1. ツリー一覧（全ファイル名）を system に置き **1h cache**。全チャンク共通の prefix。
2. 読むファイルを選ぶ：生成物・依存・バイナリ・ロックを捨て、設計を語るもの（README・Dockerfile・IaC・manifest）を先頭へ。1 ファイル 120KB、合計 6MB が既定の上限。
3. 200K 文字ごとにチャンク → `ChunkAnalysis`（components / entrypoints / deps / ops notes / risks / open_questions）。
4. 部分解析を 1 回で統合 → `RepoAnalysis`（+ onboarding_steps）。
5. S3 に `analysis.json`（機械）と `README.md`（人）と `latest.json`（最新の指し先）。

## 対話の続け方（3 層）

| 層 | 何が残る | 寿命 |
|---|---|---|
| Bedrock | 何も残らない（ステートレス）。履歴は毎回送る。prefix を prompt cache | — |
| AgentCore Runtime セッション | `runtimeSessionId` ごとの microVM。プロセス内メモリ | idle 30 分 / 最大 4h（Terraform で設定） |
| AgentCore Memory | 短期＝生イベント（actor_id + session_id）。microVM が死んでも次の invoke で再読込 | 30 日（設定） |

→ 履歴は Memory、解析結果は S3、対話経路はストリーミング。

## 観測

- worker: JSON 1 行ログ（`hop`・`latency_ms`・tokens・`exc_class`）、CloudWatch metrics（`JobDurationSeconds`・`InputTokens`・`OutputTokens`・`CacheReadTokens`・`JobsDone/Failed/Refused`）。
- agent: ADOT 自動計装 → AgentCore Observability（要 Transaction Search）。
- alarms: DLQ が空でない。

## コストの防波堤

- 1 ジョブの読む総量上限（`MAX_TOTAL_BYTES`）。
- prompt cache（ツリーと system を 1h）。
- 冪等 skip。
- `worker_max_tasks` を Bedrock クォータに合わせる。
- 本番の前に AWS Budgets（この repo の外・アカウント単位）。

## 未決

- **Step Functions への切替条件**：一括実行が主用途になったら。
- **長期 Memory の戦略**：要約・意味記憶を足すか。今は短期だけ。
- **CodeCommit 側のイベント連動**：push で自動解析するなら EventBridge（別リージョン→バス転送）。
- **Fable 5.1**：会社が `global.` と AWS review を呑むなら候補に戻す。

## 残り（まだ確かめていない・まだ作っていない）

- 実アカウントでの `terraform apply` と、worker・agent のイメージの build。
- WSL での確認：`claude.ai/install.sh`、`awsAuthRefresh`、`--allowedTools "Write(ANALYSIS.md)"` の書き方、
  `--fallback-model` が Fable の refusal で切り替わるか。
- 基盤側のモデル連鎖：Fable 5.1（global）→ Opus 5.5（jp）→ Opus 5.5（global）。refusal が出たら
  そのジョブの間は下の段に留まる。`worker/analyzer/llm.py`・config・terraform の IAM に組み込む（設計は済み、組み込みはまだ）。
- Converse 経由の refusal を Strands がどの StopReason で返すか（agent 側のフォールバック判定に要る）。
