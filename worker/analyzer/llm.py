"""Claude on Bedrock。

経路: bedrock-runtime の Messages API 口（/anthropic）に Anthropic SDK で。
     認証は SigV4 から作る短命 bearer token（aws-bedrock-token-generator）。
     → prompt caching・usage・streaming が SDK のまま使える。

落ちない作法:
- 常にストリーミング（60s 無音の read 待ちを作らない）。
- timeout は長く（既定 60s が「120s で落ちる」の正体）。
- 再試行は throttle / 5xx だけ。timeout は 1 回だけ。
- refusal は stop_reason で見る（HTTP 200 で来る）。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic
from aws_bedrock_token_generator import provide_token
from pydantic import BaseModel, Field, ValidationError

from .config import Settings
from .log import Timer, event

logger = logging.getLogger("analyzer.llm")


# --- 出力の形（Bedrock の Opus 5.5 は structured outputs 未対応なので prompt + 検証） ---


class Component(BaseModel):
    name: str
    kind: str = Field(
        default="other", description="service|library|job|infra|config|test|docs|other"
    )
    paths: list[str] = []
    summary: str
    depends_on: list[str] = []


class ChunkAnalysis(BaseModel):
    components: list[Component] = []
    entrypoints: list[str] = []
    external_dependencies: list[str] = Field(
        default=[], description="AWS services, DBs, queues, 3rd-party APIs"
    )
    runtime_and_build: list[str] = []
    operational_notes: list[str] = Field(default=[], description="SRE が知るべきこと")
    risks: list[str] = []
    open_questions: list[str] = []


class RepoAnalysis(BaseModel):
    repo: str
    commit: str
    purpose: str
    architecture: str
    components: list[Component] = []
    entrypoints: list[str] = []
    external_dependencies: list[str] = []
    runtime_and_build: list[str] = []
    deploy_and_operate: list[str] = []
    observability: list[str] = []
    risks: list[str] = []
    open_questions: list[str] = []
    onboarding_steps: list[str] = []


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    refusals: int = 0
    latencies_ms: list[int] = field(default_factory=list)

    def add(self, u: Any, ms: int) -> None:
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.calls += 1
        self.latencies_ms.append(ms)


SYSTEM_PROMPT = """あなたは SRE のオンボーディングを助けるコード解析者です。
与えられたリポジトリのソースを読み、運用者が「このリポジトリは何で、どう動き、どこを見れば
いいか」を最短で把握できる JSON を返します。

守ること:
- 推測は open_questions に入れ、本文では断定しない。
- 秘密らしき値（鍵・トークン・パスワード）は値を書かず、存在と場所だけ risks に書く。
- 出力は JSON のみ。前後に説明文やコードフェンスを付けない。
"""

CHUNK_INSTRUCTION = """次の JSON Schema に従って、このチャンクで分かったことだけを返してください。
分からない項目は空配列にします。

{schema}
"""

SYNTH_INSTRUCTION = """以下は同じリポジトリを分割して読んだ部分解析の一覧です。
重複をまとめ、矛盾があれば open_questions に書き、次の JSON Schema で 1 つの全体像にしてください。
onboarding_steps は「最初の 1 日で読む順」を 5〜10 手で。

{schema}

