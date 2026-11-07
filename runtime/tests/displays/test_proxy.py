from __future__ import annotations

import asyncio
import socket
from pathlib import Path

from pal.config import DisplaySettings
from pal.displays import DisplayManager, InMemoryDisplayBackend, VncProxy


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_proxy_wakes_display_and_relays_bytes(tmp_path: Path) -> None:
    public, internal = free_port(), free_port()
    settings = DisplaySettings(
        backend="simulated",
        operator_display=0,
        vnc_public_base_port=public,
        vnc_internal_base_port=internal,
    )
    backend = InMemoryDisplayBackend()
    manager = DisplayManager(settings, backend, tmp_path / "displays.json")
    manager.register([])  # operator only, on display :0

    async def fake_vnc(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"RFB 003.008\n")
        await writer.drain()
        writer.write(b"echo:" + await reader.readexactly(4))
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(fake_vnc, "127.0.0.1", internal)
    proxy = VncProxy(manager, bind_host="127.0.0.1")
    await proxy.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", public)
        assert await reader.readexactly(12) == b"RFB 003.008\n"
        assert manager.get("operator").viewers == 1
        assert manager.get("operator").state == "running"
        writer.write(b"ping")
        await writer.drain()
        assert await reader.read() == b"echo:ping"
        writer.close()
        for _ in range(50):
            if manager.get("operator").viewers == 0:
                break
            await asyncio.sleep(0.02)
        assert manager.get("operator").viewers == 0
        assert backend.calls == [("start", "operator")]
    finally:
        await proxy.close()
        upstream.close()
        await upstream.wait_closed()
