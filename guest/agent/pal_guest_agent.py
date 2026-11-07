#!/usr/bin/env python3
"""Pal guest agent: the VM's only link to the outside.

The VM has no network interface. Every connection leaves through this agent
over vsock to palvmd on the host, which allows the public internet and
refuses everything else — including the host itself and its local network.
Enforcement happens on the host, so nothing in the guest can bypass it.

The agent:

- routes all outgoing TCP through a transparent proxy (a dummy interface
  carries the default route and iptables redirects connections to the agent),
- answers DNS queries with addresses resolved, and vetted, by the host,
- bridges connections from the host to guest services (SSH, the Pal API,
  the displays' VNC ports),
- keeps the guest clock in step with the host.

Standard library only: it has to run before anything else is installed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ipaddress
import json
import logging
import socket
import struct
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("pal-guest-agent")

HOST_CID = 2  # VMADDR_CID_HOST
INBOUND_PORT = 1025  # host -> guest services
EGRESS_PORT = 1026  # guest -> internet, via the host
PROXY_PORT = 15001
DNS_HOST = "127.0.0.1"
DNS_PORT = 53
DUMMY_INTERFACE = "pal0"
DUMMY_ADDRESS = "10.255.255.1/32"
IPTABLES_CHAIN = "PAL_EGRESS"
SO_ORIGINAL_DST = 80
RESOLV_CONF = Path("/etc/resolv.conf")

#: Guest ports the host may connect to: SSH, the Pal API, and display VNC.
INBOUND_PORTS = frozenset({22, 8765, *range(5900, 6000)})

HostConnector = Callable[
    [dict], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter, dict]]
]


# -- the host channel ------------------------------------------------------------


async def connect_host(
    request: dict,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, dict]:
    """Open an egress channel to the host and send ``request``."""

    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        await asyncio.wait_for(loop.sock_connect(sock, (HOST_CID, EGRESS_PORT)), 10)
    except BaseException:
        sock.close()
        raise
    reader, writer = await asyncio.open_connection(sock=sock)
    return await exchange(reader, writer, request)


async def exchange(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, request: dict
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, dict]:
    writer.write(json.dumps(request).encode() + b"\n")
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), 30)
    reply = json.loads(line) if line.strip() else {"ok": False, "error": "no reply"}
    return reader, writer, reply


async def splice(
    a: tuple[asyncio.StreamReader, asyncio.StreamWriter],
    b: tuple[asyncio.StreamReader, asyncio.StreamWriter],
) -> None:
    """Copy bytes both ways until both directions have finished."""

    async def pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(ConnectionError, OSError):
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
            if writer.can_write_eof():
                writer.write_eof()

    try:
        await asyncio.gather(pump(a[0], b[1]), pump(b[0], a[1]))
    finally:
        for writer in (a[1], b[1]):
            writer.close()


# -- outgoing TCP ------------------------------------------------------------------


def original_destination(sock: socket.socket) -> tuple[str, int]:
    """Where a redirected connection was originally headed."""

    raw = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
    return parse_sockaddr_in(raw)


def parse_sockaddr_in(raw: bytes) -> tuple[str, int]:
    (port,) = struct.unpack_from("!H", raw, 2)
    return socket.inet_ntoa(raw[4:8]), port


@dataclass
class EgressProxy:
    """Transparent proxy for every outgoing TCP connection."""

    connect: HostConnector = connect_host
    destination: Callable[[socket.socket], tuple[str, int]] = original_destination

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            host, port = self.destination(writer.get_extra_info("socket"))
            remote_reader, remote_writer, reply = await self.connect(
                {"op": "connect", "host": host, "port": port}
            )
        except (OSError, TimeoutError, ValueError) as exc:
            log.debug("egress failed: %s", exc)
            writer.close()
            return
        if not reply.get("ok"):
            log.info(
                "connection to %s:%d refused by host: %s",
                host,
                port,
                reply.get("error"),
            )
            remote_writer.close()
            writer.close()
            return
        await splice((reader, writer), (remote_reader, remote_writer))


# -- DNS ---------------------------------------------------------------------------

TYPE_A, TYPE_AAAA, CLASS_IN = 1, 28, 1
RCODE_NOERROR, RCODE_FORMERR, RCODE_SERVFAIL, RCODE_NXDOMAIN, RCODE_NOTIMP = (
    0,
    1,
    2,
    3,
    4,
)
TTL = 60


@dataclass(frozen=True)
class Question:
    id: int
    flags: int
    name: str
    qtype: int
    qclass: int
    raw: bytes  # the question section, echoed in the answer


def parse_query(packet: bytes) -> Question | None:
    if len(packet) < 12:
        return None
    query_id, flags, qdcount = struct.unpack_from("!HHH", packet)
    if flags & 0x8000 or qdcount != 1:  # a response, or not exactly one question
        return None
    labels, offset = [], 12
    while True:
        if offset >= len(packet):
            return None
        length = packet[offset]
        offset += 1
        if length == 0:
            break
        if length & 0xC0 or offset + length > len(packet):
            return None  # compression is not valid in a question
        labels.append(packet[offset : offset + length].decode("ascii", "replace"))
        offset += length
    if offset + 4 > len(packet):
        return None
    qtype, qclass = struct.unpack_from("!HH", packet, offset)
    return Question(
        query_id,
        flags,
        ".".join(labels).lower(),
        qtype,
        qclass,
        packet[12 : offset + 4],
    )


def build_response(
    question: Question, addresses: list[str], rcode: int = RCODE_NOERROR
) -> bytes:
    flags = 0x8000 | (question.flags & 0x0100) | 0x0080 | rcode  # QR, RD copied, RA
    answers = b"".join(
        struct.pack("!HHHIH", 0xC00C, TYPE_A, CLASS_IN, TTL, 4)
        + socket.inet_aton(address)
        for address in addresses
    )
    header = struct.pack("!HHHHHH", question.id, flags, 1, len(addresses), 0, 0)
    return header + question.raw + answers


def error_response(packet: bytes, rcode: int) -> bytes | None:
    if len(packet) < 4:
        return None
    query_id, flags = struct.unpack_from("!HH", packet)
    return struct.pack(
        "!HHHHHH", query_id, 0x8000 | (flags & 0x0100) | 0x0080 | rcode, 0, 0, 0, 0
    )


@dataclass
class DnsForwarder:
    """Answers DNS with addresses the host resolved and allowed."""

    connect: HostConnector = connect_host
    cache: dict[str, tuple[float, list[str]]] = field(default_factory=dict)
    pending: set[asyncio.Future] = field(default_factory=set)

    async def resolve(self, name: str) -> list[str] | None:
        cached = self.cache.get(name)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        _, writer, reply = await self.connect({"op": "resolve", "name": name})
        writer.close()
        addresses = [
            address
            for address in reply.get("addresses") or []
            if isinstance(ipaddress.ip_address(address), ipaddress.IPv4Address)
        ]
        result = addresses if reply.get("ok") and addresses else None
        self.cache[name] = (time.monotonic() + TTL, result or [])
        if len(self.cache) > 4096:
            self.cache.clear()
        return result

    async def answer(self, packet: bytes) -> bytes | None:
        question = parse_query(packet)
        if question is None:
            return error_response(packet, RCODE_FORMERR)
        if question.qclass != CLASS_IN:
            return build_response(question, [], RCODE_NOTIMP)
        if question.qtype != TYPE_A:
            # The guest has no IPv6 and needs no other record types: answer
            # "no records" so clients move on to the A lookup.
            return build_response(question, [])
        try:
            addresses = await self.resolve(question.name)
        except (OSError, TimeoutError, ValueError) as exc:
            log.debug("resolve %s failed: %s", question.name, exc)
            return build_response(question, [], RCODE_SERVFAIL)
        if addresses is None:
            return build_response(question, [], RCODE_NXDOMAIN)
        return build_response(question, addresses)

    # UDP
    def datagram_protocol(self) -> asyncio.DatagramProtocol:
        forwarder = self

        class Protocol(asyncio.DatagramProtocol):
            def connection_made(self, transport: asyncio.DatagramTransport) -> None:
                self.transport = transport

            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                async def reply() -> None:
                    response = await forwarder.answer(data)
                    if response is not None:
                        self.transport.sendto(response, addr)

                task = asyncio.ensure_future(reply())
                forwarder.pending.add(task)
                task.add_done_callback(forwarder.pending.discard)

        return Protocol()

    # TCP: two-byte length prefix per message
    async def handle_stream(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        with contextlib.suppress(
            asyncio.IncompleteReadError, ConnectionError, TimeoutError
        ):
            while True:
                (length,) = struct.unpack(
                    "!H", await asyncio.wait_for(reader.readexactly(2), 30)
                )
                response = await self.answer(await reader.readexactly(length))
                if response is None:
                    break
                writer.write(struct.pack("!H", len(response)) + response)
                await writer.drain()
        writer.close()


# -- incoming connections from the host -------------------------------------------


async def handle_inbound(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        request = json.loads(await asyncio.wait_for(reader.readline(), 10))
        port = int(request["port"])
    except (ValueError, KeyError, TypeError, TimeoutError):
        writer.close()
        return
    if port not in INBOUND_PORTS:
        writer.write(
            json.dumps({"ok": False, "error": f"port {port} is not forwarded"}).encode()
            + b"\n"
        )
        writer.close()
        return
    try:
        local = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 10)
    except (OSError, TimeoutError) as exc:
        writer.write(json.dumps({"ok": False, "error": str(exc)}).encode() + b"\n")
        writer.close()
        return
    writer.write(b'{"ok": true}\n')
    await writer.drain()
    await splice((reader, writer), local)


# -- clock -------------------------------------------------------------------------


async def keep_time(
    connect: HostConnector = connect_host, interval: float = 60
) -> None:
    """Follow the host clock; the guest has no network time source."""

    while True:
        try:
            _, writer, reply = await connect({"op": "time"})
            writer.close()
            epoch = float(reply["epoch"])
            drift = time.time() - epoch
            if abs(drift) > 1:
                time.clock_settime(time.CLOCK_REALTIME, epoch)
                log.info("clock corrected by %.1fs", -drift)
        except (OSError, TimeoutError, ValueError, KeyError) as exc:
            log.debug("time sync failed: %s", exc)
        await asyncio.sleep(interval)


# -- system setup ------------------------------------------------------------------


def run(*command: str, check: bool = True) -> bool:
    result = subprocess.run(command, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)}: {result.stderr.strip()}")
    return result.returncode == 0


def configure_network() -> None:
    """Route everything through the agent. Safe to run repeatedly."""

    run("ip", "link", "add", DUMMY_INTERFACE, "type", "dummy", check=False)
    run("ip", "address", "replace", DUMMY_ADDRESS, "dev", DUMMY_INTERFACE)
    run("ip", "link", "set", DUMMY_INTERFACE, "up")
    run("ip", "route", "replace", "default", "dev", DUMMY_INTERFACE)

    nat = ("iptables", "-w", "-t", "nat")
    run(*nat, "-N", IPTABLES_CHAIN, check=False)
    run(*nat, "-F", IPTABLES_CHAIN)
    run(*nat, "-A", IPTABLES_CHAIN, "-d", "127.0.0.0/8", "-j", "RETURN")
    for protocol in ("udp", "tcp"):
        run(*nat, "-A", IPTABLES_CHAIN, "-p", protocol, "--dport", "53",
            "-j", "REDIRECT", "--to-ports", str(DNS_PORT))  # fmt: skip
    run(
        *nat,
        "-A",
        IPTABLES_CHAIN,
        "-p",
        "tcp",
        "-j",
        "REDIRECT",
        "--to-ports",
        str(PROXY_PORT),
    )
    if not run(*nat, "-C", "OUTPUT", "-j", IPTABLES_CHAIN, check=False):
        run(*nat, "-A", "OUTPUT", "-j", IPTABLES_CHAIN)

    resolv = f"# Managed by the Pal guest agent.\nnameserver {DNS_HOST}\n"
    with contextlib.suppress(OSError):
        if (
            RESOLV_CONF.is_symlink()
            or not RESOLV_CONF.exists()
            or RESOLV_CONF.read_text() != resolv
        ):
            RESOLV_CONF.unlink(missing_ok=True)
            RESOLV_CONF.write_text(resolv)


async def serve() -> None:
    proxy, dns = EgressProxy(), DnsForwarder()
    loop = asyncio.get_running_loop()

    inbound_socket = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    inbound_socket.bind((socket.VMADDR_CID_ANY, INBOUND_PORT))
    inbound_socket.listen(64)
    inbound_socket.setblocking(False)

    servers = [
        await asyncio.start_server(proxy.handle, "127.0.0.1", PROXY_PORT),
        await asyncio.start_server(dns.handle_stream, DNS_HOST, DNS_PORT),
        await asyncio.start_server(handle_inbound, sock=inbound_socket),
    ]
    await loop.create_datagram_endpoint(
        dns.datagram_protocol, local_addr=(DNS_HOST, DNS_PORT)
    )
    log.info(
        "ready: egress via host, DNS on %s:%d, inbound on vsock %d",
        DNS_HOST,
        DNS_PORT,
        INBOUND_PORT,
    )
    await asyncio.gather(keep_time(), *(server.serve_forever() for server in servers))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--no-configure", action="store_true", help="skip network setup"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level.upper(), format="%(levelname)s %(message)s"
    )
    if not args.no_configure:
        configure_network()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
