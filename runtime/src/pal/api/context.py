"""Services the API handlers operate on."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from aiohttp import web

from pal.bots import AuthStatus, BotAgent, BotTeam
from pal.config import PalConfig
from pal.displays import DisplayManager
from pal.memory import MemoryService
from pal.messaging import EventBus, Messenger


class TeamManagement(Protocol):
    async def add_bot(
        self, name: str, *, role: str = "", persona: str = "", color: str | None = None
    ) -> BotAgent: ...

    async def remove_bot(self, bot_id: str) -> None: ...


@dataclass
class ApiContext:
    config: PalConfig
    team: BotTeam
    memory: MemoryService
    messenger: Messenger
    displays: DisplayManager
    bus: EventBus
    api_token: str
    auth_status: Callable[[], AuthStatus]
    version: str
    #: Adding and removing bots; None where the team is fixed (tests).
    bots: TeamManagement | None = None


CONTEXT = web.AppKey("pal_context", ApiContext)


def context(request: web.Request) -> ApiContext:
    return request.app[CONTEXT]
