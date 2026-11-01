"""Egress proxy for the agents' browser (compose service ``egress``).

The browser container sits on an internal Docker network whose only other member is this
proxy, so every request it makes comes through here. The proxy resolves the host itself
and connects only to public addresses on allowed ports — never to the home network, the
Tailscale range, the Docker networks or the server (SSRF protection, also against DNS
rebinding: the checked address is the one connected to). Per-connection byte and idle
limits. It logs hosts and sizes only, never paths, headers or bodies.

Supports ``CONNECT host:port`` (HTTPS) and plain ``http://`` requests.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from app.tools.builtin.web import _public

logger = logging.getLogger("moloko.egress")

HEAD_LIMIT = 16_384
Resolver = Callable[[str, int], Awaitable[list[str]]]


async def resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class EgressProxy:
    def __init__(
        self,
        *,
        allowed_ports: tuple[int, ...] = (80, 443),
        max_bytes: int = 30_000_000,
        idle_seconds: float = 20.0,
        max_connections: int = 64,
        resolver: Resolver = resolve,
        allow_private: bool = False,  # tests only
    ) -> None:
        self.allowed_ports = allowed_ports
        self.max_bytes = max_bytes
        self.idle_seconds = idle_seconds
        self.slots = asyncio.Semaphore(max_connections)
        self.resolver = resolver
        self.allow_private = allow_private

    async def _target(self, host: str, port: int) -> str:
        if port not in self.allowed_ports:
            raise PermissionError(f"port {port} is not allowed")
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
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), self.idle_seconds
            )
        except (OSError, TimeoutError):
            return await self._refuse(writer, 502, "cannot connect")
        if method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            up_writer.write(rest)
            await up_writer.drain()
        budget = [self.max_bytes]
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


def main() -> None:  # python -m app.sandbox.egress
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    proxy = EgressProxy(
        max_bytes=int(os.environ.get("EGRESS_MAX_BYTES", "30000000")),
        idle_seconds=float(os.environ.get("EGRESS_IDLE_SECONDS", "20")),
    )
    port = int(os.environ.get("EGRESS_PORT", "3128"))

    async def run() -> None:
        server = await serve(proxy, "0.0.0.0", port)  # noqa: S104 — only on the internal browser network
        async with server:
            await server.serve_forever()

    asyncio.run(run())


if __name__ == "__main__":
    main()
