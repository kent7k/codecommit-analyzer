"""AgentCore Runtime のエントリポイント。

payload: {"prompt": "...", "actor_id": "kento"}  (runtimeSessionId は Runtime が渡す)
応答はストリーミング（InvokeAgentRuntime は最大 60 分）。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from botocore.config import Config
from strands import Agent
from strands.models import BedrockModel

from memory import Conversation
from tools import TOOLS

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("agent")

app = BedrockAgentCoreApp()

SYSTEM = """あなたは SRE チームの相棒です。
CodeCommit のリポジトリ解析を依頼し、結果を読んで質問に答えます。

- 解析は非同期。analyze_repo で投入したら job_id を伝え、進捗は job_status で見る。
- 質問に答えるときは get_analysis の JSON を根拠にし、書いていないことは「解析結果に無い」と言う。
- 答えは短く、根拠のパスや名前を添える。
"""

MODEL = BedrockModel(
    model_id=os.environ.get("BEDROCK_MODEL_ID", "jp.anthropic.claude-opus-5-5"),
    region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
    # 既定 60s の read_timeout が「120s で落ちる」の正体。長い応答に耐える値に。
    boto_client_config=Config(
        read_timeout=1800, connect_timeout=30, retries={"max_attempts": 2, "mode": "adaptive"}
    ),
    streaming=True,
    cache_prompt="default",
)


@app.entrypoint
async def invoke(payload: dict[str, Any], context: Any) -> AsyncIterator[str]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        yield "prompt が空です。"
        return

    session_id = getattr(context, "session_id", None) or payload.get("session_id") or "default"
    actor_id = str(payload.get("actor_id", "default"))
    conv = Conversation(actor_id=actor_id, session_id=session_id)

    agent = Agent(model=MODEL, system_prompt=SYSTEM, tools=TOOLS, messages=conv.history())

    collected: list[str] = []
    async for ev in agent.stream_async(prompt):
        data = ev.get("data") if isinstance(ev, dict) else None
        if data:
            collected.append(data)
            yield data

    conv.save(prompt, "".join(collected))


if __name__ == "__main__":
    app.run()