--- 部分解析 ---
{partials}
"""


class RefusedError(RuntimeError):
    pass


class Analyzer:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.usage = Usage()
        self._client: anthropic.Anthropic | None = None
        self._token_at = 0.0

    # --- client ---------------------------------------------------------------

    def client(self) -> anthropic.Anthropic:
        # token は短命なので 30 分ごとに作り直す
        if self._client is None or time.time() - self._token_at > 1800:
            token = provide_token(region=self.s.aws_region)
            self._client = anthropic.Anthropic(
                base_url=f"https://bedrock-runtime.{self.s.aws_region}.amazonaws.com/anthropic",
                api_key=token,
                timeout=self.s.llm_timeout_seconds,
                max_retries=0,  # 再試行は自前（throttle と timeout を区別する）
            )
            self._token_at = time.time()
        return self._client

    # --- core call ------------------------------------------------------------

    def _call(self, *, system: list[dict[str, Any]], user: list[dict[str, Any]], hop: str) -> str:
        attempts = 0
        while True:
            attempts += 1
            try:
                with (
                    Timer() as t,
                    self.client().messages.stream(
                        model=self.s.model_id,
                        max_tokens=32000,
                        system=system,
                        messages=[{"role": "user", "content": user}],
                        output_config={"effort": self.s.effort},
                    ) as stream,
                ):
                    msg = stream.get_final_message()
                self.usage.add(msg.usage, t.ms)
                event(
                    logger,
                    hop,
                    latency_ms=t.ms,
                    input_tokens=msg.usage.input_tokens,
                    output_tokens=msg.usage.output_tokens,
                    cache_read=getattr(msg.usage, "cache_read_input_tokens", 0),
                    cache_write=getattr(msg.usage, "cache_creation_input_tokens", 0),
                    stop_reason=msg.stop_reason,
                    attempt=attempts,
                )
                if msg.stop_reason == "refusal":
                    self.usage.refusals += 1
                    details = getattr(msg, "stop_details", None)
                    raise RefusedError(f"model refused: {details}")
                if msg.stop_reason == "max_tokens":
                    logger.warning("output truncated at max_tokens", extra={"extra": {"hop": hop}})
                return "".join(b.text for b in msg.content if b.type == "text")
            except anthropic.RateLimitError as e:
                if attempts >= 6:
                    raise
                wait = min(60, 2**attempts)
                event(logger, f"{hop}.throttled", attempt=attempts, wait_s=wait, error=str(e))
                time.sleep(wait)
            except anthropic.APIStatusError as e:
                if e.status_code >= 500 and attempts < 4:
                    wait = min(60, 2**attempts)
                    event(logger, f"{hop}.5xx", attempt=attempts, wait_s=wait, status=e.status_code)
                    time.sleep(wait)
                    continue
                raise
            except anthropic.APITimeoutError as e:
                # timeout は 1 回だけやり直す。2 回目はそのまま落とす（原因を残す）。
                if attempts >= 2:
                    raise
                event(logger, f"{hop}.timeout", attempt=attempts, error=str(e))
            except anthropic.APIConnectionError as e:
                if attempts >= 3:
                    raise
                event(logger, f"{hop}.connection", attempt=attempts, error=str(e))
                time.sleep(5)

    # --- parsing --------------------------------------------------------------

    @staticmethod
    def parse_json(text: str) -> dict[str, Any]:
        """モデルがフェンスを付けてきても拾う。"""
        s = text.strip()
        if s.startswith("```"):
            s = s.split("\n", 1)[1] if "\n" in s else s
            s = s.rsplit("```", 1)[0]
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in output")
        return json.loads(s[start : end + 1])

    def _parse_or_repair(self, text: str, model: type[BaseModel], hop: str) -> BaseModel:
        try:
            return model.model_validate(self.parse_json(text))
        except (ValueError, ValidationError) as e:
            event(logger, f"{hop}.repair", error=str(e)[:500])
            fixed = self._call(
                system=[
                    {"type": "text", "text": "You fix JSON to match a schema. Output JSON only."}
                ],
                user=[
                    {
                        "type": "text",
                        "text": (
                            f"Schema:\n{json.dumps(model.model_json_schema())}\n\n"
                            f"Error:\n{e}\n\nJSON to fix:\n{text}"
                        ),
                    }
                ],
                hop=f"{hop}.repair",
            )
            return model.model_validate(self.parse_json(fixed))

    # --- public ---------------------------------------------------------------

    def analyze_chunk(
        self, *, repo: str, commit: str, tree_text: str, chunk_text: str, index: int, total: int
    ) -> ChunkAnalysis:
        # system と tree は全チャンク共通 → cache。chunk 本体は毎回違う → 最後。
        system = [
            {"type": "text", "text": SYSTEM_PROMPT},
            {
                "type": "text",
                "text": f"Repository: {repo}\nCommit: {commit}\n\nFile tree:\n{tree_text}",
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            },
        ]
        user = [
            {
                "type": "text",
                "text": CHUNK_INSTRUCTION.format(
                    schema=json.dumps(ChunkAnalysis.model_json_schema(), ensure_ascii=False)
                ),
            },
            {"type": "text", "text": f"--- chunk {index + 1}/{total} ---\n{chunk_text}"},
        ]
        text = self._call(system=system, user=user, hop="llm.chunk")
        return self._parse_or_repair(text, ChunkAnalysis, "llm.chunk")  # type: ignore[return-value]

    def synthesize(
        self, *, repo: str, commit: str, tree_text: str, partials: list[ChunkAnalysis]
    ) -> RepoAnalysis:
        system = [
            {"type": "text", "text": SYSTEM_PROMPT},
            {
                "type": "text",
                "text": f"Repository: {repo}\nCommit: {commit}\n\nFile tree:\n{tree_text}",
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            },
        ]
        partial_text = "\n\n".join(
            f"[part {i + 1}]\n{p.model_dump_json(exclude_defaults=True)}"
            for i, p in enumerate(partials)
        )
        user = [
            {
                "type": "text",
                "text": SYNTH_INSTRUCTION.format(
                    schema=json.dumps(RepoAnalysis.model_json_schema(), ensure_ascii=False),
                    partials=partial_text,
                ),
            }
        ]
        text = self._call(system=system, user=user, hop="llm.synth")
        result = self._parse_or_repair(text, RepoAnalysis, "llm.synth")
        assert isinstance(result, RepoAnalysis)
        result.repo, result.commit = repo, commit
        return result
