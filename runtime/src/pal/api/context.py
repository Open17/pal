"""Services the API handlers operate on."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aiohttp import web

from pal.bots import AuthStatus, BotTeam
from pal.config import PalConfig
from pal.displays import DisplayManager
from pal.memory import MemoryService
from pal.messaging import EventBus, Messenger


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


CONTEXT = web.AppKey("pal_context", ApiContext)


def context(request: web.Request) -> ApiContext:
    return request.app[CONTEXT]
