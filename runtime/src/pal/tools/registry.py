"""Collects tool providers and turns them into agent session options."""

from __future__ import annotations

import re
from collections.abc import Iterable

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server

from .base import ToolContext, ToolProvider


class ToolRegistry:
    def __init__(self, providers: Iterable[ToolProvider] = ()) -> None:
        self._providers: dict[str, ToolProvider] = {}
        for provider in providers:
            self.add(provider)

    def add(self, provider: ToolProvider) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", provider.name):
            raise ValueError(f"invalid tool provider name {provider.name!r}")
        if provider.name in self._providers:
            raise ValueError(f"tool provider {provider.name!r} is already registered")
        self._providers[provider.name] = provider

    @property
    def providers(self) -> list[ToolProvider]:
        return list(self._providers.values())

    def mcp_servers(self, context: ToolContext) -> dict[str, McpSdkServerConfig]:
        return {
            provider.server_name: create_sdk_mcp_server(
                name=provider.server_name, tools=provider.tools(context)
            )
            for provider in self._providers.values()
        }

    def allowed_tools(self) -> list[str]:
        """Permission rules that allow every tool of every registered provider."""

        return [f"mcp__{provider.server_name}" for provider in self._providers.values()]

    def display_tool_matcher(self) -> str | None:
        """A hook matcher for tools that need the bot's display, if any."""

        names = [
            re.escape(f"mcp__{provider.server_name}__")
            for provider in self._providers.values()
            if provider.requires_display
        ]
        return f"^({'|'.join(names)}).*" if names else None

    def requires_display(self, tool_name: str) -> bool:
        matcher = self.display_tool_matcher()
        return bool(matcher and re.match(matcher, tool_name))

    def describe(self) -> str:
        """A short list of tool groups for the bot's system prompt."""

        return "\n".join(
            f"- `mcp__{provider.server_name}__*` — {provider.description}"
            for provider in self._providers.values()
            if provider.description
        )
