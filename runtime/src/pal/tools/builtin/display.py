"""Tools for a bot's own display on the shared computer."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import SdkMcpTool, tool

from pal.displays import DisplayBackendError, DisplayManager

from ..base import ToolContext, ToolProvider, ToolResult, error_result, text_result


class DisplayTools(ToolProvider):
    name = "display"
    description = "your desktop display: use_display, display_status"

    def __init__(self, displays: DisplayManager) -> None:
        self.displays = displays

    def tools(self, context: ToolContext) -> list[SdkMcpTool[Any]]:
        displays, bot_id = self.displays, context.bot_id

        @tool(
            "use_display",
            "Start or wake your desktop display before running graphical programs. Your "
            "shell already has DISPLAY set to it. The display sleeps on its own when idle; "
            "windows stay open while it sleeps.",
            {},
        )
        async def use_display(args: dict[str, Any]) -> ToolResult:
            try:
                display = await displays.ensure_awake(bot_id)
            except DisplayBackendError as exc:
                return error_result(f"Could not start your display: {exc}")
            return text_result(
                f"Display {display.name} is awake. Launch graphical programs with "
                "`pal-open <program> [args]` so they stay open with your display "
                f"(DISPLAY={display.name} is already set in your shell)."
            )

        @tool("display_status", "Show the state of your display.", {})
        async def display_status(args: dict[str, Any]) -> ToolResult:
            display = displays.get(bot_id)
            viewers = f", {display.viewers} viewer(s) watching" if display.viewers else ""
            return text_result(f"Display {display.name}: {display.state}{viewers}.")

        return [use_display, display_status]
