"""Builds the agent session options for each bot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, HookContext, HookMatcher

from pal.config import BotDefinition, ModelSettings, PalConfig
from pal.displays import DisplayBackendError, DisplayManager
from pal.log import get_logger
from pal.memory import MemoryService
from pal.tools import ToolContext, ToolRegistry

from .auth import session_environment
from .prompts import PromptContext, system_prompt

log = get_logger(__name__)

HookResult = dict[str, Any]


class SessionOptionsBuilder:
    def __init__(
        self,
        config: PalConfig,
        tools: ToolRegistry,
        memory: MemoryService,
        displays: DisplayManager,
    ) -> None:
        self.config = config
        self.tools = tools
        self.memory = memory
        self.displays = displays

    def build(
        self, bot: BotDefinition, settings: ModelSettings, *, resume: str | None
    ) -> ClaudeAgentOptions:
        paths, agent = self.config.paths, self.config.agent
        paths.workspaces.mkdir(parents=True, exist_ok=True)

        prompt = system_prompt(
            PromptContext(
                bot=bot,
                teammates=[mate for mate in self.config.bots if mate.id != bot.id],
                paths=paths,
                display=self.displays.get(bot.id).name,
                idle_minutes=max(1, self.config.displays.idle_timeout_seconds // 60),
                memory_digest=self.memory.digest(bot.id),
                tools=self.tools.describe(),
            )
        )
        env = {
            **session_environment(paths.secrets),
            **self.displays.environment(bot.id),
            "PAL_BOT_ID": bot.id,
            "PAL_WORKSPACE": str(paths.workspaces),
        }
        options = ClaudeAgentOptions(
            model=settings.model,
            effort=settings.effort,
            system_prompt={"type": "preset", "preset": "claude_code", "append": prompt},
            cwd=str(paths.workspaces),
            mcp_servers=self.tools.mcp_servers(ToolContext(bot.id)),
            allowed_tools=self.tools.allowed_tools(),
            permission_mode=agent.permission_mode,
            setting_sources=["project"],
            resume=resume,
            env=env,
            include_partial_messages=True,
            hooks=self._hooks(bot.id),
            max_turns=agent.max_turns,
        )
        if agent.thinking_display:
            options.thinking = {"type": "adaptive", "display": agent.thinking_display}
        if agent.cli_path:
            options.cli_path = agent.cli_path
        return options

    def _hooks(self, bot_id: str) -> dict[str, list[HookMatcher]]:
        hooks: dict[str, list[HookMatcher]] = {
            # Shell commands may be driving the desktop; keep a live display awake.
            "PostToolUse": [HookMatcher(matcher="Bash", hooks=[self._touch_display(bot_id)])],
        }
        matcher = self.tools.display_tool_matcher()
        if matcher:
            hooks["PreToolUse"] = [
                HookMatcher(matcher=matcher, hooks=[self._wake_display(bot_id)], timeout=60)
            ]
        return hooks

    def _wake_display(self, bot_id: str) -> Callable[..., Any]:
        displays = self.displays

        async def wake(input_data: dict[str, Any], tool_use_id: str | None, context: HookContext):
            try:
                await displays.ensure_awake(bot_id)
            except DisplayBackendError as exc:
                return _deny(f"Your display could not be started: {exc}")
            return {}

        return wake

    def _touch_display(self, bot_id: str) -> Callable[..., Any]:
        displays = self.displays

        async def touch(input_data: dict[str, Any], tool_use_id: str | None, context: HookContext):
            if displays.get(bot_id).state == "running":
                displays.touch(bot_id)
            return {}

        return touch


def _deny(reason: str) -> HookResult:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
