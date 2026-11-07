"""Messages exchanged between the user and bots, and between bots."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pal.config import USER_ID

MessageKind = Literal["chat", "request", "reply", "notice"]
"""
- ``chat``: a message between the user and a bot.
- ``request``: a bot asks another bot and waits for an answer.
- ``reply``: the answer to a ``request``.
- ``notice``: a bot tells another bot something without waiting.
"""


_id_lock = threading.Lock()
_last_id_time = 0


def new_id(prefix: str) -> str:
    """A unique id that sorts by creation time.

    The time component is strictly increasing within the process, so ids made
    in the same instant still sort in creation order; the random suffix keeps
    ids from different processes apart.
    """

    global _last_id_time
    with _id_lock:
        _last_id_time = max(time.time_ns() // 1000, _last_id_time + 1)
        stamp = _last_id_time
    return f"{prefix}_{stamp:014x}{os.urandom(4).hex()}"


def conversation_id(a: str, b: str) -> str:
    """The stable id of the conversation between two participants.

    The user is always listed first; two bots are listed alphabetically, so
    both directions of a bot pair land in the same conversation.
    """

    if b == USER_ID:
        a, b = b, a
    if a != USER_ID and b < a:
        a, b = b, a
    return f"{a}--{b}"


def participants(conversation: str) -> tuple[str, str]:
    first, _, second = conversation.partition("--")
    if not first or not second:
        raise ValueError(f"invalid conversation id {conversation!r}")
    return first, second


@dataclass(frozen=True)
class Message:
    sender: str
    recipient: str
    content: str
    kind: MessageKind = "chat"
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("msg"))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def conversation_id(self) -> str:
        return conversation_id(self.sender, self.recipient)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["conversation_id"] = self.conversation_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            id=data["id"],
            sender=data["sender"],
            recipient=data["recipient"],
            content=data["content"],
            kind=data.get("kind", "chat"),
            reply_to=data.get("reply_to"),
            metadata=dict(data.get("metadata") or {}),
            created_at=datetime.fromisoformat(data["created_at"]),
        )
