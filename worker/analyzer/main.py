"""SQS を long polling して 1 件ずつ解析する。

メッセージ: {"repo": "<name>", "ref": "main", "requested_by": "...", "force": false}
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from datetime import UTC, datetime
from typing import Any

import boto3

from . import log as logmod
from .config import Settings
from .jobs import JobStore, job_id_for
from .llm import Analyzer, RefusedError
from .repo import chunk, clone, render_file, render_tree, snapshot
from .report import Reporter

logger = logging.getLogger("analyzer.main")
_stop = threading.Event()


def _handle_signal(signum: int, _frame: Any) -> None:
    logger.info("signal received, finishing current job", extra={"extra": {"signal": signum}})
    _stop.set()


class Heartbeat:
    """処理中は SQS の可視性を延ばし続ける（長いジョブでも二重配信させない）。"""

    def __init__(self, sqs: Any, queue_url: str, receipt: str, every: int, extend: int) -> None:
        self._sqs, self._url, self._receipt = sqs, queue_url, receipt
        self._every, self._extend = every, extend
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._done.wait(self._every):
            try:
                self._sqs.change_message_visibility(
                    QueueUrl=self._url, ReceiptHandle=self._receipt, VisibilityTimeout=self._extend
                )
                logmod.event(logger, "sqs.heartbeat", extend_s=self._extend)
            except Exception:  # noqa: BLE001 - ログして続ける
                logger.exception("heartbeat failed")

    def __enter__(self) -> Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._done.set()


def put_metrics(cw: Any, namespace: str, repo: str, **values: float) -> None:
    try:
        cw.put_metric_data(
            Namespace=namespace,
            MetricData=[
                {"MetricName": k, "Value": v, "Dimensions": [{"Name": "repo", "Value": repo}]}
                for k, v in values.items()
            ],
        )
    except Exception:  # noqa: BLE001
        logger.exception("put_metric_data failed")


def process(settings: Settings, body: dict[str, Any], jobs: JobStore, reporter: Reporter) -> None:
    repo = body["repo"]
    ref = body.get("ref", "main")
    force = bool(body.get("force", False))
    job_id = body.get("job_id") or job_id_for(repo, ref)
    logmod.job_id_var.set(job_id)

    cw = boto3.client("cloudwatch", region_name=settings.aws_region)
    jobs.start(job_id, repo, ref, body.get("requested_by"))
    t_start = time.perf_counter()

    try:
        with logmod.Timer() as t:
            path, commit = clone(repo, ref, settings.target_aws_region, settings.work_dir)
        logmod.event(logger, "git.clone", repo=repo, ref=ref, commit=commit, latency_ms=t.ms)
        jobs.update(job_id, stage="snapshot", commit=commit)

        # 冪等：同じ commit の結果があれば読まない（= 課金しない）
        if not force and reporter.exists(repo, commit):
            key = f"repos/{repo}/{commit}/analysis.json"
            logmod.event(logger, "job.skip", reason="already analyzed", key=key)
            jobs.skip(job_id, key, commit)
            return

        snap = snapshot(
            path,
            repo,
            commit,
            max_file_bytes=settings.max_file_bytes,
            max_total_bytes=settings.max_total_bytes,
        )
        chunks = chunk(snap.files, settings.chunk_chars)
        logmod.event(
            logger,
            "repo.snapshot",
            files_total=len(snap.tree),
            files_read=len(snap.files),
            skipped_bytes=snap.skipped_bytes,
            chunks=len(chunks),
        )
        jobs.update(job_id, stage="analyze", chunks=len(chunks), files_read=len(snap.files))

        analyzer = Analyzer(settings)
        tree_text = render_tree(snap.tree)
        partials = []
        for i, files in enumerate(chunks):
            text = "\n".join(render_file(f) for f in files)
            part = analyzer.analyze_chunk(
                repo=repo, commit=commit, tree_text=tree_text, chunk_text=text,
                index=i, total=len(chunks),
            )  # fmt: skip
            partials.append(part)
            reporter.put_chunk(repo, commit, i, part.model_dump())
            jobs.update(job_id, stage=f"analyze {i + 1}/{len(chunks)}")
            u = analyzer.usage
            jobs.add_usage(
                job_id,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cache_read_tokens=u.cache_read_tokens,
                cache_write_tokens=u.cache_write_tokens,
            )
            analyzer.usage = type(u)()  # 加算済みぶんをリセット

        jobs.update(job_id, stage="synthesize")
        analysis = analyzer.synthesize(
            repo=repo, commit=commit, tree_text=tree_text, partials=partials
        )
        u = analyzer.usage
        jobs.add_usage(
            job_id,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_tokens,
            cache_write_tokens=u.cache_write_tokens,
        )

        record = jobs.get(job_id) or {}
        meta = {
            "job_id": job_id,
            "model_id": settings.model_id,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "duration_s": round(time.perf_counter() - t_start, 1),
            "files_total": len(snap.tree),
            "files_read": len(snap.files),
            "chunks": len(chunks),
            "input_tokens": int(record.get("input_tokens", 0)),
            "output_tokens": int(record.get("output_tokens", 0)),
            "cache_read_tokens": int(record.get("cache_read_tokens", 0)),
            "cache_write_tokens": int(record.get("cache_write_tokens", 0)),
        }
        key = reporter.put_result(analysis, meta)
        jobs.finish(job_id, key, commit)
        logmod.event(
            logger, "job.done", key=key, **{k: v for k, v in meta.items() if k != "job_id"}
        )

        put_metrics(
            cw,
            settings.metrics_namespace,
            repo,
            JobDurationSeconds=meta["duration_s"],
            InputTokens=meta["input_tokens"],
            OutputTokens=meta["output_tokens"],
            CacheReadTokens=meta["cache_read_tokens"],
            JobsDone=1,
        )
    except RefusedError as e:
        jobs.fail(job_id, type(e).__name__, str(e))
        logger.exception("job refused by model")
        put_metrics(cw, settings.metrics_namespace, repo, JobsRefused=1)
        # refusal は再試行しても同じ → 例外を投げず DLQ に行かせない
    except Exception as e:
        jobs.fail(job_id, type(e).__name__, str(e))
        logger.exception("job failed")
        put_metrics(cw, settings.metrics_namespace, repo, JobsFailed=1)
        raise


def run() -> None:
    settings = Settings()
    logmod.setup(settings.log_level)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    sqs = boto3.client("sqs", region_name=settings.aws_region)
    jobs = JobStore(settings.jobs_table, settings.aws_region)
    reporter = Reporter(settings.results_bucket, settings.aws_region)
    logger.info("worker started", extra={"extra": {"model_id": settings.model_id}})

    while not _stop.is_set():
        resp = sqs.receive_message(
            QueueUrl=settings.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            AttributeNames=["ApproximateReceiveCount"],
        )
        for m in resp.get("Messages", []):
            receipt = m["ReceiptHandle"]
            try:
                body = json.loads(m["Body"])
            except json.JSONDecodeError:
                logger.error(
                    "bad message body, deleting", extra={"extra": {"body": m["Body"][:200]}}
                )
                sqs.delete_message(QueueUrl=settings.queue_url, ReceiptHandle=receipt)
                continue
            logmod.event(
                logger,
                "sqs.receive",
                repo=body.get("repo"),
                receive_count=m.get("Attributes", {}).get("ApproximateReceiveCount"),
            )
            try:
                with Heartbeat(
                    sqs,
                    settings.queue_url,
                    receipt,
                    settings.heartbeat_seconds,
                    settings.visibility_extend_seconds,
                ):
                    process(settings, body, jobs, reporter)
            except Exception:  # noqa: BLE001 - process 側でログ済み。削除せず再配信 → 2 回で DLQ
                continue
            sqs.delete_message(QueueUrl=settings.queue_url, ReceiptHandle=receipt)
            logmod.job_id_var.set("-")

    logger.info("worker stopped")


if __name__ == "__main__":
    run()
