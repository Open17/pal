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
        # One main folder for the whole team, with no per-bot folders.
        assert (tmp_path / "ws").is_dir()
        assert not (tmp_path / "ws" / "atlas").exists()
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
    assert "pal" in output and "atlas" not in output  # one general-purpose bot to start


def test_invalid_config_exits_with_error(tmp_path: Path, capsys) -> None:
    (tmp_path / "pal.toml").write_text("[model]\neffort = 'huge'\n")
    assert main(["--config", str(tmp_path), "config", "check"]) == 2
    assert "configuration error" in capsys.readouterr().err


async def test_bots_are_added_and_removed_while_running(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    runtime = PalRuntime(
        config,
        client_factory=lambda options: FakeClient(options, echo),
        display_backend=InMemoryDisplayBackend(),
    )
    await runtime.start()
    try:
        token = (tmp_path / "cfg" / "secrets" / "api-token").read_text().strip()
        base = f"http://127.0.0.1:{config.api.port}"
        with runtime.bus.subscribe() as events:
            async with (
                aiohttp.ClientSession(base, headers={"Authorization": f"Bearer {token}"}) as s,
                s.post("/v1/bots", json={"name": "Probe"}) as response,
            ):
                probe = (await response.json())["id"]
            assert (await events.get()).type == "bot.added"
        await runtime.remove_bot(probe)
        async with aiohttp.ClientSession(base, headers={"Authorization": f"Bearer {token}"}) as s:
            body = {"name": "Research Pal", "role": "Researcher", "persona": "Dig deep."}
            async with s.post("/v1/bots", json=body) as response:
                assert response.status == 201
                created = await response.json()
            assert created["id"] == "research-pal"
            assert created["persona"] == "Dig deep."
            saved = (tmp_path / "cfg" / "bots" / "research-pal.toml").read_text()
            assert 'name = "Research Pal"' in saved
            assert runtime.displays.get("research-pal").name == ":12"  # the probe's, freed

            # The new bot answers, and its teammates know about it.
            async with s.post("/v1/bots/research-pal/messages", json={"content": "hi"}) as r:
                assert r.status == 202
            for _ in range(100):
                async with s.get("/v1/conversations/user--research-pal/messages") as r:
                    if len((await r.json())["messages"]) == 2:
                        break
                await asyncio.sleep(0.02)
            teammates = runtime._options.team()
            assert [bot.id for bot in teammates] == ["atlas", "scout", "research-pal"]

            # A second bot with the same name gets its own id.
            async with s.post("/v1/bots", json={"name": "Research Pal"}) as response:
                assert (await response.json())["id"] == "research-pal-2"

            async with s.delete("/v1/bots/research-pal") as response:
                assert response.status == 204
            assert not (tmp_path / "cfg" / "bots" / "research-pal.toml").exists()
            async with s.get("/v1/bots") as response:
                ids = [bot["id"] for bot in (await response.json())["bots"]]
            assert ids == ["atlas", "scout", "research-pal-2"]

            for bot_id in ("atlas", "research-pal-2"):
                async with s.delete(f"/v1/bots/{bot_id}") as response:
                    assert response.status == 204
            async with s.delete("/v1/bots/scout") as response:
                assert response.status == 400  # the last bot stays
            async with s.delete("/v1/bots/ghost") as response:
                assert response.status == 404
            async with s.post("/v1/bots", json={"name": "  "}) as response:
                assert response.status == 400
    finally:
        await runtime.stop()


async def test_bot_color_changes_while_running(tmp_path: Path) -> None:
    config = runtime_config(tmp_path)
    runtime = PalRuntime(
        config,
        client_factory=lambda options: FakeClient(options, echo),
        display_backend=InMemoryDisplayBackend(),
    )
    await runtime.start()
    try:
        token = (tmp_path / "cfg" / "secrets" / "api-token").read_text().strip()
        base = f"http://127.0.0.1:{config.api.port}"
        async with aiohttp.ClientSession(base, headers={"Authorization": f"Bearer {token}"}) as s:
            body = {"name": "Painter", "color": "#3dbe7a"}
            async with s.post("/v1/bots", json=body) as response:
                assert (await response.json())["color"] == "#3DBE7A"

            with runtime.bus.subscribe() as events:
                async with s.patch("/v1/bots/painter", json={"color": "#ec5b9a"}) as response:
                    assert response.status == 200
                    assert (await response.json())["color"] == "#EC5B9A"
                event = await events.get()
            assert (event.type, event.data["color"]) == ("bot.updated", "#EC5B9A")
            saved = (tmp_path / "cfg" / "bots" / "painter.toml").read_text()
            assert 'color = "#EC5B9A"' in saved
            assert 'name = "Painter"' in saved
            assert runtime.config.bot("painter").color == "#EC5B9A"

            # Color alone leaves the model alone, and a reset leaves the color alone.
            async with s.patch("/v1/bots/painter", json={"effort": "low"}) as response:
                assert (await response.json())["color"] == "#EC5B9A"
            async with s.patch("/v1/bots/painter", json={"reset": True}) as response:
                assert (await response.json())["color"] == "#EC5B9A"

            # A bad color changes nothing, including settings sent with it.
            bad = {"color": "pink", "effort": "max"}
            async with s.patch("/v1/bots/painter", json=bad) as response:
                assert response.status == 400
            async with s.get("/v1/bots/painter") as response:
                body = await response.json()
            assert (body["color"], body["effort"]) == ("#EC5B9A", "high")
            async with s.post("/v1/bots", json={"name": "Smudge", "color": "red"}) as response:
                assert response.status == 400
            async with s.patch("/v1/bots/ghost", json={"color": "#000000"}) as response:
                assert response.status == 404
    finally:
        await runtime.stop()
