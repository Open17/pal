from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from pal.bots import BotAgent, BotStateStore, BotTeam
from pal.config import BotDefinition, MessagingSettings, PalConfig, PathSettings
from pal.messaging import ConversationLog, EventBus, Message, Messenger
from tests.bots.fakes import FakeClient


async def echo(client: FakeClient, prompt: str) -> str:
    return f"echo: {prompt}"


class TeamHarness:
    def __init__(self, tmp_path: Path, **messaging: Any) -> None:
        FakeClient.instances.clear()
        self.config = PalConfig(
            paths=PathSettings(tmp_path / "ws", tmp_path / "data", tmp_path / "cfg"),
            messaging=replace(MessagingSettings(), **messaging),
            bots=tuple(
                BotDefinition(id=bot_id, name=bot_id.title(), role="Tester")
                for bot_id in ("atlas", "scout", "forge")
            ),
        )
        self.bus = EventBus()
        self.messenger = Messenger(ConversationLog(tmp_path / "conversations"), self.bus)
        self.state = BotStateStore(tmp_path / "state" / "bots.json")
        self.team = BotTeam(self.config, self.state, self.messenger, self.bus)
        self.team.reaction_delay = 0.05
        self.scripts: dict[str, Any] = {}
        self.fail_resume = False
        self.team.add(self._agent(bot) for bot in self.config.bots)

    def _agent(self, bot: BotDefinition) -> BotAgent:
        def options(definition, settings, resume) -> ClaudeAgentOptions:
            return ClaudeAgentOptions(model=settings.model, effort=settings.effort, resume=resume)

        def client(options: ClaudeAgentOptions) -> FakeClient:
            return FakeClient(options, self.scripts.get(bot.id, echo), fail_resume=self.fail_resume)

        return BotAgent(
            bot,
            options_factory=options,
            settings=lambda: self.team.model_settings(bot.id),
            state=self.state,
            messenger=self.messenger,
            bus=self.bus,
            display_name=self.team.display_name,
            client_factory=client,
        )

    async def reply_to(self, message: Message) -> Message:
        async with asyncio.timeout(2.0):
            while True:
                for logged in await self.messenger.log.read(message.conversation_id):
                    if logged.reply_to == message.id and logged.kind != "reaction":
                        return logged
                await asyncio.sleep(0.01)


@pytest.fixture
async def harness(tmp_path: Path):
    harness = TeamHarness(tmp_path)
    harness.team.start()
    yield harness
    await harness.team.stop()


@pytest.fixture
async def make_harness(tmp_path: Path):
    created: list[TeamHarness] = []

    def make(**messaging: Any) -> TeamHarness:
        harness = TeamHarness(tmp_path, **messaging)
        harness.team.start()
        created.append(harness)
        return harness

    yield make
    for harness in created:
        await harness.team.stop()
