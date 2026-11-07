"""Live event stream over a WebSocket."""

from __future__ import annotations

import asyncio
import contextlib

from aiohttp import WSMsgType, web

from ..context import context

routes = web.RouteTableDef()


@routes.get("/v1/events")
async def events(request: web.Request) -> web.WebSocketResponse:
    """Stream every runtime event as JSON. Clients only need to read."""

    socket = web.WebSocketResponse(heartbeat=30)
    await socket.prepare(request)
    with context(request).bus.subscribe() as subscription:
        await socket.send_json({"type": "hello", "data": {"version": context(request).version}})
        reader = asyncio.create_task(_drain_client(socket))
        try:
            while not socket.closed:
                event_task = asyncio.create_task(subscription.get())
                done, _ = await asyncio.wait(
                    {event_task, reader}, return_when=asyncio.FIRST_COMPLETED
                )
                if reader in done:
                    event_task.cancel()
                    break
                await socket.send_json(event_task.result().to_dict())
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
    return socket


async def _drain_client(socket: web.WebSocketResponse) -> None:
    """Consume client frames until the connection closes."""

    async for message in socket:
        if message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
            break
