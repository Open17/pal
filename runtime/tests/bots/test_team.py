from __future__ import annotations

import asyncio

from pal.config import ModelSettings
from pal.messaging import EventType
from pal.tools.builtin import TeamMessagingError
from tests.bots.fakes import FakeClient


async def test_user_message_gets_a_reply(harness) -> None:
    message = await harness.team.send_from_user("atlas", "hello")
    reply = await harness.reply_to(message)
    assert reply.sender == "atlas"
    assert reply.recipient == "user"
    assert reply.kind == "chat"
    assert reply.content == "echo: hello"
    assert harness.state.session_id("atlas") == "session-1"
    assert harness.team.agent("atlas").status == "idle"


async def test_conversation_resumes_with_saved_session(harness) -> None:
    harness.state.set_session_id("atlas", "earlier-session")
    await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))
    assert FakeClient.instances[-1].options.resume == "earlier-session"


async def test_bot_can_ask_another_bot_and_wait(harness) -> None:
    async def atlas(client, prompt):
        answer = await harness.team.send("atlas", "scout", "what is 2+2?", wait_for_reply=True)
        return f"Scout says {answer}"

    async def scout(client, prompt):
        assert "[Message from Atlas (`atlas`). They are waiting" in prompt
        return "4"

    harness.scripts.update(atlas=atlas, scout=scout)
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "ask scout"))
    assert reply.content == "Scout says 4"

    between = await harness.messenger.log.read("atlas--scout")
    assert [(m.sender, m.kind) for m in between] == [("atlas", "request"), ("scout", "reply")]
    assert between[0].metadata["chain"] == ["atlas"]


async def test_notices_do_not_block_and_replies_are_not_delivered(harness) -> None:
    received = asyncio.Event()

    async def scout(client, prompt):
        assert "No reply expected" in prompt
        received.set()
        return "noted"

    harness.scripts["scout"] = scout
    assert await harness.team.send("atlas", "scout", "fyi", wait_for_reply=False) is None
    await asyncio.wait_for(received.wait(), 2)
    notice = (await harness.messenger.log.read("atlas--scout"))[0]
    reply = await harness.reply_to(notice)
    assert reply.metadata["delivered"] is False
    assert harness.team.agent("atlas").queued == 0  # nothing was sent back to atlas


async def test_waiting_in_a_cycle_is_refused(harness) -> None:
    errors: list[str] = []

    async def atlas(client, prompt):
        return await harness.team.send("atlas", "scout", "help", wait_for_reply=True)

    async def scout(client, prompt):
        try:
            await harness.team.send("scout", "forge", "help", wait_for_reply=True)
        except TeamMessagingError as exc:
            errors.append(str(exc))
        return "done"

    async def forge(client, prompt):
        try:
            await harness.team.send("forge", "atlas", "help", wait_for_reply=True)
        except TeamMessagingError as exc:
            errors.append(str(exc))
            return "atlas is busy"
        return "unreachable"

    harness.scripts.update(atlas=atlas, scout=scout, forge=forge)
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "go"))
    assert reply.content == "done"
    assert len(errors) == 1
    assert "waiting on you (forge → atlas → scout → forge)" in errors[0]


async def test_chain_depth_is_limited(make_harness) -> None:
    harness = make_harness(max_chain_depth=1)
    errors: list[str] = []

    async def atlas(client, prompt):
        return await harness.team.send("atlas", "scout", "go", wait_for_reply=True)

    async def scout(client, prompt):
        try:
            return await harness.team.send("scout", "forge", "go", wait_for_reply=True)
        except TeamMessagingError as exc:
            errors.append(str(exc))
            return "stopped"

    harness.scripts.update(atlas=atlas, scout=scout)
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "go"))
    assert reply.content == "stopped"
    assert "Too many bots are already waiting" in errors[0]


async def test_reply_timeout(make_harness) -> None:
    harness = make_harness(reply_timeout_seconds=0)

    async def scout(client, prompt):
        await asyncio.sleep(0.05)
        return "late"

    harness.scripts["scout"] = scout
    try:
        await harness.team.send("atlas", "scout", "quick?", wait_for_reply=True)
    except TeamMessagingError as exc:
        assert "did not answer within 0 seconds" in str(exc)
    else:
        raise AssertionError("expected a timeout")


async def test_invalid_recipients(harness) -> None:
    for recipient, text in [("atlas", "yourself"), ("ghost", "no bot called")]:
        try:
            await harness.team.send("atlas", recipient, "x", wait_for_reply=False)
        except TeamMessagingError as exc:
            assert text in str(exc)
        else:
            raise AssertionError(recipient)


async def test_failed_turns_reply_with_an_error(harness) -> None:
    async def scout(client, prompt):
        raise RuntimeError("tool exploded")

    harness.scripts["scout"] = scout
    reply = await harness.reply_to(await harness.team.send_from_user("scout", "do it"))
    assert reply.metadata["error"] is True
    assert "tool exploded" in reply.content
    assert harness.team.agent("scout").status == "error"
    try:
        await harness.team.send("atlas", "scout", "again", wait_for_reply=True)
    except TeamMessagingError as exc:
        assert "Scout failed to answer: tool exploded" in str(exc)


async def test_settings_layering(harness) -> None:
    team = harness.team
    assert team.model_settings("atlas") == ModelSettings("claude-sonnet-5-5", "high")
    team.update_defaults(effort="medium")
    assert team.model_settings("atlas") == ModelSettings("claude-sonnet-5-5", "medium")
    team.update_bot("atlas", model="claude-opus-5-5")
    assert team.model_settings("atlas") == ModelSettings("claude-opus-5-5", "medium")
    assert team.model_settings("scout") == ModelSettings("claude-sonnet-5-5", "medium")
    team.clear_bot_override("atlas")
    assert team.model_settings("atlas").model == "claude-sonnet-5-5"


async def test_settings_change_reconnects_and_resumes(harness) -> None:
    await harness.reply_to(await harness.team.send_from_user("atlas", "one"))
    with harness.bus.subscribe() as events:
        harness.team.update_bot("atlas", effort="max")
        event = await events.get()
    assert event.type == EventType.BOT_SETTINGS_CHANGED
    assert event.data == {"bot": "atlas", "model": "claude-sonnet-5-5", "effort": "max"}

    await harness.reply_to(await harness.team.send_from_user("atlas", "two"))
    first, second = FakeClient.instances
    assert first.connected is False
    assert (second.options.effort, second.options.resume) == ("max", "session-1")


async def test_unresumable_session_starts_fresh(harness) -> None:
    harness.fail_resume = True
    harness.state.set_session_id("atlas", "lost-session")
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))
    assert reply.content == "echo: hi"
    assert FakeClient.instances[-1].options.resume is None
    assert harness.state.session_id("atlas") != "lost-session"


async def test_roster_shows_waiting(harness) -> None:
    gate = asyncio.Event()

    async def scout(client, prompt):
        await gate.wait()
        return "ok"

    harness.scripts["scout"] = scout
    pending = asyncio.create_task(harness.team.send("atlas", "scout", "x", wait_for_reply=True))
    await asyncio.sleep(0.02)
    statuses = {member.id: member.status for member in harness.team.roster()}
    assert statuses["atlas"] == "waiting on scout"
    assert statuses["scout"] == "busy"
    gate.set()
    assert await pending == "ok"
