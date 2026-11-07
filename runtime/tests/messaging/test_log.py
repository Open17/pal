from __future__ import annotations

from pathlib import Path

import pytest

from pal.messaging import ConversationLog, EventBus, Message, Messenger


async def test_append_and_read(tmp_path: Path) -> None:
    log = ConversationLog(tmp_path)
    first = Message(sender="user", recipient="atlas", content="hi")
    second = Message(sender="atlas", recipient="user", content="hello")
    await log.append(first)
    await log.append(second)
    assert await log.read("user--atlas") == [first, second]
    assert await log.read("user--atlas", limit=1) == [second]
    assert await log.read("user--atlas", before=second.id) == [first]
    assert await log.read("user--forge") == []


async def test_conversation_summaries(tmp_path: Path) -> None:
    log = ConversationLog(tmp_path)
    await log.append(Message(sender="user", recipient="atlas", content="a"))
    last = Message(sender="scout", recipient="atlas", content="b", kind="notice")
    await log.append(last)
    summaries = await log.conversations()
    assert [s.id for s in summaries] == ["atlas--scout", "user--atlas"]
    assert summaries[0].participants == ("atlas", "scout")
    assert summaries[0].last_message == last


async def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    log = ConversationLog(tmp_path)
    message = Message(sender="user", recipient="atlas", content="a")
    await log.append(message)
    with (tmp_path / "user--atlas.jsonl").open("a") as handle:
        handle.write("{not json\n\n")
    assert await log.read("user--atlas") == [message]


@pytest.mark.parametrize("bad", ["../user--atlas", "nodash", ".hidden--x"])
def test_invalid_conversation_ids(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        ConversationLog(tmp_path).path_for(bad)


async def test_messenger_records_and_publishes(tmp_path: Path) -> None:
    bus = EventBus()
    messenger = Messenger(ConversationLog(tmp_path), bus)
    with bus.subscribe() as events:
        message = await messenger.record(Message(sender="user", recipient="atlas", content="x"))
        event = await events.get()
    assert event.type == "message.created"
    assert event.data["message"]["id"] == message.id
    assert await messenger.log.read("user--atlas") == [message]
