"""「120s で落ちる」の切り分け。AgentCore の外から Bedrock を直に叩いて測る。

使い方（会社の SSO プロファイルで）:
  AWS_PROFILE=xxx AWS_REGION=ap-northeast-1 \\
    uv run python scripts/diagnose_timeout.py --model jp.anthropic.claude-opus-5-5 \\
      --prompt-file ./some_big_prompt.txt

3 本走らせて比べる:
  A) boto3 既定（read_timeout=60, legacy retry）で converse  ← ReadTimeoutError なら候補 1
  B) read_timeout=1800, max_attempts=1 で converse             ← A が落ちて B が通れば確定
  C) converse_stream で first-token / total を測る             ← 本番はこれ
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ReadTimeoutError


def _messages(prompt: str) -> list[dict]:
    return [{"role": "user", "content": [{"text": prompt}]}]


def run_converse(model: str, prompt: str, cfg: Config | None, label: str) -> None:
    client = boto3.client("bedrock-runtime", config=cfg)
    t0 = time.perf_counter()
    try:
        resp = client.converse(
            modelId=model, messages=_messages(prompt), inferenceConfig={"maxTokens": 8000}
        )
        dt = time.perf_counter() - t0
        usage = resp.get("usage", {})
        print(
            f"[{label}] OK {dt:.1f}s in={usage.get('inputTokens')} out={usage.get('outputTokens')}"
        )
    except ReadTimeoutError as e:
        dt = time.perf_counter() - t0
        print(f"[{label}] ReadTimeoutError after {dt:.1f}s  ← 候補 1（client read_timeout）: {e}")
    except ClientError as e:
        dt = time.perf_counter() - t0
        code = e.response.get("Error", {}).get("Code")
        print(f"[{label}] ClientError {code} after {dt:.1f}s: {e}")


def run_stream(model: str, prompt: str) -> None:
    cfg = Config(read_timeout=1800, retries={"max_attempts": 1})
    client = boto3.client("bedrock-runtime", config=cfg)
    t0 = time.perf_counter()
    first = None
    out_chars = 0
    try:
        resp = client.converse_stream(
            modelId=model, messages=_messages(prompt), inferenceConfig={"maxTokens": 8000}
        )
        for ev in resp["stream"]:
            if "contentBlockDelta" in ev:
                if first is None:
                    first = time.perf_counter() - t0
                out_chars += len(ev["contentBlockDelta"]["delta"].get("text", ""))
            elif "messageStop" in ev:
                print(f"[C stream] stopReason={ev['messageStop'].get('stopReason')}")
            elif "metadata" in ev:
                u = ev["metadata"].get("usage", {})
                print(f"[C stream] usage in={u.get('inputTokens')} out={u.get('outputTokens')}")
        dt = time.perf_counter() - t0
        print(f"[C stream] OK total={dt:.1f}s first_token={first:.1f}s chars={out_chars}")
    except ReadTimeoutError as e:
        print(f"[C stream] ReadTimeoutError: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model", default=os.environ.get("BEDROCK_MODEL_ID", "jp.anthropic.claude-opus-5-5")
    )
    ap.add_argument("--prompt-file", help="落ちたときと同じ大きさのプロンプト")
    ap.add_argument("--only", choices=["A", "B", "C"], help="1 本だけ")
    args = ap.parse_args()

    if args.prompt_file:
        with open(args.prompt_file, encoding="utf-8") as f:
            prompt = f.read()
    else:
        # 60s を超えるくらいの仕事をさせる
        prompt = (
            "Write a thorough, 3000-word design review of a hypothetical microservice "
            "that ingests S3 events, enriches them with DynamoDB lookups, and publishes "
            "to Kinesis. Cover failure modes, retries, idempotency, observability, and cost."
        )
    print(f"model={args.model} region={os.environ.get('AWS_REGION')} prompt_chars={len(prompt)}")

    if args.only in (None, "A"):
        run_converse(args.model, prompt, None, "A default(read_timeout=60)")
    if args.only in (None, "B"):
        run_converse(
            args.model, prompt, Config(read_timeout=1800, retries={"max_attempts": 1}), "B long"
        )
    if args.only in (None, "C"):
        run_stream(args.model, prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
