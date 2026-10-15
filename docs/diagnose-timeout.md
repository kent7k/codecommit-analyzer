# 「120s で落ちる」の切り分け

プロトタイプが約 120 秒で落ちた。AgentCore Runtime の上限はそこに無い（下表）ので、
原因は別の層にある。この手順で層を確定してから直す。

## AgentCore Runtime の公式上限（当たらないことの確認）

| 項目 | 上限 | 出典 |
|---|---|---|
| 同期リクエスト | 15 分 | [Quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html) |
| ストリーミング接続 | 60 分 | 同上 |
| 非同期ジョブ | 8 時間 | 同上 |
| セッション idle | 15 分（60s〜8h で変更可） | [Lifecycle](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html) |
| セッション最大寿命 | 8 時間（変更可） | 同上 |

## 候補（確からしい順）

| # | 層 | 仕組み | 証拠の出方 |
|---|---|---|---|
| 1 | **エージェント → Bedrock** | boto3 `bedrock-runtime` の既定 `read_timeout=60`。legacy retry で 1 回やり直し → **合計 ≈120s で `ReadTimeoutError`**。AWS 自身が「Opus 級は 60s を超える。read_timeout は 1000s 級に」と書いている（[Knowledge Center](https://www.repost.aws/knowledge-center/bedrock-large-model-read-timeouts)） | 例外が `botocore.exceptions.ReadTimeoutError`、スタックに `bedrock-runtime` / Strands の `BedrockModel` |
| 2 | 呼び出し側 → `InvokeAgentRuntime` | こちらも boto3 既定 60s＋再試行。エージェントが 60s で返さないとクライアントが切って再送 → 同じ仕事が二重に走る | 例外がクライアント側。Runtime のログで同じ invoke が 2 回 |
| 3 | 前段（API Gateway 29s / ALB idle 60s） | 置いていれば | 504 の発生元 |
| 4 | `/ping` 無応答 | 同期処理でイベントループを塞ぐとヘルスチェックが落ちる | Runtime のログに ping 失敗 |

## 手順

### 0. 落ちたときの例外クラスを見る（最短）

例外クラス 1 行で層が決まる：

- `botocore.exceptions.ReadTimeoutError` … 候補 1 か 2（スタックで `bedrock-runtime` か `bedrock-agentcore` か）
- `ClientError: ThrottlingException` … タイムアウトではなくクォータ
- HTTP 504 / `GatewayTimeout` … 候補 3

### 1. AgentCore の外から Bedrock を直に叩く

```bash
AWS_PROFILE=<会社の SSO> AWS_REGION=ap-northeast-1 \
  uv run --project worker python scripts/diagnose_timeout.py \
    --model jp.anthropic.claude-opus-5-5 --prompt-file <落ちたときと同じ大きさの入力>
```

3 本の結果の読み方：

| A 既定 | B 長い timeout | C ストリーム | 結論 |
|---|---|---|---|
| ReadTimeoutError ≈120s | OK | OK | **候補 1 で確定**。timeout を伸ばしストリームにする |
| OK | OK | OK | モデル呼び出しは無実。候補 2〜4 へ |
| Throttling | Throttling | Throttling | クォータ。`aws service-quotas` で TPM/RPM を見る |

### 2. 候補 2 を潰す

呼び出し側の `boto3.client("bedrock-agentcore")` に `Config(read_timeout=900)` を入れて再現するか。
あるいはストリーミング（`InvokeAgentRuntime` の `Accept: text/event-stream`）に変える。

### 3. 観測を入れてから本番へ

- Runtime 側は ADOT 自動計装（`agent/Dockerfile` の `opentelemetry-instrument`）。
  アカウントで CloudWatch **Transaction Search** を一度有効化すると、invoke ごとのスパン
  （モデル呼び出しの所要・トークン）が GenAI Observability に出る
  （[Get started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html)）。
- worker 側は JSON 1 行ログ（`hop` と `latency_ms`）。CloudWatch Logs Insights で
  `filter hop like /llm/ | stats avg(latency_ms), max(latency_ms) by hop`。

## この repo が最初から入れている対策

| 対策 | どこ |
|---|---|
| モデル呼び出しは常にストリーミング | `worker/analyzer/llm.py` `_call` |
| timeout 1800s、再試行は throttle/5xx だけ、timeout は 1 回 | 同上 |
| Strands の `BedrockModel` に `read_timeout=1800` | `agent/app.py` |
| 重い仕事は Runtime の中でやらず SQS → Fargate | `agent/tools.py` `analyze_repo` |
| SQS 可視性をハートビートで延長 | `worker/analyzer/main.py` `Heartbeat` |
| 2 回失敗で DLQ、DLQ にアラーム | `terraform/modules/queue` |
