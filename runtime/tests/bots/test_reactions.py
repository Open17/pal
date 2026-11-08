from __future__ import annotations

import asyncio

import pytest

from pal.bots import UnknownMessageError
from pal.messaging import EventType
from pal.tools.builtin import TeamMessagingError
from tests.bots.fakes import FakeClient


async def turn_done(harness, bot_id: str) -> dict:
    with harness.bus.subscribe() as events:
        async with asyncio.timeout(2.0):
            while True:
                event = await events.get()
                if event.type == EventType.BOT_TURN_COMPLETED and event.data["bot"] == bot_id:
                    return event.data


async def test_a_reaction_can_stand_in_for_a_reply(harness) -> None:
    async def atlas(client, prompt):
        await harness.team.react("atlas", " 👍 ")
        return ""

    harness.scripts["atlas"] = atlas
    done = asyncio.create_task(turn_done(harness, "atlas"))
    await asyncio.sleep(0)
    message = await harness.team.send_from_user("atlas", "thanks!")
    completed = await done

    assert completed["message_id"] is None
    logged = await harness.messenger.log.read("user--atlas")
    assert [(m.sender, m.kind, m.content) for m in logged] == [
        ("user", "chat", "thanks!"),
        ("atlas", "reaction", "👍"),
    ]
    assert logged[1].reply_to == message.id
    assert logged[1].recipient == "user"


async def test_a_reaction_with_words_still_sends_them(harness) -> None:
    async def atlas(client, prompt):
        await harness.team.react("atlas", "🎉")
        return "Congrats!"

    harness.scripts["atlas"] = atlas
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "I shipped it"))
    assert reply.content == "Congrats!"


async def test_a_waiting_teammate_still_gets_an_answer(harness) -> None:
    async def scout(client, prompt):
        await harness.team.react("scout", "✅")
        return ""

    harness.scripts["scout"] = scout
    answer = await harness.team.send("atlas", "scout", "done?", wait_for_reply=True)
    assert answer == "(reacted ✅)"


async def test_bots_react_only_to_the_message_at_hand(harness) -> None:
    with pytest.raises(TeamMessagingError, match="no message to react to"):
        await harness.team.react("atlas", "👍")

    errors: list[str] = []

    async def atlas(client, prompt):
        try:
            await harness.team.react("atlas", "thumbs up")
        except TeamMessagingError as exc:
            errors.append(str(exc))
        return "ok"

    harness.scripts["atlas"] = atlas
    await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))
    assert errors and "single emoji" in errors[0]


async def test_the_bot_sees_your_reaction_with_its_next_message(harness) -> None:
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))
    reaction = await harness.team.react_from_user("atlas", reply.id, "❤️")
    assert (reaction.sender, reaction.recipient, reaction.kind) == ("user", "atlas", "reaction")

    await harness.reply_to(await harness.team.send_from_user("atlas", "next"))
    prompt = FakeClient.instances[-1].prompts[-1]
    assert prompt.startswith('[The user reacted ❤️ to your message: "echo: hi"]')
    assert prompt.endswith("next")

    # Taking it back is noted too, and only once.
    await harness.team.react_from_user("atlas", reply.id, "")
    await harness.reply_to(await harness.team.send_from_user("atlas", "again"))
    assert FakeClient.instances[-1].prompts[-1].startswith("[The user took back their reaction")
    await harness.reply_to(await harness.team.send_from_user("atlas", "plain"))
    assert FakeClient.instances[-1].prompts[-1] == "plain"


async def test_reacting_to_your_own_message_tells_no_one(harness) -> None:
    message = await harness.team.send_from_user("atlas", "hi")
    await harness.reply_to(message)
    await harness.team.react_from_user("atlas", message.id, "😂")
    await harness.reply_to(await harness.team.send_from_user("atlas", "next"))
    assert FakeClient.instances[-1].prompts[-1] == "next"


async def test_user_reactions_need_a_real_message(harness) -> None:
    with pytest.raises(UnknownMessageError):
        await harness.team.react_from_user("atlas", "msg_nope", "👍")
    message = await harness.team.send_from_user("atlas", "hi")
    with pytest.raises(ValueError):
        await harness.team.react_from_user("atlas", message.id, "way too long for an emoji")
