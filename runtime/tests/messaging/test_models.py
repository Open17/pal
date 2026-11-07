from __future__ import annotations

import pytest

from pal.messaging import Message, conversation_id, new_id, participants


def test_conversation_ids_are_direction_independent() -> None:
    assert conversation_id("user", "atlas") == "user--atlas"
    assert conversation_id("atlas", "user") == "user--atlas"
    assert conversation_id("scout", "atlas") == "atlas--scout"
    assert conversation_id("atlas", "scout") == "atlas--scout"


def test_participants_round_trip() -> None:
    assert participants("user--atlas") == ("user", "atlas")
    with pytest.raises(ValueError):
        participants("atlas")


def test_ids_sort_by_creation_time() -> None:
    ids = [new_id("msg") for _ in range(500)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert all(identifier.startswith("msg_") for identifier in ids)


def test_message_serialisation_round_trip() -> None:
    message = Message(
        sender="atlas",
        recipient="scout",
        content="find the docs",
        kind="request",
        metadata={"chain": ["atlas"]},
    )
    data = message.to_dict()
    assert data["conversation_id"] == "atlas--scout"
    assert Message.from_dict(data) == message
