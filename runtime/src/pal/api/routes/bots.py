"""Bots: listing, settings, messages, and control."""

from __future__ import annotations

from aiohttp import web

from ..context import context
from ..errors import ApiError, json_body, optional_str

routes = web.RouteTableDef()


@routes.get("/v1/bots")
async def list_bots(request: web.Request) -> web.Response:
    return web.json_response({"bots": [agent.to_dict() for agent in context(request).team.agents]})


@routes.get("/v1/bots/{bot_id}")
async def get_bot(request: web.Request) -> web.Response:
    agent = context(request).team.agent(request.match_info["bot_id"])
    payload = agent.to_dict()
    payload["persona"] = agent.definition.persona
    return web.json_response(payload)


@routes.patch("/v1/bots/{bot_id}")
async def update_bot(request: web.Request) -> web.Response:
    """Change a bot's model or effort. ``{"reset": true}`` returns it to the defaults."""

    team = context(request).team
    bot_id = request.match_info["bot_id"]
    body = await json_body(request)
    if body.get("reset"):
        team.clear_bot_override(bot_id)
    else:
        team.update_bot(
            bot_id, model=optional_str(body, "model"), effort=optional_str(body, "effort")
        )
    return web.json_response(team.agent(bot_id).to_dict())


@routes.post("/v1/bots/{bot_id}/messages")
async def send_message(request: web.Request) -> web.Response:
    body = await json_body(request)
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(400, "invalid_request", "'content' must be a non-empty string")
    message = await context(request).team.send_from_user(request.match_info["bot_id"], content)
    return web.json_response({"message": message.to_dict()}, status=202)


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
