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


async def test_your_reaction_gets_the_bot_s_attention(harness) -> None:
    prompts: list[str] = []

    async def atlas(client, prompt):
        prompts.append(prompt)
        if "reacted 👎" in prompt:
            return "Sorry, let me fix that."
        return "" if "reacted" in prompt else f"echo: {prompt}"

    harness.scripts["atlas"] = atlas
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))

    # A ❤️ reaches the bot in a turn of its own, and needs no answer.
    done = asyncio.create_task(turn_done(harness, "atlas"))
    await asyncio.sleep(0)
    reaction = await harness.team.react_from_user("atlas", reply.id, "❤️")
    assert (reaction.sender, reaction.recipient, reaction.kind) == ("user", "atlas", "reaction")
    assert (await done)["message_id"] is None
    assert prompts[-1].startswith('[The user reacted ❤️ to your message: "echo: hi".')
    assert [m.kind for m in await harness.messenger.log.read("user--atlas")][-1] == "reaction"

    # A 👎 gets a follow-up.
    await harness.team.react_from_user("atlas", reply.id, "👎")
    follow_up = await harness.reply_to((await harness.messenger.log.read("user--atlas"))[-1])
    assert (follow_up.content, follow_up.kind) == ("Sorry, let me fix that.", "chat")


async def test_trying_a_few_reactions_reaches_the_bot_once(harness) -> None:
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))
    turns = len(FakeClient.instances[-1].prompts)
    for emoji in ("👍", "", "😂"):
        await harness.team.react_from_user("atlas", reply.id, emoji)
    await turn_done(harness, "atlas")
    prompts = FakeClient.instances[-1].prompts
    assert len(prompts) == turns + 1
    assert "reacted 😂" in prompts[-1]

    # Added and taken back before it settles: nothing to tell.
    other = await harness.reply_to(await harness.team.send_from_user("atlas", "again"))
    turns = len(FakeClient.instances[-1].prompts)
    await harness.team.react_from_user("atlas", other.id, "👍")
    await harness.team.react_from_user("atlas", other.id, "")
    await asyncio.sleep(harness.team.reaction_delay * 3)
    assert len(FakeClient.instances[-1].prompts) == turns


async def test_taking_back_a_reaction_is_noted_not_a_turn(harness) -> None:
    async def quiet_about_reactions(client, prompt):
        return "" if prompt.startswith("[The user reacted") else f"echo: {prompt}"

    harness.scripts["atlas"] = quiet_about_reactions
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))
    await harness.team.react_from_user("atlas", reply.id, "👍")
    await turn_done(harness, "atlas")
    turns = len(FakeClient.instances[-1].prompts)

    await harness.team.react_from_user("atlas", reply.id, "")
    await asyncio.sleep(harness.team.reaction_delay * 3)
    assert len(FakeClient.instances[-1].prompts) == turns
    await harness.reply_to(await harness.team.send_from_user("atlas", "next"))
    assert FakeClient.instances[-1].prompts[-1] == (
        '[The user took back their 👍 on your message: "echo: hi"]\n\nnext'
    )


async def test_a_bot_cannot_react_to_a_reaction(harness) -> None:
    errors: list[str] = []

    async def atlas(client, prompt):
        if "reacted" in prompt:
            try:
                await harness.team.react("atlas", "👍")
            except TeamMessagingError as exc:
                errors.append(str(exc))
            return ""
        return "ok"

    harness.scripts["atlas"] = atlas
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "hi"))
    await harness.team.react_from_user("atlas", reply.id, "🎉")
    await turn_done(harness, "atlas")
    assert errors and "can't react to a reaction" in errors[0]


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


async def test_a_reply_quotes_the_message_it_answers(harness) -> None:
    reply = await harness.reply_to(await harness.team.send_from_user("atlas", "pick a color"))
    message = await harness.team.send_from_user("atlas", "why that one?", reply_to=reply.id)
    assert message.reply_to == reply.id
    assert message.metadata["quote"] == {"sender": "atlas", "content": "echo: pick a color"}
    await harness.reply_to(message)
    assert FakeClient.instances[-1].prompts[-1] == (
        '[Replying to your message: "echo: pick a color"]\n\nwhy that one?'
    )

    with pytest.raises(UnknownMessageError):
        await harness.team.send_from_user("atlas", "hm", reply_to="msg_nope")
