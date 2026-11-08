"""A bot's first message: a short hello, written by a small, fast model.

Every bot says hello when it joins the team, so a new chat never opens
empty. The greeting comes from a one-off call with no tools, separate from
the bot's own session; the bot is told what it said with its next message.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from pal.config import BotDefinition
from pal.log import get_logger

from .auth import session_environment

log = get_logger(__name__)

GREETING_MODEL = "claude-haiku-5-5"
GREETING_EFFORT = "medium"
GREETING_TIMEOUT_SECONDS = 60

Greeter = Callable[[BotDefinition], Awaitable[str]]
QueryFunction = Callable[..., AsyncIterator[Any]]


def fallback_greeting(bot: BotDefinition) -> str:
    """The hello used when the model can't be reached (e.g. not signed in yet)."""

    role = f", your {bot.role.lower()}" if bot.role else ""
    return f"Hi, I'm {bot.name}{role}! What can I help you with?"


def greeting_prompt(bot: BotDefinition) -> str:
    role = f" Your role on the team: {bot.role}." if bot.role else ""
    persona = f"\n\nHow you work:\n{bot.persona}" if bot.persona else ""
    return (
        f"You are {bot.name}, a bot that was just added to the user's team.{role}{persona}\n\n"
        "Write your first message to the user: one or two short, friendly sentences that "
        "say hello, introduce yourself and what you can help with, and invite them to "
        "start. Plain text only: no markdown, no quotation marks, no sign-off."
    )


class ModelGreeter:
    """Writes greetings with a one-off, tool-free agent call."""

    def __init__(
        self,
        secrets: Path,
        cwd: Path,
        *,
        cli_path: str | None = None,
        query_fn: QueryFunction = query,
    ) -> None:
        self.secrets = secrets
        self.cwd = cwd
        self.cli_path = cli_path
        self._query = query_fn

    def options(self) -> ClaudeAgentOptions:
        options = ClaudeAgentOptions(
            model=GREETING_MODEL,
            effort=GREETING_EFFORT,
            tools=[],
            max_turns=1,
            cwd=str(self.cwd),
            env=session_environment(self.secrets),
        )
        if self.cli_path:
            options.cli_path = self.cli_path
        return options

    async def __call__(self, bot: BotDefinition) -> str:
        parts: list[str] = []
        result = ""
        async with asyncio.timeout(GREETING_TIMEOUT_SECONDS):
            async for message in self._query(prompt=greeting_prompt(bot), options=self.options()):
                if isinstance(message, AssistantMessage):
                    parts.extend(b.text for b in message.content if isinstance(b, TextBlock))
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        raise RuntimeError("; ".join(message.errors or []) or message.subtype)
                    result = message.result or ""
        return clean_greeting(result or "".join(parts))


def clean_greeting(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return text
