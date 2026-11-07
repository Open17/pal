"""Conversation history."""

from __future__ import annotations

from aiohttp import web

from ..context import context
from ..errors import ApiError

routes = web.RouteTableDef()

MAX_PAGE = 500


@routes.get("/v1/conversations")
async def list_conversations(request: web.Request) -> web.Response:
    summaries = await context(request).messenger.log.conversations()
    return web.json_response(
        {
            "conversations": [
                {
                    "id": summary.id,
                    "participants": list(summary.participants),
                    "message_count": summary.message_count,
                    "last_message": summary.last_message.to_dict()
                    if summary.last_message
                    else None,
                }
                for summary in summaries
            ]
        }
    )


@routes.get("/v1/conversations/{conversation_id}/messages")
async def list_messages(request: web.Request) -> web.Response:
    try:
        limit = min(int(request.query.get("limit", 100)), MAX_PAGE)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "'limit' must be an integer") from exc
    messages = await context(request).messenger.log.read(
        request.match_info["conversation_id"],
        limit=limit,
        before=request.query.get("before"),
    )
    return web.json_response({"messages": [message.to_dict() for message in messages]})
