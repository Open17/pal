"""Bots: agent sessions, their prompts and settings, and the team that routes between them."""

from .agent import AgentClient, BotAgent, BotStatus, ClientFactory, WorkItem, default_client_factory
from .auth import AuthStatus, auth_status, scrub_api_credentials, session_environment
from .options import SessionOptionsBuilder
from .prompts import PromptContext, frame_message, system_prompt
from .state import BotStateStore, ModelOverride
from .team import BotTeam, UnknownBotError, UnknownMessageError

__all__ = [
    "AgentClient",
    "AuthStatus",
    "BotAgent",
    "BotStateStore",
    "BotStatus",
    "BotTeam",
    "ClientFactory",
    "ModelOverride",
    "PromptContext",
    "SessionOptionsBuilder",
    "UnknownBotError",
    "UnknownMessageError",
    "WorkItem",
    "auth_status",
    "default_client_factory",
    "frame_message",
    "scrub_api_credentials",
    "session_environment",
    "system_prompt",
]
