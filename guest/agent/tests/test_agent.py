"""Tests for the guest agent. Run with: pytest guest/agent/tests"""

from __future__ import annotations

import asyncio
import socket
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pal_guest_agent as agent


def dns_query(name: str, qtype: int = agent.TYPE_A, query_id: int = 0x1234) -> bytes:
    header = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    labels = b"".join(bytes([len(part)]) + part.encode() for part in name.split("."))
    return header + labels + b"\x00" + struct.pack("!HH", qtype, agent.CLASS_IN)


def parse_answer(packet: bytes) -> tuple[int, int, list[str]]:
    query_id, flags, _, ancount, _, _ = struct.unpack_from("!HHHHHH", packet)
    question = agent.parse_query(
        struct.pack("!HH", query_id, flags & ~0x8000) + packet[4:]
    )
    offset = 12 + len(question.raw) if question else 12
    addresses = []
    for _ in range(ancount):
        _, _, _, _, length = struct.unpack_from("!HHHIH", packet, offset)
        offset += 12
        addresses.append(socket.inet_ntoa(packet[offset : offset + length]))
        offset += length
    return query_id, flags & 0x000F, addresses


class FakeHost:
    """Plays palvmd's side of the egress channel."""

    def __init__(self, replies: dict[str, dict]) -> None:
        self.replies = replies
        self.requests: list[dict] = []

    async def connect(self, request: dict):
        self.requests.append(request)
        reader = asyncio.StreamReader()
        reader.feed_eof()
        writer = _NullWriter()
        return reader, writer, self.replies[request["op"]]


class _NullWriter:
    def close(self) -> None:
        pass


# -- DNS ---------------------------------------------------------------------------


def test_query_parsing() -> None:
    question = agent.parse_query(dns_query("Example.COM"))
    assert (question.id, question.name, question.qtype) == (
        0x1234,
        "example.com",
        agent.TYPE_A,
    )
    assert agent.parse_query(b"short") is None
    assert agent.parse_query(dns_query("a.b")[:-3]) is None


async def test_a_queries_use_host_addresses_ipv4_only() -> None:
    host = FakeHost(
        {"resolve": {"ok": True, "addresses": ["93.184.216.34", "2606:2800::1"]}}
    )
    dns = agent.DnsForwarder(connect=host.connect)
    query_id, rcode, addresses = parse_answer(
        await dns.answer(dns_query("example.com"))
    )
    assert (query_id, rcode, addresses) == (
        0x1234,
        agent.RCODE_NOERROR,
        ["93.184.216.34"],
    )
    await dns.answer(dns_query("example.com"))
    assert len(host.requests) == 1  # cached


async def test_names_without_public_addresses_do_not_exist() -> None:
    dns = agent.DnsForwarder(
        connect=FakeHost({"resolve": {"ok": False, "error": "x"}}).connect
    )
    _, rcode, addresses = parse_answer(await dns.answer(dns_query("router.lan")))
    assert (rcode, addresses) == (agent.RCODE_NXDOMAIN, [])


async def test_aaaa_and_other_types_get_empty_answers() -> None:
    host = FakeHost({})
    dns = agent.DnsForwarder(connect=host.connect)
    _, rcode, addresses = parse_answer(
        await dns.answer(dns_query("example.com", agent.TYPE_AAAA))
    )
    assert (rcode, addresses, host.requests) == (agent.RCODE_NOERROR, [], [])


async def test_malformed_queries_get_formerr() -> None:
    dns = agent.DnsForwarder(connect=FakeHost({}).connect)
    response = await dns.answer(b"\x00\x01\x01\x00" + b"\xff" * 10)
    assert struct.unpack_from("!H", response, 2)[0] & 0x000F == agent.RCODE_FORMERR


# -- egress ------------------------------------------------------------------------


def test_sockaddr_parsing() -> None:
    raw = struct.pack("!HH4s8x", socket.AF_INET, 443, socket.inet_aton("1.2.3.4"))
    assert agent.parse_sockaddr_in(raw) == ("1.2.3.4", 443)


async def echo_server():
    async def echo(reader, writer):
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_egress_proxy_relays_allowed_connections() -> None:
    server, port = await echo_server()
    requests = []

    async def connect(request):
        requests.append(request)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        return reader, writer, {"ok": True}

    proxy = agent.EgressProxy(
        connect=connect, destination=lambda sock: ("1.1.1.1", 443)
    )
    front = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", front.sockets[0].getsockname()[1]
    )
    writer.write(b"hello")
    writer.write_eof()
    assert await reader.read() == b"hello"
    assert requests == [{"op": "connect", "host": "1.1.1.1", "port": 443}]
    for s in (front, server):
        s.close()


async def test_egress_proxy_closes_refused_connections() -> None:
    proxy = agent.EgressProxy(
        connect=FakeHost({"connect": {"ok": False, "error": "blocked"}}).connect,
        destination=lambda sock: ("192.168.1.1", 80),
    )
    front = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    reader, _ = await asyncio.open_connection(
        "127.0.0.1", front.sockets[0].getsockname()[1]
    )
    assert await asyncio.wait_for(reader.read(), 2) == b""
    front.close()


# -- inbound -----------------------------------------------------------------------


async def test_inbound_bridges_only_allowed_ports(monkeypatch) -> None:
    server, port = await echo_server()
    front = await asyncio.start_server(agent.handle_inbound, "127.0.0.1", 0)
    front_port = front.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", front_port)
    writer.write(f'{{"port": {port}}}\n'.encode())
    assert b'"ok": false' in await reader.readline()  # not an allowed port

    monkeypatch.setattr(agent, "INBOUND_PORTS", frozenset({port}))
    reader, writer = await asyncio.open_connection("127.0.0.1", front_port)
    writer.write(f'{{"port": {port}}}\nping'.encode())
    writer.write_eof()
    assert await reader.readline() == b'{"ok": true}\n'
    assert await reader.read() == b"ping"
    for s in (front, server):
        s.close()


# -- clock -------------------------------------------------------------------------


async def test_clock_follows_host(monkeypatch) -> None:
    set_to = []
    monkeypatch.setattr(
        agent.time, "clock_settime", lambda clock, value: set_to.append(value)
    )
    host = FakeHost({"time": {"ok": True, "epoch": 2_000_000_000.0}})
    task = asyncio.create_task(agent.keep_time(host.connect, interval=3600))
    await asyncio.sleep(0.05)
    task.cancel()
    assert set_to == [2_000_000_000.0]


def test_inbound_ports_are_limited() -> None:
    assert {22, 8765, 5901, 5910} <= agent.INBOUND_PORTS
    assert 80 not in agent.INBOUND_PORTS and 6000 not in agent.INBOUND_PORTS


@pytest.mark.skipif(not hasattr(socket, "AF_VSOCK"), reason="vsock is Linux-only")
def test_vsock_constants() -> None:
    assert agent.HOST_CID == socket.VMADDR_CID_HOST
