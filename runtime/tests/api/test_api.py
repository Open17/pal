from __future__ import annotations

import asyncio

from pal.messaging import Message
from tests.api.conftest import TOKEN


async def test_health_is_public_and_everything_else_needs_a_token(api) -> None:
    response = await api.get("/v1/health")
    assert response.status == 200
    assert (await response.json())["ok"] is True

    for headers in ({}, {"Authorization": "Bearer wrong"}):
        response = await api.get("/v1/bots", headers=headers)
        assert response.status == 401
        assert (await response.json())["error"]["code"] == "unauthorized"
    assert (await api.get(f"/v1/bots?token={TOKEN}")).status == 200


async def test_status(api) -> None:
    body = await (await api.get("/v1/status", headers=api.auth)).json()
    assert body["auth"] == {"ok": True, "method": "oauth-token", "detail": "test"}
    assert [bot["id"] for bot in body["bots"]] == ["atlas", "scout", "forge"]
    assert body["displays"][0]["owner"] == "operator"


async def test_list_and_get_bots(api) -> None:
    bots = (await (await api.get("/v1/bots", headers=api.auth)).json())["bots"]
    assert bots[0]["model"] == "claude-sonnet-5-5"
    assert bots[0]["effort"] == "high"
    assert (await api.get("/v1/bots/ghost", headers=api.auth)).status == 404


async def test_change_settings(api) -> None:
    response = await api.patch("/v1/settings", json={"effort": "low"}, headers=api.auth)
    assert (await response.json())["defaults"] == {"model": "claude-sonnet-5-5", "effort": "low"}

    response = await api.patch(
        "/v1/bots/atlas", json={"model": "claude-opus-5-5", "effort": "max"}, headers=api.auth
    )
    body = await response.json()
    assert (body["model"], body["effort"]) == ("claude-opus-5-5", "max")

    response = await api.patch("/v1/bots/atlas", json={"reset": True}, headers=api.auth)
    assert (await response.json())["effort"] == "low"

    response = await api.patch("/v1/bots/atlas", json={"effort": "huge"}, headers=api.auth)
    assert response.status == 400


async def test_send_message_and_read_conversation(api) -> None:
    response = await api.post("/v1/bots/atlas/messages", json={"content": "hi"}, headers=api.auth)
    assert response.status == 202
    message = (await response.json())["message"]
    await api.harness.reply_to(Message.from_dict(message))

    body = await (await api.get("/v1/conversations/user--atlas/messages", headers=api.auth)).json()
    assert [m["content"] for m in body["messages"]] == ["hi", "echo: hi"]

    conversations = await (await api.get("/v1/conversations", headers=api.auth)).json()
    assert conversations["conversations"][0]["id"] == "user--atlas"


async def test_bad_message_bodies(api) -> None:
    bad = await api.post("/v1/bots/atlas/messages", json={"content": " "}, headers=api.auth)
    assert bad.status == 400
    broken = await api.post("/v1/bots/atlas/messages", data="{", headers=api.auth)
    assert (await broken.json())["error"]["code"] == "invalid_json"


async def test_memory_crud(api) -> None:
    created = await api.post(
        "/v1/memory/shared",
        json={"title": "Team rule", "content": "Be kind", "tags": ["rules"]},
        headers=api.auth,
    )
    assert created.status == 201
    entry = await created.json()
    assert entry["author"] == "user"

    listed = await (await api.get("/v1/memory/shared?q=rule", headers=api.auth)).json()
    assert [e["id"] for e in listed["entries"]] == ["team-rule"]

    updated = await api.put(
        "/v1/memory/shared/team-rule", json={"content": "Be very kind"}, headers=api.auth
    )
    assert (await updated.json())["body"] == "Be very kind"

    private = await api.post(
        "/v1/memory/atlas", json={"title": "Note", "content": "x"}, headers=api.auth
    )
    assert private.status == 201
    assert (await api.get("/v1/memory/ghost", headers=api.auth)).status == 404

    deleted = await api.delete("/v1/memory/shared/team-rule", headers=api.auth)
    assert (await deleted.json()) == {"deleted": True}
    assert (await api.get("/v1/memory/shared/team-rule", headers=api.auth)).status == 404


async def test_display_control(api) -> None:
    woke = await (await api.post("/v1/displays/atlas/wake", headers=api.auth)).json()
    assert (woke["state"], woke["display"], woke["vnc_port"]) == ("running", ":10", 5910)
    slept = await (await api.post("/v1/displays/atlas/sleep", headers=api.auth)).json()
    assert slept["state"] == "sleeping"
    stopped = await (await api.post("/v1/displays/atlas/stop", headers=api.auth)).json()
    assert stopped["state"] == "stopped"
    assert (await api.post("/v1/displays/ghost/wake", headers=api.auth)).status == 404


async def test_event_stream(api) -> None:
    async with api.ws_connect("/v1/events", headers=api.auth) as socket:
        assert (await socket.receive_json())["type"] == "hello"
        await api.post("/v1/bots/scout/messages", json={"content": "ping"}, headers=api.auth)
        seen = []
        async with asyncio.timeout(2):
            while "bot.turn.completed" not in seen:
                seen.append((await socket.receive_json())["type"])
    assert seen[0] == "message.created"
    assert "bot.status" in seen


async def test_react_to_a_message(api) -> None:
    response = await api.post("/v1/bots/atlas/messages", json={"content": "hi"}, headers=api.auth)
    reply = await api.harness.reply_to(Message.from_dict((await response.json())["message"]))

    body = {"message_id": reply.id, "emoji": "👍"}
    response = await api.post("/v1/bots/atlas/reactions", json=body, headers=api.auth)
    assert response.status == 201
    reaction = (await response.json())["message"]
    assert (reaction["kind"], reaction["content"], reaction["reply_to"]) == (
        "reaction",
        "👍",
        reply.id,
    )

    missing = {"message_id": "msg_nope", "emoji": "👍"}
    response = await api.post("/v1/bots/atlas/reactions", json=missing, headers=api.auth)
    assert (await response.json())["error"]["code"] == "unknown_message"
    response = await api.post("/v1/bots/atlas/reactions", json={"emoji": "👍"}, headers=api.auth)
    assert response.status == 400
