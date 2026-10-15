"""結果を S3 へ。機械向け JSON と人向け Markdown、最新を指す latest.json。"""

from __future__ import annotations

import json
from typing import Any

import boto3

from .llm import RepoAnalysis


def key_prefix(repo: str, commit: str) -> str:
    return f"repos/{repo}/{commit}"


def analysis_key(repo: str, commit: str) -> str:
    return f"{key_prefix(repo, commit)}/analysis.json"


def _section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    body = "\n".join(f"- {i}" for i in items)
    return f"\n## {title}\n\n{body}\n"


def to_markdown(a: RepoAnalysis, meta: dict[str, Any]) -> str:
    parts = [
        f"# {a.repo}\n",
        f"commit `{a.commit}` · analyzed {meta.get('finished_at', '')} · "
        f"model `{meta.get('model_id', '')}`\n",
        f"\n## 目的\n\n{a.purpose}\n",
        f"\n## アーキテクチャ\n\n{a.architecture}\n",
    ]
    if a.components:
        parts.append("\n## コンポーネント\n")
        for c in a.components:
            deps = f"（depends on: {', '.join(c.depends_on)}）" if c.depends_on else ""
            paths = f" — `{'`, `'.join(c.paths[:5])}`" if c.paths else ""
            parts.append(f"- **{c.name}** [{c.kind}]{paths}: {c.summary}{deps}")
        parts.append("")
    parts.append(_section("エントリポイント", a.entrypoints))
    parts.append(_section("外部依存", a.external_dependencies))
    parts.append(_section("ランタイム・ビルド", a.runtime_and_build))
    parts.append(_section("デプロイ・運用", a.deploy_and_operate))
    parts.append(_section("観測", a.observability))
    parts.append(_section("リスク", a.risks))
    parts.append(_section("未解決の問い", a.open_questions))
    parts.append(_section("オンボーディングの順", a.onboarding_steps))
    parts.append(
        "\n---\n"
        f"tokens: in {meta.get('input_tokens', 0)} / out {meta.get('output_tokens', 0)} / "
        f"cache read {meta.get('cache_read_tokens', 0)} · files read {meta.get('files_read', 0)} · "
        f"chunks {meta.get('chunks', 0)}\n"
    )
    return "\n".join(p for p in parts if p is not None)


class Reporter:
    def __init__(self, bucket: str, region: str) -> None:
        self._s3 = boto3.client("s3", region_name=region)
        self._bucket = bucket

    def exists(self, repo: str, commit: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=analysis_key(repo, commit))
            return True
        except self._s3.exceptions.ClientError:
            return False

    def put_chunk(self, repo: str, commit: str, index: int, payload: dict[str, Any]) -> None:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=f"chunks/{repo}/{commit}/{index:03d}.json",
            Body=json.dumps(payload, ensure_ascii=False).encode(),
            ContentType="application/json",
        )

    def put_result(self, a: RepoAnalysis, meta: dict[str, Any]) -> str:
        prefix = key_prefix(a.repo, a.commit)
        doc = {"meta": meta, "analysis": a.model_dump()}
        self._s3.put_object(
            Bucket=self._bucket,
            Key=f"{prefix}/analysis.json",
            Body=json.dumps(doc, ensure_ascii=False, indent=2).encode(),
            ContentType="application/json",
        )
        self._s3.put_object(
            Bucket=self._bucket,
            Key=f"{prefix}/README.md",
            Body=to_markdown(a, meta).encode(),
            ContentType="text/markdown; charset=utf-8",
        )
        self._s3.put_object(
            Bucket=self._bucket,
            Key=f"repos/{a.repo}/latest.json",
            Body=json.dumps({"commit": a.commit, "key": f"{prefix}/analysis.json"}).encode(),
            ContentType="application/json",
        )
        return f"{prefix}/analysis.json"
