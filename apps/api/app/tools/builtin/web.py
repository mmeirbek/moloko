"""Web tools (spec 15.6 Browser): fetch a page as text; optional search via SearXNG.

``web_fetch`` guards against SSRF: only http(s), only allowed ports, the host must resolve
to public addresses only, and the connection goes to the address that was checked (no DNS
re-binding). Redirects are followed by hand and every hop is checked again. Page text is
untrusted content (the runner fences it as data).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.tools.base import (
    BaseTool,
    ScopeError,
    ToolCategory,
    ToolContext,
    ToolFailed,
    ToolOutput,
    object_schema,
    string_prop,
)

MAX_REDIRECTS = 5
TEXT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
    "application/rss",
)
USER_AGENT = "moloko-agent/1.0 (+personal AI office)"

# Tests replace these (no network in tests).
TRANSPORT: httpx2.AsyncBaseTransport | None = None


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


RESOLVE = _resolve


def _public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def check_url(url: str, settings: Settings) -> tuple[str, int, str]:
    """(host, port, address to connect to) — or ScopeError."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ScopeError("only http(s) URLs")
    if parts.username or parts.password:
        raise ScopeError("URLs with credentials are not allowed")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in settings.web_fetch_allowed_ports:
        raise ScopeError(f"port {port} is not allowed")
    host = parts.hostname
    try:
        addrs = await RESOLVE(host, port)
    except OSError:
        raise ScopeError(f"cannot resolve {host}") from None
    if not addrs or not all(_public(a) for a in addrs):
        raise ScopeError("the address is private or local")
    return host, port, addrs[0]


class _Text(HTMLParser):
    SKIP: ClassVar[set[str]] = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCK: ClassVar[set[str]] = {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.out.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _Text()
    parser.feed(html)
    lines = [" ".join(line.split()) for line in "".join(parser.out).splitlines()]
    text = "\n".join(line for line in lines if line)
    return " ".join(parser.title.split()), text


async def fetch(url: str, settings: Settings) -> tuple[str, str, str]:
    """(final_url, content_type, body text). Follows redirects with a check per hop."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        host, port, addr = await check_url(current, settings)
        parts = urlsplit(current)
        pinned = parts._replace(netloc=(f"[{addr}]" if ":" in addr else addr) + f":{port}").geturl()
        headers = {
            "Host": host if port in (80, 443) else f"{host}:{port}",
            "User-Agent": USER_AGENT,
        }
        async with httpx2.AsyncClient(
            transport=TRANSPORT, timeout=settings.web_fetch_timeout_seconds, follow_redirects=False
        ) as client:
            req = client.build_request("GET", pinned, headers=headers)
            req.extensions["sni_hostname"] = host
            resp = await client.send(req, stream=True)
            try:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise ToolFailed("Redirect without a location.")
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    raise ToolFailed(f"The page answered HTTP {resp.status_code}.")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(TEXT_TYPES):
                    raise ToolFailed(f"Not a text page ({ctype}).")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > settings.web_fetch_max_bytes:
                        break
                encoding = resp.encoding or "utf-8"
                return (
                    current,
                    ctype,
                    bytes(body[: settings.web_fetch_max_bytes]).decode(encoding, "replace"),
                )
            finally:
                await resp.aclose()
    raise ToolFailed("Too many redirects.")


class WebFetch(BaseTool):
    name = "web_fetch"
    title = "Open a web page"
    description = "Download a public web page and return its readable text."
    group = "web"
    category = ToolCategory.READ
    timeout_seconds = 60
    input_schema = object_schema(
        {
            "url": string_prop("http(s) URL", maxLength=2000),
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 100_000},
        },
        ["url"],
    )

    async def check_scope(self, ctx: ToolContext, args: dict[str, Any]) -> None:
        await check_url(args["url"], ctx.settings)

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        try:
            final, ctype, body = await fetch(args["url"], ctx.settings)
        except httpx2.HTTPError as exc:
            raise ToolFailed(f"The page could not be loaded ({type(exc).__name__}).") from None
        if "html" in ctype or (not ctype and "<html" in body[:500].lower()):
            title, text = html_to_text(body)
        else:
            title, text = "", body
        limit = int(args.get("max_chars") or ctx.settings.tool_output_max_chars)
        head = f"URL: {final}\n" + (f"Title: {title}\n" if title else "")
        return ToolOutput(head + "\n" + text[:limit] + ("\n… (cut)" if len(text) > limit else ""))


class WebSearch(BaseTool):
    name = "web_search"
    title = "Search the web"
    description = "Search the web (self-hosted SearXNG) and return titles, links and snippets."
    group = "web"
    category = ToolCategory.READ
    input_schema = object_schema(
        {
            "query": string_prop("Search query", maxLength=400),
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        ["query"],
    )

    async def available(self, db: AsyncSession, user_id: Any, settings: Settings) -> bool:
        return bool(settings.searxng_url)

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
        url = (ctx.settings.searxng_url or "").rstrip("/") + "/search"
        async with httpx2.AsyncClient(
            transport=TRANSPORT, timeout=ctx.settings.web_fetch_timeout_seconds
        ) as client:
            try:
                resp = await client.get(url, params={"q": args["query"], "format": "json"})
            except httpx2.HTTPError:
                raise ToolFailed("The search service cannot be reached.") from None
        if resp.status_code != 200:
            raise ToolFailed(f"The search service answered HTTP {resp.status_code}.")
        results = resp.json().get("results", [])[: int(args.get("limit") or 8)]
        lines = [
            f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n   {r.get('content', '')[:300]}"
            for i, r in enumerate(results, 1)
        ]
        return ToolOutput("\n".join(lines) if lines else "No results.")


WEB_TOOLS: tuple[BaseTool, ...] = (WebFetch(), WebSearch())
