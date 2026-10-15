"""JSON 1 行ログ。job_id と hop を必ず乗せて、落ちた層を後から引けるようにする。"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from typing import Any

job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "job_id": job_id_var.get(),
            "msg": record.getMessage(),
        }
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc_class"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup(level: str = "INFO") -> logging.Logger:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # boto の DEBUG は多すぎる
    logging.getLogger("botocore").setLevel("WARNING")
    logging.getLogger("urllib3").setLevel("WARNING")
    return logging.getLogger("analyzer")


def event(logger: logging.Logger, hop: str, **fields: Any) -> None:
    """構造化イベント。hop = sqs.receive / git.clone / llm.chunk / s3.put ..."""
    logger.info(hop, extra={"extra": {"hop": hop, **fields}})


class Timer:
    """with Timer() as t: ... ; t.ms"""

    def __enter__(self) -> Timer:
        self._t0 = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = int((time.perf_counter() - self._t0) * 1000)
