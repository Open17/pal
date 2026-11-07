from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from pal.api import ApiContext, create_app
from pal.bots import AuthStatus
from pal.config import DisplaySettings
from pal.displays import DisplayManager, InMemoryDisplayBackend
from pal.memory import MemoryService
from tests.bots.conftest import TeamHarness

TOKEN = "test-token"


@pytest.fixture
async def api(tmp_path: Path):
    harness = TeamHarness(tmp_path)
    displays = DisplayManager(
        DisplaySettings(backend="simulated"), InMemoryDisplayBackend(), tmp_path / "d.json"
    )
    displays.register(harness.config.bot_ids)
    ctx = ApiContext(
        config=harness.config,
        team=harness.team,
        memory=MemoryService(tmp_path / "memory"),
        messenger=harness.messenger,
        displays=displays,
        bus=harness.bus,
        api_token=TOKEN,
        auth_status=lambda: AuthStatus("oauth-token", "test"),
        version="test",
    )
    harness.team.start()
    client = TestClient(TestServer(create_app(ctx)))
    await client.start_server()
    client.harness = harness
    client.ctx = ctx
    client.auth = {"Authorization": f"Bearer {TOKEN}"}
    yield client
    await client.close()
    await harness.team.stop()
