"""エージェントの道具。重い仕事は SQS に投げ、結果は S3 から読む。"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import boto3
from strands import tool

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
QUEUE_URL = os.environ["QUEUE_URL"]
RESULTS_BUCKET = os.environ["RESULTS_BUCKET"]
JOBS_TABLE = os.environ["JOBS_TABLE"]

_sqs = boto3.client("sqs", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)
_jobs = boto3.resource("dynamodb", region_name=REGION).Table(JOBS_TABLE)


def _job_id(repo: str, ref: str) -> str:
    return hashlib.sha256(f"{repo}\n{ref}".encode()).hexdigest()[:32]


@tool
def analyze_repo(repo: str, ref: str = "main", force: bool = False) -> str:
    """CodeCommit リポジトリの解析ジョブを投入する。数分〜数十分かかる。

    Args:
        repo: CodeCommit のリポジトリ名
        ref: ブランチまたはタグ（既定 main）
        force: 同じ commit を解析済みでもやり直す
    """
    job_id = _job_id(repo, ref)
    existing = _jobs.get_item(Key={"job_id": job_id}).get("Item")
    if existing and existing.get("status") == "running" and not force:
        return json.dumps({"job_id": job_id, "status": "already running"}, ensure_ascii=False)
    _sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {"repo": repo, "ref": ref, "force": force, "job_id": job_id, "requested_by": "agent"}
        ),
    )
    return json.dumps({"job_id": job_id, "status": "queued", "repo": repo, "ref": ref})


@tool
def job_status(job_id: str) -> str:
    """解析ジョブの状態（stage・トークン・エラー）を返す。"""
    item = _jobs.get_item(Key={"job_id": job_id}).get("Item")
    if not item:
        return json.dumps({"job_id": job_id, "status": "unknown"})
    keep = (
        "status",
        "stage",
        "repo",
        "ref",
        "commit",
        "started_at",
        "updated_at",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "error_class",
        "error",
        "result_key",
    )
    return json.dumps({k: item.get(k) for k in keep if k in item}, default=str, ensure_ascii=False)


@tool
def list_analyses(prefix: str = "") -> str:
    """解析済みリポジトリの一覧（最新 commit とキー）。"""
    out: list[dict[str, Any]] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=RESULTS_BUCKET, Prefix=f"repos/{prefix}"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/latest.json"):
                repo = obj["Key"].removeprefix("repos/").removesuffix("/latest.json")
                out.append({"repo": repo, "updated": obj["LastModified"].isoformat()})
    return json.dumps(out, ensure_ascii=False)


@tool
def get_analysis(repo: str, commit: str | None = None) -> str:
    """リポジトリの解析結果（JSON）を読む。commit 省略で最新。

    返る JSON を根拠に質問へ答えること。無いことは無いと言う。
    """
    if not commit:
        try:
            latest = _s3.get_object(Bucket=RESULTS_BUCKET, Key=f"repos/{repo}/latest.json")
        except _s3.exceptions.NoSuchKey:
            return json.dumps({"error": "not analyzed yet", "repo": repo})
        key = json.loads(latest["Body"].read())["key"]
    else:
        key = f"repos/{repo}/{commit}/analysis.json"
    try:
        obj = _s3.get_object(Bucket=RESULTS_BUCKET, Key=key)
    except _s3.exceptions.NoSuchKey:
        return json.dumps({"error": "not found", "key": key})
    return obj["Body"].read().decode("utf-8")


TOOLS = [analyze_repo, job_status, list_analyses, get_analysis]
