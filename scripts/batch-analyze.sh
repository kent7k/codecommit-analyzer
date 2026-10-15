#!/usr/bin/env bash
# CodeCommit の全 repo（または指定 repo）を clone して Claude Code（headless）で解析し、
# 各 repo の ANALYSIS.md と out/<repo>.md を作る。AWS 基盤は使わない。
#
# 使い方:
#   scripts/batch-analyze.sh                  # 対象リージョンの全 repo
#   scripts/batch-analyze.sh repo-a repo-b    # 指定だけ
# 環境変数:
#   AWS_PROFILE          SSO プロファイル（必須）
#   TARGET_AWS_REGION    CodeCommit のリージョン（既定 ap-northeast-3）
#   MODEL                主モデル（既定 jp.anthropic.claude-opus-5-5）
#   FALLBACK_MODEL       混雑時の切替先（既定 jp.anthropic.claude-opus-5-5 と同じなら無効）
#   PROMPT_FILE          解析プロンプト（既定 scripts/analyze-prompt.md）
#   PARALLEL             同時実行数（既定 1。Bedrock の TPM に合わせて上げる）
set -euo pipefail

: "${AWS_PROFILE:?AWS_PROFILE を設定する}"
TARGET_AWS_REGION="${TARGET_AWS_REGION:-ap-northeast-3}"
MODEL="${MODEL:-jp.anthropic.claude-opus-5-5}"
FALLBACK_MODEL="${FALLBACK_MODEL:-}"
PROMPT_FILE="${PROMPT_FILE:-$(dirname "$0")/analyze-prompt.md}"
PARALLEL="${PARALLEL:-1}"
ROOT="${ROOT:-$PWD/repos}"
OUT="${OUT:-$PWD/out}"
mkdir -p "$ROOT" "$OUT"

if [ $# -gt 0 ]; then
  repos=("$@")
else
  mapfile -t repos < <(aws codecommit list-repositories --region "$TARGET_AWS_REGION" \
    --query 'repositories[].repositoryName' --output text | tr '\t' '\n' | sort)
fi
echo "repos: ${#repos[@]}  model: $MODEL  fallback: ${FALLBACK_MODEL:-none}"

analyze_one() {
  local repo="$1" dir="$ROOT/$1" t0 t1
  t0=$(date +%s)
  if [ -d "$dir/.git" ]; then
    git -C "$dir" pull -q --ff-only || true
  else
    git clone -q --depth 1 "codecommit::${TARGET_AWS_REGION}://${repo}" "$dir"
  fi
  local extra=()
  [ -n "$FALLBACK_MODEL" ] && extra+=(--fallback-model "$FALLBACK_MODEL")
  ( cd "$dir" && claude -p "$(cat "$PROMPT_FILE")" \
      --model "$MODEL" "${extra[@]}" \
      --allowedTools "Read,Grep,Glob,LS,Bash(git log:*),Bash(git ls-files:*),Write(ANALYSIS.md)" \
      --output-format text ) > "$OUT/$repo.log" 2>&1 || echo "FAILED: $repo (see $OUT/$repo.log)"
  if [ -f "$dir/ANALYSIS.md" ]; then
    cp "$dir/ANALYSIS.md" "$OUT/$repo.md"
  fi
  t1=$(date +%s)
  echo "done: $repo ($((t1 - t0))s)"
}
export -f analyze_one
export ROOT OUT MODEL FALLBACK_MODEL PROMPT_FILE TARGET_AWS_REGION AWS_PROFILE

printf '%s\n' "${repos[@]}" | xargs -P "$PARALLEL" -I{} bash -c 'analyze_one "$@"' _ {}

echo
echo "index:"
{
  echo "# Repository analyses"
  echo
  for r in "${repos[@]}"; do
    [ -f "$OUT/$r.md" ] && echo "- [$r]($r.md)" || echo "- $r (failed)"
  done
} > "$OUT/INDEX.md"
cat "$OUT/INDEX.md"
