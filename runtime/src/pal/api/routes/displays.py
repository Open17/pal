"""Displays: state and manual control."""

from __future__ import annotations

from aiohttp import web

from ..context import context

routes = web.RouteTableDef()


@routes.get("/v1/displays")
async def list_displays(request: web.Request) -> web.Response:
    displays = context(request).displays.all()
    return web.json_response({"displays": [display.to_dict() for display in displays]})


@routes.get("/v1/displays/{owner}")
async def get_display(request: web.Request) -> web.Response:
    return web.json_response(context(request).displays.get(request.match_info["owner"]).to_dict())


@routes.post("/v1/displays/{owner}/wake")
async def wake(request: web.Request) -> web.Response:
    display = await context(request).displays.ensure_awake(request.match_info["owner"])
    return web.json_response(display.to_dict())


@routes.post("/v1/displays/{owner}/sleep")
async def sleep(request: web.Request) -> web.Response:
    manager = context(request).displays
    owner = request.match_info["owner"]
    await manager.sleep(owner, force=True)
    return web.json_response(manager.get(owner).to_dict())


@routes.post("/v1/displays/{owner}/stop")
async def stop(request: web.Request) -> web.Response:
    manager = context(request).displays
    owner = request.match_info["owner"]
    await manager.stop(owner)
    return web.json_response(manager.get(owner).to_dict())
