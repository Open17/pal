"""Health, status, and global model settings."""

from __future__ import annotations

from aiohttp import web

from pal.config import EFFORT_LEVELS

from ..context import context
from ..errors import json_body, optional_str

routes = web.RouteTableDef()


@routes.get("/v1/health")
async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "version": context(request).version})


@routes.get("/v1/status")
async def status(request: web.Request) -> web.Response:
    ctx = context(request)
    auth = ctx.auth_status()
    return web.json_response(
        {
            "version": ctx.version,
            "auth": {"ok": auth.ok, "method": auth.method, "detail": auth.detail},
            "bots": [agent.to_dict() for agent in ctx.team.agents],
            "displays": [display.to_dict() for display in ctx.displays.all()],
        }
    )


def _settings_payload(request: web.Request) -> dict:
    defaults = context(request).team.default_settings()
    return {
        "defaults": {"model": defaults.model, "effort": defaults.effort},
        "effort_levels": list(EFFORT_LEVELS),
    }


@routes.get("/v1/settings")
async def get_settings(request: web.Request) -> web.Response:
    return web.json_response(_settings_payload(request))


@routes.patch("/v1/settings")
async def update_settings(request: web.Request) -> web.Response:
    body = await json_body(request)
    context(request).team.update_defaults(
        model=optional_str(body, "model"), effort=optional_str(body, "effort")
    )
    return web.json_response(_settings_payload(request))
