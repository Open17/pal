"""TCP proxy in front of each display's VNC server.

Xvnc only listens on localhost. The proxy listens on the public port for each
display, wakes the display when a viewer connects (starting it if needed),
keeps it awake while the viewer is attached, and pipes bytes both ways.
"""

from __future__ import annotations

import asyncio
import contextlib

from pal.log import get_logger

from .backend import DisplayBackendError
from .manager import DisplayManager
from .models import Display

log = get_logger(__name__)

_CHUNK = 64 * 1024


class VncProxy:
    def __init__(
        self,
        manager: DisplayManager,
        *,
        bind_host: str,
        upstream_host: str = "127.0.0.1",
        connect_timeout: float = 20.0,
        activity_interval: float = 30.0,
    ) -> None:
        self.manager = manager
        self.bind_host = bind_host
        self.upstream_host = upstream_host
        self.connect_timeout = connect_timeout
        self.activity_interval = activity_interval
        self._servers: list[asyncio.Server] = []

    async def start(self) -> None:
        for display in self.manager.all():
            server = await asyncio.start_server(
                lambda r, w, owner=display.owner: self._handle(owner, r, w),
                host=self.bind_host,
                port=display.vnc_public_port,
            )
            self._servers.append(server)
            log.info(
                "VNC for %s (%s) on %s:%d",
                display.owner,
                display.name,
                self.bind_host,
                display.vnc_public_port,
            )

    async def close(self) -> None:
        for server in self._servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in self._servers))
        self._servers.clear()

    async def _handle(
        self, owner: str, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        peer = client_writer.get_extra_info("peername")
        self.manager.viewer_connected(owner)
        try:
            display = await self.manager.ensure_awake(owner)
            upstream_reader, upstream_writer = await self._connect_upstream(display)
        except (DisplayBackendError, OSError, TimeoutError) as exc:
            log.warning("viewer %s for %s refused: %s", peer, owner, exc)
            self.manager.viewer_disconnected(owner)
            client_writer.close()
            return

        log.info("viewer %s attached to %s", peer, display.name)
        keepalive = asyncio.create_task(self._keep_awake(owner))
        pipes: list[asyncio.Task[None]] = []
        try:
            pipes = [
                asyncio.create_task(_pipe(client_reader, upstream_writer)),
                asyncio.create_task(_pipe(upstream_reader, client_writer)),
            ]
            # When either side hangs up, tear down the whole connection.
            await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
        finally:
            keepalive.cancel()
            for pipe in pipes:
                pipe.cancel()
            for writer in (client_writer, upstream_writer):
                writer.close()
            self.manager.viewer_disconnected(owner)
            log.info("viewer %s detached from %s", peer, display.name)

    async def _connect_upstream(
        self, display: Display
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Connect to Xvnc, retrying while a freshly started display comes up."""

        async with asyncio.timeout(self.connect_timeout):
            while True:
                try:
                    return await asyncio.open_connection(
                        self.upstream_host, display.vnc_internal_port
                    )
                except OSError:
                    await asyncio.sleep(0.25)

    async def _keep_awake(self, owner: str) -> None:
        while True:
            await asyncio.sleep(self.activity_interval)
            self.manager.touch(owner)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(ConnectionError, asyncio.IncompleteReadError):
        while data := await reader.read(_CHUNK):
            writer.write(data)
            await writer.drain()
    with contextlib.suppress(OSError):
        if writer.can_write_eof():
            writer.write_eof()
