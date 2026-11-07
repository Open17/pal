from __future__ import annotations

from pathlib import Path

import pytest

from pal.config import DisplaySettings
from pal.displays import DisplayManager, InMemoryDisplayBackend
from pal.memory import MemoryService
from pal.tools.builtin import (
    DisplayTools,
    MemoryTools,
    TeamMember,
    TeamMessagingError,
    TeamTools,
)
from tests.tools.helpers import handlers, text


@pytest.fixture
def memory(tmp_path: Path) -> MemoryService:
    return MemoryService(tmp_path / "memory")


async def test_memory_tools_round_trip(memory: MemoryService) -> None:
    tools = handlers(MemoryTools(memory))
    saved = await tools["remember"](
        {"title": "Office wifi", "content": "Network: pal-net", "scope": "shared", "tags": ["net"]}
    )
    assert "`office-wifi`" in text(saved)

    found = await tools["recall"]({"query": "wifi"})
    assert "[shared] `office-wifi` — Office wifi (by atlas" in text(found)

    full = await tools["read_memory"]({"id": "office-wifi", "scope": "shared"})
    assert "Network: pal-net" in text(full)

    assert "Forgot" in text(await tools["forget"]({"id": "office-wifi", "scope": "shared"}))
    missing = await tools["read_memory"]({"id": "office-wifi", "scope": "shared"})
    assert missing["is_error"] is True


async def test_private_memory_tools_are_per_bot(memory: MemoryService) -> None:
    atlas, scout = handlers(MemoryTools(memory), "atlas"), handlers(MemoryTools(memory), "scout")
    await atlas["remember"]({"title": "Diary", "content": "x", "scope": "private"})
    assert text(await scout["recall"]({"query": "diary"})) == "No matching memories."
    assert "Diary" in text(await atlas["recall"]({"query": "diary", "scope": "private"}))


class FakeTeam:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, bool]] = []

    def roster(self) -> list[TeamMember]:
        return [
            TeamMember("atlas", "Atlas", "Coordinator", "idle"),
            TeamMember("scout", "Scout", "Researcher", "busy"),
        ]

    async def send(self, sender, recipient, content, *, wait_for_reply):
        if recipient == "ghost":
            raise TeamMessagingError("There is no bot called ghost.")
        self.sent.append((sender, recipient, content, wait_for_reply))
        return "on it" if wait_for_reply else None


async def test_team_tools() -> None:
    team = FakeTeam()
    tools = handlers(TeamTools(team))
    assert text(await tools["list_bots"]({})) == "- scout (Scout, Researcher): busy"

    reply = await tools["message_bot"]({"to": "scout", "message": "q", "wait_for_reply": True})
    assert text(reply) == "Reply from scout:\n\non it"
    queued = await tools["message_bot"]({"to": "scout", "message": "fyi", "wait_for_reply": False})
    assert text(queued) == "Message queued for scout."
    assert team.sent == [("atlas", "scout", "q", True), ("atlas", "scout", "fyi", False)]

    failed = await tools["message_bot"]({"to": "ghost", "message": "?", "wait_for_reply": True})
    assert failed["is_error"] is True


async def test_display_tools(tmp_path: Path) -> None:
    manager = DisplayManager(
        DisplaySettings(backend="simulated"), InMemoryDisplayBackend(), tmp_path / "d.json"
    )
    manager.register(["atlas"])
    tools = handlers(DisplayTools(manager))
    assert text(await tools["display_status"]({})) == "Display :10: stopped."
    assert "Display :10 is awake" in text(await tools["use_display"]({}))
    assert text(await tools["display_status"]({})) == "Display :10: running."
