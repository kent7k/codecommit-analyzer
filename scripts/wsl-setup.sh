#!/usr/bin/env bash
# WSL (Ubuntu) に Claude Code を入れて Amazon Bedrock につなぐ。
# 使い方: bash scripts/wsl-setup.sh <aws-sso-profile> [model-id]
#   例:   bash scripts/wsl-setup.sh work jp.anthropic.claude-opus-5-5
# 何度走らせても同じ状態に収束する（冪等）。
set -euo pipefail

PROFILE="${1:?usage: wsl-setup.sh <aws-sso-profile> [model-id]}"
MODEL="${2:-jp.anthropic.claude-opus-5-5}"
REGION="${AWS_REGION:-ap-northeast-1}"

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

say "apt: 基本道具"
sudo apt-get update -qq
sudo apt-get install -y -qq curl git unzip jq pipx >/dev/null
pipx ensurepath >/dev/null 2>&1 || true

say "AWS CLI v2"
if ! command -v aws >/dev/null; then
  tmp=$(mktemp -d)
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o "$tmp/awscli.zip"
  unzip -q "$tmp/awscli.zip" -d "$tmp"
  sudo "$tmp/aws/install" --update
  rm -rf "$tmp"
fi
aws --version

say "git-remote-codecommit（CodeCommit を clone する用）"
pipx install --force git-remote-codecommit >/dev/null

say "Claude Code"
if ! command -v claude >/dev/null; then
  curl -fsSL https://claude.ai/install.sh | bash
  export PATH="$HOME/.local/bin:$PATH"
fi
claude --version

say "AWS SSO プロファイル '$PROFILE'"
if ! aws configure list-profiles | grep -qx "$PROFILE"; then
  echo "プロファイルが無い。対話で作る:"
  aws configure sso --profile "$PROFILE"
fi
aws sso login --profile "$PROFILE" || true

say "Bedrock のモデル確認（$REGION）"
aws bedrock list-inference-profiles --region "$REGION" --profile "$PROFILE" \
  --query 'inferenceProfileSummaries[].inferenceProfileId' --output text 2>/dev/null \
  | tr '\t' '\n' | grep -E 'claude-(opus|fable|sonnet)-5' || echo "(一覧が取れない: bedrock:ListInferenceProfiles の権限を確認)"

say "~/.claude/settings.json に Bedrock 設定をマージ"
mkdir -p "$HOME/.claude"
SETTINGS="$HOME/.claude/settings.json"
[ -s "$SETTINGS" ] || echo '{}' > "$SETTINGS"
tmp=$(mktemp)
jq --arg p "$PROFILE" --arg r "$REGION" --arg m "$MODEL" '
  .env = ((.env // {}) + {
    CLAUDE_CODE_USE_BEDROCK: "1",
    AWS_REGION: $r,
    AWS_PROFILE: $p,
    ANTHROPIC_MODEL: $m
  })
  | .awsAuthRefresh = ("aws sso login --profile " + $p)
' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
cat "$SETTINGS"

say "done"
cat <<EOF
次:
  claude                      # 起動。/model でモデルを確認・切替
  /status                     # Bedrock につながっているか
WSL の PATH に ~/.local/bin が無ければ:  echo 'export PATH="\$HOME/.local/bin:\$PATH"' >> ~/.bashrc
EOF
