from __future__ import annotations

from typing import Any

import pytest
from claude_agent_sdk import SdkMcpTool, tool

from pal.tools import ToolContext, ToolProvider, ToolRegistry, text_result


class Echo(ToolProvider):
    name = "echo"
    description = "echoes"

    def tools(self, context: ToolContext) -> list[SdkMcpTool[Any]]:
        @tool("say", "Echo", {"text": str})
        async def say(args: dict[str, Any]) -> dict[str, Any]:
            return text_result(f"{context.bot_id}: {args['text']}")

        return [say]


class Screen(Echo):
    name = "screen"
    description = ""
    requires_display = True


def test_servers_and_permissions() -> None:
    registry = ToolRegistry([Echo(), Screen()])
    servers = registry.mcp_servers(ToolContext("atlas"))
    assert set(servers) == {"pal_echo", "pal_screen"}
    assert all(server["type"] == "sdk" for server in servers.values())
    assert registry.allowed_tools() == ["mcp__pal_echo", "mcp__pal_screen"]


def test_display_matcher_only_covers_display_providers() -> None:
    registry = ToolRegistry([Echo(), Screen()])
    assert registry.requires_display("mcp__pal_screen__click")
    assert not registry.requires_display("mcp__pal_echo__say")
    assert not registry.requires_display("Bash")
    assert ToolRegistry([Echo()]).display_tool_matcher() is None


def test_describe_skips_providers_without_description() -> None:
    assert ToolRegistry([Echo(), Screen()]).describe() == "- `mcp__pal_echo__*` — echoes"


def test_duplicate_and_invalid_names_rejected() -> None:
    registry = ToolRegistry([Echo()])
    with pytest.raises(ValueError, match="already registered"):
        registry.add(Echo())
    bad = Echo()
    bad.name = "Bad-Name"
    with pytest.raises(ValueError, match="invalid"):
        registry.add(bad)


async def test_tools_know_their_bot() -> None:
    (say,) = Echo().tools(ToolContext("scout"))
    result = await say.handler({"text": "hi"})
    assert result["content"][0]["text"] == "scout: hi"
