"""Shared memory and bot knowledge.

``{scope}`` is ``shared`` for team memory, or a bot id for that bot's private
knowledge.
"""

from __future__ import annotations

import asyncio

from aiohttp import web

from pal.config import USER_ID
from pal.memory import Scope

from ..context import context
from ..errors import ApiError, json_body

routes = web.RouteTableDef()


def _scope(request: web.Request) -> tuple[Scope, str | None]:
    scope = request.match_info["scope"]
    if scope == "shared":
        return "shared", None
    context(request).team.agent(scope)  # 404 for unknown bots
    return "private", scope


@routes.get("/v1/memory/{scope}")
async def list_memory(request: web.Request) -> web.Response:
    scope, owner = _scope(request)
    memory = context(request).memory
    query = request.query.get("q")
    if query:
        store = memory.store(scope, owner)
        hits = await asyncio.to_thread(store.search, query, limit=50)
        entries = [hit.entry for hit in hits]
    else:
        entries = await memory.list(scope, owner)
    return web.json_response({"entries": [entry.to_dict() for entry in entries]})


@routes.get("/v1/memory/{scope}/{entry_id}")
async def get_memory(request: web.Request) -> web.Response:
    scope, owner = _scope(request)
    entry = await context(request).memory.read(scope, owner, request.match_info["entry_id"])
    if entry is None:
        raise ApiError(404, "not_found", "no such memory")
    return web.json_response(entry.to_dict())


@routes.post("/v1/memory/{scope}")
async def create_memory(request: web.Request) -> web.Response:
    return await _write(request, entry_id=None, status=201)


@routes.put("/v1/memory/{scope}/{entry_id}")
async def update_memory(request: web.Request) -> web.Response:
    return await _write(request, entry_id=request.match_info["entry_id"], status=200)


@routes.delete("/v1/memory/{scope}/{entry_id}")
async def delete_memory(request: web.Request) -> web.Response:
    scope, owner = _scope(request)
    if not await context(request).memory.forget(scope, owner, request.match_info["entry_id"]):
        raise ApiError(404, "not_found", "no such memory")
    return web.json_response({"deleted": True})


async def _write(request: web.Request, *, entry_id: str | None, status: int) -> web.Response:
    scope, owner = _scope(request)
    body = await json_body(request)
    title, content = body.get("title", ""), body.get("content")
    if not isinstance(content, str):
        raise ApiError(400, "invalid_request", "'content' must be a string")
    if entry_id is None and not (isinstance(title, str) and title.strip()):
        raise ApiError(400, "invalid_request", "'title' must be a non-empty string")
    tags = body.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ApiError(400, "invalid_request", "'tags' must be a list of strings")
    entry = await context(request).memory.remember(
        author=USER_ID,
        owner=owner,
        scope=scope,
        title=str(title),
        body=content,
        description=str(body.get("description", "")),
        kind=str(body.get("kind") or "note"),
        tags=tags,
        entry_id=entry_id,
    )
    return web.json_response(entry.to_dict(), status=status)
