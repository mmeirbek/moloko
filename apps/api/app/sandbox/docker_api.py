"""A small Docker Engine API client over the unix socket (runner side only)."""

from __future__ import annotations

import contextlib
import struct
from typing import Any

import httpx2

API = "/v1.45"  # Engine 26+: needed for volume subpaths


class DockerError(Exception):
    pass


class DockerApi:
    def __init__(
        self, socket_path: str, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self._transport = transport or httpx2.AsyncHTTPTransport(uds=socket_path)

    def _client(self, timeout: float = 30) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            base_url="http://docker", transport=self._transport, timeout=timeout
        )

    async def _json(self, method: str, path: str, *, http_timeout: float = 30, **kw: Any) -> Any:
        async with self._client(http_timeout) as c:
            resp = await c.request(method, API + path, **kw)
        if resp.status_code >= 400:
            raise DockerError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json() if resp.content else None

    async def ping(self) -> bool:
        try:
            async with self._client(5) as c:
                return (await c.get(API + "/_ping")).status_code == 200
        except httpx2.HTTPError:
            return False

    async def image_exists(self, image: str) -> bool:
        async with self._client() as c:
            return (await c.get(f"{API}/images/{image}/json")).status_code == 200

    async def pull(self, image: str) -> None:
        name, _, tag = (
            image.rpartition(":") if ":" in image.split("/")[-1] else (image, "", "latest")
        )
        async with self._client(600) as c:
            resp = await c.post(f"{API}/images/create", params={"fromImage": name, "tag": tag})
        if resp.status_code >= 400:
            raise DockerError(f"pull {image}: HTTP {resp.status_code}")

    async def create(self, name: str, spec: dict[str, Any]) -> str:
        data = await self._json("POST", "/containers/create", params={"name": name}, json=spec)
        return str(data["Id"])

    async def start(self, cid: str) -> None:
        await self._json("POST", f"/containers/{cid}/start")

    async def wait(self, cid: str, max_seconds: float) -> int:
        data = await self._json("POST", f"/containers/{cid}/wait", http_timeout=max_seconds)
        return int(data.get("StatusCode", -1))

    async def kill(self, cid: str) -> None:
        with contextlib.suppress(DockerError):  # already stopped
            await self._json("POST", f"/containers/{cid}/kill")

    async def inspect(self, cid: str) -> dict[str, Any]:
        return dict(await self._json("GET", f"/containers/{cid}/json"))

    async def logs(self, cid: str, limit: int) -> tuple[str, str, bool]:
        """stdout, stderr (each capped at ``limit`` bytes), truncated."""
        async with self._client() as c:
            resp = await c.get(f"{API}/containers/{cid}/logs", params={"stdout": 1, "stderr": 1})
        return demux(resp.content, limit)

    async def remove(self, cid: str) -> None:
        with contextlib.suppress(DockerError):
            await self._json("DELETE", f"/containers/{cid}", params={"force": 1, "v": 1})


def demux(raw: bytes, limit: int) -> tuple[str, str, bool]:
    """Split Docker's multiplexed log stream (8-byte frame headers) into stdout/stderr."""
    out, err = bytearray(), bytearray()
    truncated = False
    i = 0
    while i + 8 <= len(raw):
        stream, size = raw[i], struct.unpack(">I", raw[i + 4 : i + 8])[0]
        chunk = raw[i + 8 : i + 8 + size]
        target = err if stream == 2 else out
        room = limit - len(target)
        if room > 0:
            target.extend(chunk[:room])
        if len(chunk) > max(room, 0):
            truncated = True
        i += 8 + size
    return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), truncated
