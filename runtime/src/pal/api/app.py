"""The aiohttp application and server lifecycle."""

from __future__ import annotations

from aiohttp import web

from pal.log import get_logger

from .auth import auth_middleware
from .context import CONTEXT, ApiContext
from .errors import error_middleware
from .routes import ROUTE_TABLES

log = get_logger(__name__)

MAX_BODY_BYTES = 4 * 1024 * 1024


def create_app(ctx: ApiContext) -> web.Application:
    app = web.Application(
        middlewares=[error_middleware, auth_middleware], client_max_size=MAX_BODY_BYTES
    )
    app[CONTEXT] = ctx
    for table in ROUTE_TABLES:
        app.add_routes(table)
    return app


class ApiServer:
    def __init__(self, app: web.Application, host: str, port: int) -> None:
        self.app = app
        self.host = host
        self.port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app, access_log=None, shutdown_timeout=5)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()
        log.info("API listening on http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
