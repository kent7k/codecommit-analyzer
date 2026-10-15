#!/usr/bin/env bash
# 対象 repo に post-commit hook を入れる。プロンプトは ~/.config/codecommit-analyzer/ に写す。
# 使い方: scripts/install-hooks.sh <repo-dir> [<repo-dir>...]
#         scripts/install-hooks.sh repos/*          # batch-analyze.sh で clone した全部
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
CFG="${CLAUDE_ANALYZE_PROMPTS:-$HOME/.config/codecommit-analyzer}"
mkdir -p "$CFG"
cp "$HERE/analyze-prompt.md" "$CFG/analyze-prompt.md"
[ -f "$CFG/update-prompt.md" ] || cat > "$CFG/update-prompt.md" <<'EOF'
ANALYSIS.md はこのリポジトリの SRE 向け解析です。下の差分（前回の解析以降のコミット）を読み、
ANALYSIS.md のうち変わった部分だけを更新してください。章立ては変えない。変わっていない章は触らない。
根拠のパスを添える。推測は「未解決の問い」へ。ANALYSIS.md 以外は作らない・変えない。
EOF

for repo in "$@"; do
  if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
    echo "skip (not a git repo): $repo"; continue
  fi
  hooks=$(git -C "$repo" rev-parse --git-path hooks)
  mkdir -p "$hooks"
  # 本体は別名で置き、post-commit からは 1 行で呼ぶ（既存の hook と共存する）
  cp "$HERE/hooks/post-commit" "$hooks/claude-analyze.post-commit"
  chmod +x "$hooks/claude-analyze.post-commit"
  call='[ -x "$(dirname "$0")/claude-analyze.post-commit" ] && "$(dirname "$0")/claude-analyze.post-commit"  # claude-analyze'
  if [ ! -e "$hooks/post-commit" ]; then
    printf '#!/usr/bin/env bash\n%s\nexit 0\n' "$call" > "$hooks/post-commit"
    chmod +x "$hooks/post-commit"
    echo "installed: $repo"
  elif grep -q claude-analyze "$hooks/post-commit"; then
    echo "updated: $repo"
  else
    printf '\n%s\n' "$call" >> "$hooks/post-commit"
    echo "chained to existing post-commit: $repo"
  fi
done

cat <<EOF

動き: コミットすると裏で claude -p が走り ANALYSIS.md を更新（unstaged のまま）。
  ログ:   <repo>/.git/claude-analyze.log
  止める: CLAUDE_ANALYZE=0 git commit ...   / 外す: rm <repo>/.git/hooks/claude-analyze.post-commit
  モデル: CLAUDE_ANALYZE_MODEL=global.anthropic.claude-fable-5-1（既定 jp.anthropic.claude-opus-5-5）
EOF
