"""Messages exchanged between the user and bots, and between bots."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pal.config import USER_ID

MessageKind = Literal["chat", "request", "reply", "notice", "reaction"]
"""
- ``chat``: a message between the user and a bot.
- ``request``: a bot asks another bot and waits for an answer.
- ``reply``: the answer to a ``request``.
- ``notice``: a bot tells another bot something without waiting.
- ``reaction``: an emoji on the message named by ``reply_to``. A sender has one
  reaction per message: a later one replaces it, and an empty one removes it.
"""

#: Long enough for any emoji sequence (flags, skin tones, families).
MAX_REACTION_LENGTH = 16


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


def clean_reaction(emoji: str, *, allow_empty: bool) -> str:
    """A reaction as stored: trimmed, short, and non-empty unless removing one."""

    emoji = emoji.strip()
    if not emoji and not allow_empty:
        raise ValueError("a reaction needs an emoji")
    if len(emoji) > MAX_REACTION_LENGTH or any(c.isspace() for c in emoji):
        raise ValueError("a reaction is a single emoji")
    return emoji


def excerpt(text: str, limit: int = 120) -> str:
    """One line of a message, for quoting it back to a bot."""

    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


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
