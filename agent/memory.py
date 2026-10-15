"""AgentCore Memory（短期）で会話を続ける。

Runtime セッションの microVM は idle で消えるので、履歴はここに置く。
actor_id = 誰と話しているか（人）、session_id = 会話の筋。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from bedrock_agentcore.memory import MemoryClient

logger = logging.getLogger("agent.memory")

MAX_TURNS = 40


class Conversation:
    def __init__(self, actor_id: str, session_id: str) -> None:
        self.memory_id = os.environ.get("MEMORY_ID")
        self.actor_id = actor_id
        self.session_id = session_id
        self._client = (
            MemoryClient(region_name=os.environ.get("AWS_REGION", "ap-northeast-1"))
            if self.memory_id
            else None
        )

    def history(self) -> list[dict[str, Any]]:
        """Strands の messages 形式で過去ターンを返す（新しい順→古い順に直す）。"""
        if not self._client:
            return []
        try:
            events = self._client.list_events(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                max_results=MAX_TURNS,
            )
        except Exception:  # noqa: BLE001 - 記憶が読めなくても会話は続ける
            logger.exception("list_events failed")
            return []
        messages: list[dict[str, Any]] = []
        for ev in reversed(events):
            for p in ev.get("payload", []):
                conv = p.get("conversational")
                if not conv:
                    continue
                role = "user" if conv.get("role", "").upper() == "USER" else "assistant"
                text = conv.get("content", {}).get("text", "")
                if text:
                    messages.append({"role": role, "content": [{"text": text}]})
        return messages

    def save(self, user_text: str, assistant_text: str) -> None:
        if not self._client:
            return
        try:
            self._client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[(user_text, "USER"), (assistant_text, "ASSISTANT")],
            )
        except Exception:  # noqa: BLE001
            logger.exception("create_event failed")
