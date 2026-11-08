from __future__ import annotations

from pathlib import Path

from pal.bots import SessionOptionsBuilder
from pal.config import BotDefinition, DisplaySettings, ModelSettings, PalConfig, PathSettings
from pal.displays import DisplayManager, InMemoryDisplayBackend
from pal.memory import MemoryService
from pal.tools import ToolRegistry
from pal.tools.builtin import DisplayTools, MemoryTools
from tests.tools.test_registry import Screen


def build(tmp_path: Path, *providers):
    paths = PathSettings(tmp_path / "ws", tmp_path / "data", tmp_path / "cfg")
    bots = (
        BotDefinition(id="atlas", name="Atlas", role="Coordinator", persona="Be helpful."),
        BotDefinition(id="scout", name="Scout", role="Researcher"),
    )
    config = PalConfig(paths=paths, displays=DisplaySettings(backend="simulated"), bots=bots)
    displays = DisplayManager(config.displays, InMemoryDisplayBackend(), tmp_path / "d.json")
    displays.register(config.bot_ids)
    memory = MemoryService(paths.memory)
    registry = ToolRegistry([MemoryTools(memory), DisplayTools(displays), *providers])
    return config, displays, SessionOptionsBuilder(config, registry, memory, displays)


def test_options_for_a_bot(tmp_path: Path) -> None:
    config, _, builder = build(tmp_path)
    secrets = config.paths.secrets
    secrets.mkdir(parents=True)
    (secrets / "oauth-token").write_text("tok-123\n")

    options = builder.build(
        config.bot("atlas"), ModelSettings("claude-sonnet-5-5", "high"), resume="s1"
    )
    assert (options.model, options.effort, options.resume) == ("claude-sonnet-5-5", "high", "s1")
    # Every bot works in the team's one shared folder.
    assert options.cwd == str(config.paths.workspaces)
    assert Path(options.cwd).is_dir()
    assert options.add_dirs == []
    assert set(options.mcp_servers) == {"pal_memory", "pal_display"}
    assert options.allowed_tools == ["mcp__pal_memory", "mcp__pal_display"]
    assert options.permission_mode == "bypassPermissions"
    assert options.env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-123"
    assert options.env["DISPLAY"] == ":10"
    assert options.thinking == {"type": "adaptive", "display": "summarized"}
    assert "PreToolUse" not in options.hooks  # no provider needs a display

    prompt = options.system_prompt["append"]
    assert options.system_prompt["preset"] == "claude_code"
    assert "You are Atlas, the team's coordinator" in prompt
    assert "Be helpful." in prompt
    assert "- `scout` — Scout (Researcher)" in prompt
    assert "`atlas`" not in prompt.split("# Your team")[1].split("# Messages")[0]
    assert "falls asleep after 8 idle minutes" in prompt
    assert "`pal-open <program> [args]`" in prompt
    assert "`sudo` works without a password" in prompt
    assert "not the user's own computer" in prompt
    assert options.env["PAL_DISPLAY_OWNER"] == "atlas"


async def test_display_tools_wake_the_display(tmp_path: Path) -> None:
    config, displays, builder = build(tmp_path, Screen())
    options = builder.build(config.bot("atlas"), ModelSettings(), resume=None)
    (matcher,) = options.hooks["PreToolUse"]
    assert matcher.matcher == "^(mcp__pal_screen__).*"
    assert displays.get("atlas").state == "stopped"
    result = await matcher.hooks[0]({"tool_name": "mcp__pal_screen__say"}, "t1", {})
    assert result == {}
    assert displays.get("atlas").state == "running"
