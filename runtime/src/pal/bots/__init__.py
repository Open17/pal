"""Bots: agent sessions, their prompts and settings, and the team that routes between them."""

from .agent import AgentClient, BotAgent, BotStatus, ClientFactory, WorkItem, default_client_factory
from .auth import AuthStatus, auth_status, scrub_api_credentials, session_environment
from .greeting import (
    GREETING_EFFORT,
    GREETING_MODEL,
    Greeter,
    ModelGreeter,
    fallback_greeting,
)
from .options import SessionOptionsBuilder
from .prompts import PromptContext, frame_message, system_prompt
from .state import BotStateStore, ModelOverride
from .team import BotTeam, UnknownBotError, UnknownMessageError

__all__ = [
    "GREETING_EFFORT",
    "GREETING_MODEL",
    "AgentClient",
    "AuthStatus",
    "BotAgent",
    "BotStateStore",
    "BotStatus",
    "BotTeam",
    "ClientFactory",
    "Greeter",
    "ModelGreeter",
    "ModelOverride",
    "PromptContext",
    "SessionOptionsBuilder",
    "UnknownBotError",
    "UnknownMessageError",
    "WorkItem",
    "auth_status",
    "default_client_factory",
    "fallback_greeting",
    "frame_message",
    "scrub_api_credentials",
    "session_environment",
    "system_prompt",
]
