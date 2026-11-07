"""The contract every tool provider implements.

A provider contributes a group of in-process tools to each bot's agent
session. Tools are built per bot so handlers know which bot is calling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import SdkMcpTool

ToolResult = dict[str, Any]


@dataclass(frozen=True)
class ToolContext:
    """Who is using the tools."""

    bot_id: str


class ToolProvider(ABC):
    #: Short identifier; tools are exposed to bots as ``mcp__pal_<name>__<tool>``.
    name: str
    #: One line shown in the bot's system prompt.
    description: str = ""
    #: When true, the bot's display is started or woken before any of these
    #: tools run, and their use counts as display activity.
    requires_display: bool = False

    @abstractmethod
    def tools(self, context: ToolContext) -> list[SdkMcpTool[Any]]:
        """Build this provider's tools for one bot."""

    @property
    def server_name(self) -> str:
        return f"pal_{self.name}"


def text_result(text: str) -> ToolResult:
    return {"content": [{"type": "text", "text": text}]}


def error_result(text: str) -> ToolResult:
    return {"content": [{"type": "text", "text": text}], "is_error": True}
