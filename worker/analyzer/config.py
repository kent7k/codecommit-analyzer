"""環境変数 → 設定。値は Terraform の task definition が入れる。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"missing env: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "ap-northeast-1"))
    target_aws_region: str = field(
        default_factory=lambda: _env("TARGET_AWS_REGION", "ap-northeast-3")
    )
    queue_url: str = field(default_factory=lambda: _env("QUEUE_URL"))
    results_bucket: str = field(default_factory=lambda: _env("RESULTS_BUCKET"))
    jobs_table: str = field(default_factory=lambda: _env("JOBS_TABLE"))
    # jp. で国内完結。global. は国外へ流れる。
    model_id: str = field(
        default_factory=lambda: _env("BEDROCK_MODEL_ID", "jp.anthropic.claude-opus-5-5")
    )
    metrics_namespace: str = field(default_factory=lambda: _env("METRICS_NAMESPACE", "cc-analyzer"))
    work_dir: str = field(default_factory=lambda: _env("WORK_DIR", "/work"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # 1 チャンクに詰める文字数の上限（≒ tokens × 3.5）。
    chunk_chars: int = field(default_factory=lambda: int(_env("CHUNK_CHARS", "200000")))
    # 1 ファイルの上限。これより大きいファイルは先頭だけ読む。
    max_file_bytes: int = field(default_factory=lambda: int(_env("MAX_FILE_BYTES", "120000")))
    # 1 ジョブで読む総バイトの上限（コストの防波堤）。
    max_total_bytes: int = field(
        default_factory=lambda: int(_env("MAX_TOTAL_BYTES", str(6 * 1024 * 1024)))
    )
    # SQS 可視性の延長間隔（秒）。visibility timeout より短く。
    heartbeat_seconds: int = field(default_factory=lambda: int(_env("HEARTBEAT_SECONDS", "300")))
    visibility_extend_seconds: int = field(
        default_factory=lambda: int(_env("VISIBILITY_EXTEND_SECONDS", "900"))
    )
    # モデル呼び出しの read timeout（秒）。60s の既定が 120s 落ちの正体なので長く。
    llm_timeout_seconds: float = field(
        default_factory=lambda: float(_env("LLM_TIMEOUT_SECONDS", "1800"))
    )
    effort: str = field(default_factory=lambda: _env("LLM_EFFORT", "high"))
