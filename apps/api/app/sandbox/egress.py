"""Egress proxies of the sandbox (compose services ``egress`` and ``egress-packages``).

``egress`` — the agents' browser. The browser container sits on an internal Docker network
whose only other member is this proxy, so every request it makes comes through here.

``egress-packages`` — package downloads (``terminal_run`` with ``network: "packages"``).
Same code with an allow-list (``EGRESS_ALLOWED_HOSTS``, default the npm and PyPI
registries): only HTTPS tunnels (``CONNECT``) to those exact hosts, and the TLS ClientHello
that follows must name the same host (SNI), so a client cannot reach another site behind the
same CDN address. It sits alone with the sandbox containers on its own internal network.

Both resolve the host themselves and connect only to public addresses on allowed ports —
never to the home network, the Tailscale range, the Docker networks or the server (SSRF
protection, also against DNS rebinding: the checked address is the one connected to).
Per-connection byte and idle limits. They log hosts and sizes only, never paths, headers or
bodies.

Supports ``CONNECT host:port`` (HTTPS) and, without an allow-list, plain ``http://``
requests.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

from app.tools.builtin.web import _public

logger = logging.getLogger("moloko.egress")

HEAD_LIMIT = 16_384
HELLO_LIMIT = 65_536  # a TLS ClientHello is a few KB; more is not a client we know
Resolver = Callable[[str, int], Awaitable[list[str]]]


async def resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def host_allowed(host: str, allowed: Iterable[str]) -> bool:
    """Exact host names; ``*.example.org`` allows the subdomains of example.org."""
    name = host.lower().rstrip(".")
    for entry in allowed:
        if entry.startswith("*.") and name.endswith(entry[1:]) and name != entry[2:]:
            return True
        if name == entry:
            return True
    return False


def server_name(hello: bytes) -> str | None:
    """The host name (SNI) of a TLS ClientHello handshake body, if it names one."""

    def num(at: int, size: int) -> int:
        if at + size > len(hello):
            raise ValueError("short")
        return int.from_bytes(hello[at : at + size], "big")

    try:
        at = 2 + 32  # legacy version, random
        at += 1 + num(at, 1)  # session id
        at += 2 + num(at, 2)  # cipher suites
        at += 1 + num(at, 1)  # compression methods
        end = at + 2 + num(at, 2)
        at += 2
        while at + 4 <= min(end, len(hello)):
            kind, size = num(at, 2), num(at + 2, 2)
            at += 4
            if kind == 0:  # server_name: list length, then (type, length, name)…
                stop, at = at + size, at + 2
                while at + 3 <= stop:
                    name_type, length = num(at, 1), num(at + 1, 2)
                    at += 3
                    if name_type == 0:
                        return hello[at : at + length].decode("ascii").lower().rstrip(".")
                    at += length
                return None
            at += size
    except (ValueError, UnicodeDecodeError):
        return None
    return None


async def read_client_hello(
    reader: asyncio.StreamReader, idle_seconds: float
) -> tuple[bytes, str | None]:
    """The client's first TLS record(s) up to the end of its ClientHello, and its SNI.
    Returns the bytes read so far and None when it is not a TLS ClientHello."""
    raw, handshake = b"", b""
    while len(raw) <= HELLO_LIMIT:
        header = await asyncio.wait_for(reader.readexactly(5), idle_seconds)
        raw += header
        if header[0] != 0x16:  # not a TLS handshake record
            return raw, None
        body = await asyncio.wait_for(
            reader.readexactly(int.from_bytes(header[3:5], "big")), idle_seconds
        )
        raw += body
        handshake += body
        if len(handshake) >= 4:
            if handshake[0] != 0x01:  # not a ClientHello
                return raw, None
            need = 4 + int.from_bytes(handshake[1:4], "big")
            if len(handshake) >= need:
                return raw, server_name(handshake[4:need])
    return raw, None


class EgressProxy:
    def __init__(
        self,
        *,
        allowed_ports: tuple[int, ...] = (80, 443),
        allowed_hosts: Iterable[str] = (),  # empty = any public host (the browser's proxy)
        max_bytes: int = 30_000_000,
        idle_seconds: float = 20.0,
        max_connections: int = 64,
        resolver: Resolver = resolve,
        allow_private: bool = False,  # tests only
    ) -> None:
        self.allowed_ports = allowed_ports
        self.allowed_hosts = tuple(
            h.strip().lower().rstrip(".") for h in allowed_hosts if h.strip()
        )
        self.max_bytes = max_bytes
        self.idle_seconds = idle_seconds
        self.slots = asyncio.Semaphore(max_connections)
        self.resolver = resolver
        self.allow_private = allow_private

    async def _target(self, host: str, port: int) -> str:
        if port not in self.allowed_ports:
            raise PermissionError(f"port {port} is not allowed")
        if self.allowed_hosts and not host_allowed(host, self.allowed_hosts):
            raise PermissionError("host is not on the allow-list")
        try:
            addrs = await self.resolver(host, port)
        except OSError:
            raise PermissionError("cannot resolve") from None
        if not addrs:
            raise PermissionError("cannot resolve")
        if not self.allow_private and not all(_public(a) for a in addrs):
            raise PermissionError("private or local address")
        return addrs[0]

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async with self.slots:
            try:
                await self._handle(reader, writer)
            except (ConnectionError, TimeoutError, asyncio.IncompleteReadError):
                pass
            finally:
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self.idle_seconds)
        if len(head) > HEAD_LIMIT:
            return await self._refuse(writer, 431, "too large")
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            return await self._refuse(writer, 400, "bad request")
        if method == "CONNECT":
            host, _, port_text = target.rpartition(":")
            host = host.strip("[]")
            port = int(port_text) if port_text.isdigit() else 0
            rest = b""
        elif self.allowed_hosts:  # package registries: HTTPS only
            return await self._refuse(writer, 403, "only HTTPS (CONNECT) is allowed")
        else:
            parts = urlsplit(target)
            if parts.scheme != "http" or not parts.hostname:
                return await self._refuse(writer, 400, "absolute http:// URL expected")
            host, port = parts.hostname, parts.port or 80
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            kept = [line for line in lines[1:] if line and not line.lower().startswith("proxy-")]
            rest = (f"{method} {path} {version}\r\n" + "\r\n".join(kept) + "\r\n\r\n").encode(
                "latin-1"
            )
        try:
            address = await self._target(host, port)
        except PermissionError as exc:
            logger.info("egress_refused", extra={"host": host[:100], "reason": str(exc)})
            return await self._refuse(writer, 403, str(exc))
        if self.allowed_hosts:
            # Package registries: the tunnel must be TLS to the very host it was opened for
            # (checked before anything is sent anywhere). The answer to CONNECT has to come
            # first, so a later failure can only close the connection.
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            rest, name = await read_client_hello(reader, self.idle_seconds)
            if name != host.lower().rstrip("."):
                reason = "not a TLS connection" if name is None else "TLS name differs"
                logger.info("egress_refused", extra={"host": host[:100], "reason": reason})
                return None
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), self.idle_seconds
            )
        except (OSError, TimeoutError):
            if self.allowed_hosts:
                return None  # 200 was already sent
            return await self._refuse(writer, 502, "cannot connect")
        if method == "CONNECT" and not self.allowed_hosts:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        if rest:
            up_writer.write(rest)
            await up_writer.drain()
        budget = [self.max_bytes - len(rest)]
        await asyncio.gather(
            self._pipe(reader, up_writer, budget), self._pipe(up_reader, writer, budget)
        )
        logger.info("egress", extra={"host": host[:100], "bytes": self.max_bytes - budget[0]})

    async def _pipe(
        self, src: asyncio.StreamReader, dst: asyncio.StreamWriter, budget: list[int]
    ) -> None:
        try:
            while budget[0] > 0:
                data = await asyncio.wait_for(src.read(65_536), self.idle_seconds)
                if not data:
                    break
                budget[0] -= len(data)
                dst.write(data)
                await dst.drain()
        except (ConnectionError, TimeoutError):
            pass
        finally:
            with contextlib.suppress(Exception):
                dst.close()

    async def _refuse(self, writer: asyncio.StreamWriter, status: int, reason: str) -> None:
        body = f"moloko egress: {reason}\n".encode()
        head = (
            f"HTTP/1.1 {status} Refused\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        )
        writer.write(head.encode() + body)
        with contextlib.suppress(Exception):
            await writer.drain()


async def serve(proxy: EgressProxy, host: str, port: int) -> asyncio.Server:
    return await asyncio.start_server(proxy.handle, host, port)


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


def main() -> None:  # python -m app.sandbox.egress
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    proxy = EgressProxy(
        allowed_ports=tuple(int(p) for p in _list("EGRESS_ALLOWED_PORTS", "80,443")),
        allowed_hosts=_list("EGRESS_ALLOWED_HOSTS", ""),
        max_bytes=int(os.environ.get("EGRESS_MAX_BYTES", "30000000")),
        idle_seconds=float(os.environ.get("EGRESS_IDLE_SECONDS", "20")),
    )
    port = int(os.environ.get("EGRESS_PORT", "3128"))

    async def run() -> None:
        server = await serve(proxy, "0.0.0.0", port)  # noqa: S104 — only on its internal network(s)
        async with server:
            await server.serve_forever()

    asyncio.run(run())


if __name__ == "__main__":
    main()
