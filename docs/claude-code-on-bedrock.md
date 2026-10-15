# Claude Code を Bedrock で使う（WSL）

「会社のアカウントで、使い慣れた Claude を使って repo を読み解く」の最短路。
AWS 基盤（`terraform/`）は要らない。

## 入れる

```bash
bash scripts/wsl-setup.sh <sso-profile> [model-id]
```

やること: apt → AWS CLI v2 → git-remote-codecommit → Claude Code → SSO login →
Bedrock のモデル一覧確認 → `~/.claude/settings.json` に以下をマージ。

```json
{
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_REGION": "ap-northeast-1",
    "AWS_PROFILE": "work",
    "ANTHROPIC_MODEL": "jp.anthropic.claude-opus-5-5"
  },
  "awsAuthRefresh": "aws sso login --profile work"
}
```

IAM に要るもの: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`,
`bedrock:ListInferenceProfiles`。

## モデルの選び方

| モデル | ID | 居場所 | 使うには |
|---|---|---|---|
| **Fable 5.1**（最上位） | `global.anthropic.claude-fable-5-1` | `global.` のみ＝国外へ流れる | アカウントの Data Retention を `aws_review` に opt-in（会社判断）。refusal が多い |
| **Opus 5.5**（国内最上位） | `jp.anthropic.claude-opus-5-5` | 東京⇄大阪で閉じる | 今すぐ |
| Opus 5.5（逃げ道） | `global.anthropic.claude-opus-5-5` | 国外へ流れる | `jp.` が混んだとき |

進め方: **Opus 5.5 で始め、Fable の承認を並行で取る。** 承認後は `ANTHROPIC_MODEL` を Fable にし、
断られたり混んだら `/model` で Opus 5.5 へ。headless は `--fallback-model`（混雑時の切替。
refusal で切り替わるかは未確認）。

出典: [Fable 5.1 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-fable-5-1.html)
· [Opus 5.5 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html)
· [Claude Code on Bedrock](https://docs.claude.com/en/docs/claude-code/amazon-bedrock)

## 1 つの repo を読む

```bash
git clone --depth 1 codecommit::ap-northeast-3://<repo> && cd <repo>
claude
> この repo を SRE 向けに読み解いて。まず README と IaC から。
```

## 全部まとめて読む（headless）

```bash
AWS_PROFILE=work scripts/batch-analyze.sh            # 全 repo
AWS_PROFILE=work scripts/batch-analyze.sh repo-a     # 指定
PARALLEL=3 FALLBACK_MODEL=jp.anthropic.claude-opus-5-5 MODEL=global.anthropic.claude-fable-5-1 \
  AWS_PROFILE=work scripts/batch-analyze.sh
```

各 repo に `ANALYSIS.md`、`out/<repo>.md` と `out/INDEX.md` ができる。
プロンプトは `scripts/analyze-prompt.md`（章立て固定）。

## 120s で落ちない理由

Claude Code は常にストリーミングで、長い生成を前提に作られている。プロトタイプが落ちた
boto3 の `read_timeout=60` の経路を通らない。詳しくは [diagnose-timeout](diagnose-timeout.md)。

## 基盤（terraform/）が要るのは

チームで共有する・定期で回す・自分の PC が無くても動く、が要るようになってから。
