"""Append-only JSONL logs, one file per conversation."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pal.log import get_logger

from .models import Message, participants

log = get_logger(__name__)


@dataclass(frozen=True)
class ConversationSummary:
    id: str
    participants: tuple[str, str]
    message_count: int
    last_message: Message | None


class ConversationLog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def path_for(self, conversation: str) -> Path:
        participants(conversation)  # validates the id
        if "/" in conversation or conversation.startswith("."):
            raise ValueError(f"invalid conversation id {conversation!r}")
        return self.root / f"{conversation}.jsonl"

    async def append(self, message: Message) -> None:
        path = self.path_for(message.conversation_id)
        line = json.dumps(message.to_dict(), ensure_ascii=False) + "\n"
        async with self._locks[message.conversation_id]:
            await asyncio.to_thread(_append_line, path, line)

    async def read(
        self, conversation: str, *, limit: int = 100, before: str | None = None
    ) -> list[Message]:
        """The newest ``limit`` messages, oldest first, optionally before an id."""

        path = self.path_for(conversation)
        messages = await asyncio.to_thread(_read_messages, path)
        if before is not None:
            index = next((i for i, m in enumerate(messages) if m.id == before), len(messages))
            messages = messages[:index]
        return messages[-limit:] if limit > 0 else messages

    async def find(self, conversation: str, message_id: str) -> Message | None:
        """One message of a conversation by id, or None."""

        messages = await asyncio.to_thread(_read_messages, self.path_for(conversation))
        return next((m for m in messages if m.id == message_id), None)

    async def delete_with(self, participant: str) -> list[str]:
        """Delete every conversation someone took part in; returns their ids."""

        def delete() -> list[str]:
            if not self.root.is_dir():
                return []
            deleted = []
            for path in self.root.glob("*.jsonl"):
                try:
                    pair = participants(path.stem)
                except ValueError:
                    continue
                if participant in pair:
                    path.unlink(missing_ok=True)
                    deleted.append(path.stem)
            return deleted

        return await asyncio.to_thread(delete)

    async def conversations(self) -> list[ConversationSummary]:
        def summarize() -> list[ConversationSummary]:
            if not self.root.is_dir():
                return []
            summaries = []
            for path in self.root.glob("*.jsonl"):
                try:
                    pair = participants(path.stem)
                except ValueError:
                    continue
                messages = _read_messages(path)
                summaries.append(
                    ConversationSummary(
                        path.stem, pair, len(messages), messages[-1] if messages else None
                    )
                )
            summaries.sort(
                key=lambda s: s.last_message.created_at.isoformat() if s.last_message else "",
                reverse=True,
            )
            return summaries

        return await asyncio.to_thread(summarize)


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _read_messages(path: Path) -> list[Message]:
    if not path.is_file():
        return []
    messages: list[Message] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                messages.append(Message.from_dict(json.loads(line)))
            except (ValueError, KeyError) as exc:
                log.warning("%s:%d: skipping malformed message: %s", path, number, exc)
    return messages
