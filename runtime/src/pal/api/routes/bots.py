"""Bots: listing, settings, messages, and control."""

from __future__ import annotations

from aiohttp import web

from pal.config import validate_color

from ..context import context
from ..errors import ApiError, json_body, optional_str, optional_text

routes = web.RouteTableDef()


@routes.get("/v1/bots")
async def list_bots(request: web.Request) -> web.Response:
    return web.json_response({"bots": [agent.to_dict() for agent in context(request).team.agents]})


@routes.post("/v1/bots")
async def create_bot(request: web.Request) -> web.Response:
    """Add a bot: ``{"name": ..., "role": ..., "persona": ..., "color": ...}``."""

    manager = _manager(request)
    body = await json_body(request)
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ApiError(400, "invalid_request", "'name' must be a non-empty string")
    agent = await manager.add_bot(
        name,
        role=optional_text(body, "role"),
        persona=optional_text(body, "persona"),
        color=optional_str(body, "color"),
    )
    return web.json_response(agent.to_dict(), status=201)


@routes.delete("/v1/bots/{bot_id}")
async def delete_bot(request: web.Request) -> web.Response:
    manager = _manager(request)
    bot_id = request.match_info["bot_id"]
    context(request).team.agent(bot_id)  # unknown bots are a 404
    await manager.remove_bot(bot_id)
    return web.Response(status=204)


def _manager(request: web.Request):
    manager = context(request).bots
    if manager is None:
        raise ApiError(501, "not_supported", "bots cannot be added or removed here")
    return manager


@routes.get("/v1/bots/{bot_id}")
async def get_bot(request: web.Request) -> web.Response:
    return web.json_response(context(request).team.agent(request.match_info["bot_id"]).to_dict())


@routes.patch("/v1/bots/{bot_id}")
async def update_bot(request: web.Request) -> web.Response:
    """Change a bot's model, effort, name, role, instructions (``persona``), or
    color. ``{"reset": true}`` returns its model and effort to the defaults; the
    rest stays."""

    team = context(request).team
    bot_id = request.match_info["bot_id"]
    body = await json_body(request)
    team.agent(bot_id)  # unknown bots are a 404, before anything changes
    identity = {
        "name": optional_str(body, "name"),
        "role": body.get("role"),
        "persona": body.get("persona"),
        "color": optional_str(body, "color"),
    }
    for key in ("role", "persona"):
        if identity[key] is not None and not isinstance(identity[key], str):
            raise ApiError(400, "invalid_request", f"{key!r} must be a string")
    identity = {key: value for key, value in identity.items() if value is not None}
    if identity:
        # Checked up front so a bad change doesn't leave the rest half-applied.
        manager = _manager(request)
        if "color" in identity:
            validate_color(identity["color"], where=bot_id)
    if body.get("reset"):
        team.clear_bot_override(bot_id)
    elif "model" in body or "effort" in body:
        team.update_bot(
            bot_id, model=optional_str(body, "model"), effort=optional_str(body, "effort")
        )
    if identity:
        manager.edit_bot(bot_id, **identity)
    return web.json_response(team.agent(bot_id).to_dict())


@routes.post("/v1/bots/{bot_id}/messages")
async def send_message(request: web.Request) -> web.Response:
    body = await json_body(request)
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(400, "invalid_request", "'content' must be a non-empty string")
    reply_to = body.get("reply_to")
    if reply_to is not None and (not isinstance(reply_to, str) or not reply_to):
        raise ApiError(400, "invalid_request", "'reply_to' must be a message id")
    message = await context(request).team.send_from_user(
        request.match_info["bot_id"], content, reply_to=reply_to
    )
    return web.json_response({"message": message.to_dict()}, status=202)


@routes.post("/v1/bots/{bot_id}/reactions")
async def react(request: web.Request) -> web.Response:
    """React to a message in your chat with a bot: ``{"message_id": ..., "emoji": "👍"}``.
    An empty emoji takes your reaction back."""

    body = await json_body(request)
    message_id, emoji = body.get("message_id"), body.get("emoji", "")
    if not isinstance(message_id, str) or not message_id:
        raise ApiError(400, "invalid_request", "'message_id' must be a non-empty string")
    if not isinstance(emoji, str):
        raise ApiError(400, "invalid_request", "'emoji' must be a string")
    reaction = await context(request).team.react_from_user(
        request.match_info["bot_id"], message_id, emoji
    )
    return web.json_response({"message": reaction.to_dict()}, status=201)


@routes.post("/v1/bots/{bot_id}/interrupt")
async def interrupt(request: web.Request) -> web.Response:
    agent = context(request).team.agent(request.match_info["bot_id"])
    return web.json_response({"interrupted": await agent.interrupt()})


@routes.post("/v1/bots/{bot_id}/session/reset")
async def reset_session(request: web.Request) -> web.Response:
    agent = context(request).team.agent(request.match_info["bot_id"])
    if agent.status == "busy":
        raise ApiError(409, "busy", f"{agent.definition.name} is busy; interrupt it first")
    await agent.reset_session()
    return web.json_response(agent.to_dict())
