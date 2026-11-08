"""Shared memory and per-bot knowledge, with the access rules between them."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .entry import MAX_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH, MemoryEntry
from .store import MemoryStore

Scope = Literal["shared", "private"]
SCOPES: tuple[Scope, ...] = ("shared", "private")


class MemoryAccessError(PermissionError):
    """Raised when a caller asks for memory it is not allowed to touch."""


@dataclass(frozen=True)
class RecallHit:
    scope: Scope
    owner: str | None  # bot id for private knowledge, None for shared memory
    entry: MemoryEntry
    score: float


class MemoryService:
    """Entry point for everything memory-related.

    Layout under ``root``::

        shared/<id>.md         visible to every bot and the user
        bots/<bot-id>/<id>.md  private knowledge of one bot

    Bots may read and write shared memory and their own knowledge only. The
    user (through the API) may read and write all of it.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.shared = MemoryStore(root / "shared", title="Shared memory")
        self._knowledge: dict[str, MemoryStore] = {}

    def knowledge(self, bot_id: str) -> MemoryStore:
        if bot_id not in self._knowledge:
            self._knowledge[bot_id] = MemoryStore(
                self.root / "bots" / bot_id, title=f"Knowledge of {bot_id}"
            )
        return self._knowledge[bot_id]

    async def forget_bot(self, bot_id: str) -> None:
        """Delete a removed bot's private knowledge. Shared memory stays."""

        self._knowledge.pop(bot_id, None)
        await asyncio.to_thread(shutil.rmtree, self.root / "bots" / bot_id, ignore_errors=True)

    def store(self, scope: Scope, owner: str | None) -> MemoryStore:
        if scope == "shared":
            return self.shared
        if not owner:
            raise MemoryAccessError("private knowledge requires a bot id")
        return self.knowledge(owner)

    # -- operations used by bots and the API ------------------------------

    async def remember(
        self,
        *,
        author: str,
        scope: Scope,
        title: str,
        body: str,
        description: str = "",
        kind: str = "note",
        tags: Iterable[str] = (),
        entry_id: str | None = None,
        owner: str | None = None,
    ) -> MemoryEntry:
        """Create a memory, or update it when ``entry_id`` names an existing one.

        ``owner`` is the bot whose private knowledge is targeted; it defaults
        to ``author`` so bots write to their own knowledge.
        """

        store = self.store(scope, owner or author)
        title = title.strip()[:MAX_TITLE_LENGTH]
        description = " ".join(description.split())[:MAX_DESCRIPTION_LENGTH]
        clean_tags = tuple(dict.fromkeys(tag.strip().lower() for tag in tags if tag.strip()))

        def write() -> MemoryEntry:
            existing = store.get(entry_id) if entry_id else None
            if existing is not None:
                entry = existing.updated(
                    title=title or existing.title,
                    body=body,
                    description=description or existing.description,
                    kind=kind or existing.kind,
                    tags=clean_tags or existing.tags,
                )
            else:
                entry = MemoryEntry(
                    id=entry_id or store.new_id(title),
                    title=title,
                    body=body,
                    description=description,
                    kind=kind,
                    tags=clean_tags,
                    author=author,
                )
            return store.put(entry)

        return await asyncio.to_thread(write)

    async def read(self, scope: Scope, owner: str | None, entry_id: str) -> MemoryEntry | None:
        store = self.store(scope, owner)
        return await asyncio.to_thread(store.get, entry_id)

    async def forget(self, scope: Scope, owner: str | None, entry_id: str) -> bool:
        store = self.store(scope, owner)
        return await asyncio.to_thread(store.delete, entry_id)

    async def list(self, scope: Scope, owner: str | None) -> list[MemoryEntry]:
        store = self.store(scope, owner)
        return await asyncio.to_thread(store.entries)

    async def recall(
        self,
        bot_id: str | None,
        query: str,
        *,
        scopes: Sequence[Scope] = SCOPES,
        limit: int = 8,
    ) -> list[RecallHit]:
        """Search shared memory and (for a bot) its own knowledge together."""

        def search() -> list[RecallHit]:
            hits: list[RecallHit] = []
            if "shared" in scopes:
                hits += [
                    RecallHit("shared", None, hit.entry, hit.score)
                    for hit in self.shared.search(query, limit=limit)
                ]
            if "private" in scopes and bot_id:
                hits += [
                    RecallHit("private", bot_id, hit.entry, hit.score)
                    for hit in self.knowledge(bot_id).search(query, limit=limit)
                ]
            hits.sort(key=lambda hit: (hit.score, hit.entry.updated_at), reverse=True)
            return hits[:limit]

        return await asyncio.to_thread(search)

    # -- prompt support ----------------------------------------------------

    def digest(self, bot_id: str, *, max_entries: int = 40) -> str:
        """An index of memories for a bot's system prompt.

        Lists titles and summaries only; the bot reads full entries on demand
        with its recall tool.
        """

        sections = [
            ("Your private knowledge", self.knowledge(bot_id).entries()),
            ("Shared team memory", self.shared.entries()),
        ]
        lines: list[str] = []
        for heading, entries in sections:
            lines.append(f"### {heading}")
            if not entries:
                lines.append("(empty)")
            for entry in entries[:max_entries]:
                lines.append(f"- `{entry.id}` — {entry.title}: {entry.summary}")
            if len(entries) > max_entries:
                lines.append(f"- … and {len(entries) - max_entries} more (use recall to search)")
            lines.append("")
        return "\n".join(lines).strip()
