from __future__ import annotations

import asyncio

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from pal.bots import GREETING_EFFORT, GREETING_MODEL, ModelGreeter, fallback_greeting
from pal.config import BotDefinition
from tests.bots.fakes import FakeClient


async def chat(harness, bot_id: str, count: int):
    async with asyncio.timeout(2.0):
        while True:
            messages = await harness.messenger.log.read(f"user--{bot_id}")
            if len(messages) >= count:
                return messages
            await asyncio.sleep(0.01)


async def test_a_bot_says_hello_before_anything_else(harness) -> None:
    agent = harness.team.agent("atlas")

    async def greeter(bot: BotDefinition) -> str:
        return f"  Hi, I'm {bot.name}.  "

    agent._greeter = greeter
    agent.greet()
    await chat(harness, "atlas", 1)
    await harness.team.send_from_user("atlas", "hello")
    messages = await chat(harness, "atlas", 3)
    assert [(m.sender, m.content) for m in messages] == [
        ("atlas", "Hi, I'm Atlas."),
        ("user", "hello"),
        ("atlas", messages[2].content),
    ]
    assert messages[0].metadata == {"greeting": True}
    assert FakeClient.instances[-1].prompts[-1] == (
        '[When you joined the team you said hello to the user with: "Hi, I\'m Atlas."]\n\nhello'
    )


async def test_a_failed_greeting_falls_back_to_a_plain_hello(harness) -> None:
    async def broken(bot: BotDefinition) -> str:
        raise RuntimeError("not signed in")

    harness.team.agent("scout")._greeter = broken
    harness.team.agent("scout").greet()
    messages = await chat(harness, "scout", 1)
    assert messages[0].content == "Hi, I'm Scout, your tester! What can I help you with?"
    assert harness.team.agent("scout").status == "idle"


def test_fallback_without_a_role() -> None:
    assert fallback_greeting(BotDefinition(id="x", name="Max")) == (
        "Hi, I'm Max! What can I help you with?"
    )


async def test_model_greeter_uses_a_small_model_without_tools(tmp_path) -> None:
    calls = []

    async def fake_query(*, prompt, options):
        calls.append((prompt, options))
        yield AssistantMessage(content=[TextBlock(text='"Hey there!"')], model=options.model)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result='"Hey there!"',
        )

    greeter = ModelGreeter(tmp_path / "secrets", tmp_path, query_fn=fake_query)
    bot = BotDefinition(id="ada", name="Ada", role="Researcher", persona="Cite sources.")
    assert await greeter(bot) == "Hey there!"
    prompt, options = calls[0]
    assert (options.model, options.effort) == (GREETING_MODEL, GREETING_EFFORT)
    assert (GREETING_MODEL, GREETING_EFFORT) == ("claude-haiku-5-5", "medium")
    assert options.tools == [] and options.max_turns == 1
    assert "You are Ada" in prompt and "Researcher" in prompt and "Cite sources." in prompt
