"""手でジョブを投げる。AgentCore を通さず worker だけ試すとき用。

QUEUE_URL=... uv run python scripts/enqueue.py my-repo --ref main
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os

import boto3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--ref", default="main")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--queue-url", default=os.environ.get("QUEUE_URL"))
    args = ap.parse_args()
    if not args.queue_url:
        raise SystemExit("--queue-url か QUEUE_URL が要る")

    job_id = hashlib.sha256(f"{args.repo}\n{args.ref}".encode()).hexdigest()[:32]
    body = {
        "repo": args.repo,
        "ref": args.ref,
        "force": args.force,
        "job_id": job_id,
        "requested_by": os.environ.get("USER", "cli"),
    }
    boto3.client("sqs").send_message(QueueUrl=args.queue_url, MessageBody=json.dumps(body))
    print(json.dumps(body, ensure_ascii=False))


if __name__ == "__main__":
    main()
