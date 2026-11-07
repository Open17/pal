from __future__ import annotations

import asyncio
import os
from pathlib import Path

import aiohttp

from pal.cli import main
from pal.config import ApiSettings, BotDefinition, DisplaySettings, PalConfig, PathSettings
from pal.displays import InMemoryDisplayBackend
from pal.runtime import PalRuntime
from tests.bots.conftest import echo
from tests.bots.fakes import FakeClient
from tests.conftest import REPO_CONFIG_DIR
from tests.displays.test_proxy import free_port


def runtime_config(tmp_path: Path) -> PalConfig:
    return PalConfig(
        paths=PathSettings(tmp_path / "ws", tmp_path / "data", tmp_path / "cfg"),
        api=ApiSettings(host="127.0.0.1", port=free_port()),
        displays=DisplaySettings(
            backend="simulated",
            vnc_bind_host="127.0.0.1",
            vnc_public_base_port=free_port() - 20,
        ),
        bots=(BotDefinition(id="atlas", name="Atlas"), BotDefinition(id="scout", name="Scout")),
    )


async def test_runtime_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-be-removed")
    config = runtime_config(tmp_path)
    runtime = PalRuntime(
        config,
        client_factory=lambda options: FakeClient(options, echo),
        display_backend=InMemoryDisplayBackend(),
    )
    await runtime.start()
    try:
        assert (tmp_path / "ws" / "shared").is_dir()
        assert (tmp_path / "ws" / "atlas").is_dir()
        token = (tmp_path / "cfg" / "secrets" / "api-token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}"}
        base = f"http://127.0.0.1:{config.api.port}"
        async with aiohttp.ClientSession(base, headers=headers) as session:
            async with session.post("/v1/bots/atlas/messages", json={"content": "hi"}) as response:
                assert response.status == 202
            for _ in range(100):
                async with session.get("/v1/conversations/user--atlas/messages") as response:
                    messages = (await response.json())["messages"]
                if len(messages) == 2:
                    break
                await asyncio.sleep(0.02)
        assert messages[1]["content"] == "echo: hi"

        assert "ANTHROPIC_API_KEY" not in os.environ
        options = FakeClient.instances[-1].options
        assert "mcp__pal_team" in options.allowed_tools
        assert options.env["DISPLAY"] == ":10"
    finally:
        await runtime.stop()


def test_config_check_command(capsys) -> None:
    assert main(["--config", str(REPO_CONFIG_DIR), "config", "check"]) == 0
    output = capsys.readouterr().out
    assert "claude-sonnet-5-5 (high effort)" in output
    assert "atlas" in output and "forge" in output and "scout" in output


def test_invalid_config_exits_with_error(tmp_path: Path, capsys) -> None:
    (tmp_path / "pal.toml").write_text("[model]\neffort = 'huge'\n")
    assert main(["--config", str(tmp_path), "config", "check"]) == 2
    assert "configuration error" in capsys.readouterr().err
