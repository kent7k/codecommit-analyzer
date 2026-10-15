"""ジョブ状態（DynamoDB）。「今どこ？」「何トークン使った？」に答える器。"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import boto3

TTL_DAYS = 90


def job_id_for(repo: str, ref: str) -> str:
    """同じ repo+ref は同じ job_id。再投入しても二重に走らない。"""
    return hashlib.sha256(f"{repo}\n{ref}".encode()).hexdigest()[:32]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self._table.get_item(Key={"job_id": job_id}).get("Item")

    def start(self, job_id: str, repo: str, ref: str, requested_by: str | None) -> None:
        self._table.put_item(
            Item={
                "job_id": job_id,
                "repo": repo,
                "ref": ref,
                "requested_by": requested_by or "-",
                "status": "running",
                "stage": "clone",
                "started_at": _now(),
                "updated_at": _now(),
                "expires_at": int(time.time()) + TTL_DAYS * 86400,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
            }
        )

    def update(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        names = {f"#{k}": k for k in fields}
        values = {f":{k}": v for k, v in fields.items()}
        expr = ", ".join(f"#{k} = :{k}" for k in fields)
        self._table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=f"SET {expr}",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def add_usage(
        self,
        job_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> None:
        self._table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=(
                "ADD input_tokens :i, output_tokens :o, cache_read_tokens :cr, "
                "cache_write_tokens :cw SET updated_at = :t"
            ),
            ExpressionAttributeValues={
                ":i": input_tokens,
                ":o": output_tokens,
                ":cr": cache_read_tokens,
                ":cw": cache_write_tokens,
                ":t": _now(),
            },
        )

    def finish(self, job_id: str, result_key: str, commit: str) -> None:
        self.update(job_id, status="done", stage="done", result_key=result_key, commit=commit)

    def fail(self, job_id: str, exc_class: str, message: str) -> None:
        self.update(job_id, status="failed", error_class=exc_class, error=message[:2000])

    def skip(self, job_id: str, result_key: str, commit: str) -> None:
        self.update(job_id, status="done", stage="skipped", result_key=result_key, commit=commit)
