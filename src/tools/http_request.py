"""http_request tool: the SSRF-protected six-step security chain (contract §2.2; ARCHITECTURE §6.2 / ADR-005).

Implementation note (contract §2.2 chain step 4 allows an "equivalent"): this tool does not rely on httpx
transport DNS behavior but uses a hand-written minimal HTTP/1.1 client — ``asyncio.open_connection``
natively separates the connect address from ``server_hostname``, naturally satisfying
resolve-then-connect with HTTPS SNI/certificate validation against the original hostname (no verify=False).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel

from src.config import Settings
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec

MAX_REDIRECTS = 3
MAX_BODY_BYTES = 1_048_576  # 1MB
TIMEOUT_SECONDS = 10.0
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# DNS-resolution step abstraction (injectable — FakeResolver is the test channel for the M1-5 rebinding case)
Resolver = Callable[[str, int], list[IPAddress]]


class Reader(Protocol):
    """Minimal read-side interface (structurally compatible with asyncio.StreamReader)."""

    async def readline(self) -> bytes: ...

    async def readexactly(self, n: int) -> bytes: ...

    async def read(self, n: int = -1) -> bytes: ...


class Writer(Protocol):
    """Minimal write-side interface (structurally compatible with asyncio.StreamWriter)."""

    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


# Connect-step abstraction (injectable — tests use FakeReader/FakeWriter to assert the actual connect target)
Connector = Callable[[str, int, bool, "str | None"], Awaitable[tuple[Reader, Writer]]]


class HttpRequestInput(BaseModel):
    """http_request arguments (M1: GET only)."""

    url: str
    method: Literal["GET"] = "GET"


class HttpRequestToolSpec(ToolSpec):
    """http_request-specific spec: GET is overridden to idempotent (ARCHITECTURE §6.4 call-level override)."""

    def effective_idempotency(self, args: dict[str, Any]) -> Literal["idempotent", "non-idempotent"]:
        if args.get("method", "GET") == "GET":
            return "idempotent"
        return self.idempotency


class _HttpBlocked(Exception):
    """Security refusal (→ BLOCKED: prefix)."""


def _default_resolver(hostname: str, port: int) -> list[IPAddress]:
    """Default DNS resolution: all getaddrinfo addresses."""
    results: list[IPAddress] = []
    for info in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM):
        sockaddr = info[4]
        results.append(ipaddress.ip_address(sockaddr[0]))
    return results


async def _default_connector(ip: str, port: int, tls: bool, server_hostname: str | None) -> tuple[Reader, Writer]:
    """Default connector: bind directly to the validated IP (resolve-then-connect).

    HTTPS: server_hostname=original host → TLS SNI and certificate validation both use the original hostname;
    the connect address is the validated IP; no second resolution happens.
    """
    if tls:
        if server_hostname is None:
            raise ValueError("TLS connection requires server_hostname")
        context = ssl.create_default_context()
        reader, writer = await asyncio.open_connection(
            ip, port, ssl=context, server_hostname=server_hostname
        )
    else:
        reader, writer = await asyncio.open_connection(ip, port)
    return reader, writer


def _ip_allowed(ip: IPAddress) -> bool:
    """Private/reserved/loopback/link-local (incl. cloud metadata 169.254.169.254)/multicast/unspecified are all rejected."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_and_resolve(
    url: str, allowed_hosts: list[str], resolver: Resolver
) -> tuple[str, int, bool, str, str]:
    """Chain steps 1~3: URL parse → host allow-list → DNS full-IP validation.

    Returns (hostname, port, tls, validated IP, request target path?query).
    """
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise _HttpBlocked(f"invalid URL: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise _HttpBlocked(f"scheme not allowed: {parts.scheme!r}")
    hostname = parts.hostname
    if not hostname:
        raise _HttpBlocked("URL has no hostname")
    if parts.username is not None or parts.password is not None:
        raise _HttpBlocked("URL userinfo not allowed")
    hostname = hostname.lower()
    if hostname not in allowed_hosts:  # exact match, before DNS
        raise _HttpBlocked(f"host not allowed: {hostname}")
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    addresses = resolver(hostname, port)
    if not addresses:
        raise _HttpBlocked(f"DNS resolution returned no addresses for {hostname}")
    for address in addresses:  # validate all; any violation rejects the whole set (blocks multi-record rebinding)
        if not _ip_allowed(address):
            raise _HttpBlocked(f"non-public IP address: {address}")
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return hostname, port, parts.scheme == "https", str(addresses[0]), target


async def _read_body(reader: Reader, headers: dict[str, str]) -> tuple[bytes, bool]:
    """Read the response body: chunked / content-length / read to EOF; total ≤1MB, truncated beyond."""
    body = bytearray()
    truncated = False
    if headers.get("transfer-encoding", "").strip().lower() == "chunked":
        while True:
            size_line = await reader.readline()
            try:
                size = int(size_line.split(b";", 1)[0].strip() or b"0", 16)
            except ValueError as exc:
                raise ValueError(f"malformed chunk size: {size_line!r}") from exc
            if size == 0:
                await reader.readline()  # trailing CRLF
                break
            chunk = await reader.readexactly(size)
            await reader.readline()  # chunk CRLF
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                body += chunk[: MAX_BODY_BYTES - len(body)]
                truncated = True
                break
            body += chunk
        return bytes(body), truncated
    declared = headers.get("content-length")
    if declared is not None:
        try:
            remaining = int(declared)
        except ValueError as exc:
            raise ValueError(f"malformed content-length: {declared!r}") from exc
        while remaining > 0:
            chunk = await reader.readexactly(min(remaining, 65536))
            if not chunk:
                break
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                body += chunk[: MAX_BODY_BYTES - len(body)]
                truncated = True
                break
            body += chunk
            remaining -= len(chunk)
        return bytes(body), truncated
    while True:  # no length indication, read to EOF
        chunk = await reader.read(65536)
        if not chunk:
            break
        if len(body) + len(chunk) > MAX_BODY_BYTES:
            body += chunk[: MAX_BODY_BYTES - len(body)]
            truncated = True
            break
        body += chunk
    return bytes(body), truncated


async def _single_request(
    url: str,
    allowed_hosts: list[str],
    resolver: Resolver,
    connector: Connector,
) -> tuple[int, dict[str, str], bytes, bool]:
    """Single-hop request: validate → connect to the validated IP → send → read the response."""
    hostname, port, tls, ip, target = _validate_and_resolve(url, allowed_hosts, resolver)
    reader, writer = await connector(ip, port, tls, hostname if tls else None)
    try:
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {hostname}\r\n"  # the Host header keeps the original hostname
            "User-Agent: cognitive-agent-lab/0.1\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        writer.write(request)
        await writer.drain()

        status_line = await reader.readline()
        if not status_line:
            raise ValueError("empty response")
        try:
            status = int(status_line.split(None, 2)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"malformed status line: {status_line!r}") from exc

        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()

        body, truncated = await _read_body(reader, headers)
        return status, headers, body, truncated
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass  # a fake/disconnected cleanup failure does not affect the result


async def _get(
    url: str,
    allowed_hosts: list[str],
    resolver: Resolver,
    connector: Connector,
) -> ToolResult:
    """Full GET: redirects followed manually hop by hop, ≤3 hops; every hop re-runs the full security chain."""
    current = url
    hops = 0
    while True:
        status, headers, body, truncated = await asyncio.wait_for(
            _single_request(current, allowed_hosts, resolver, connector),
            TIMEOUT_SECONDS,
        )
        if status in _REDIRECT_STATUSES and "location" in headers:
            if hops >= MAX_REDIRECTS:
                raise _HttpBlocked(f"redirect limit exceeded (> {MAX_REDIRECTS} hops)")
            hops += 1
            # a relative Location is resolved against the current URL to absolute (RFC 3986)
            current = urllib.parse.urljoin(current, headers["location"])
            continue
        text = body.decode("utf-8", errors="replace")
        lines = [
            f"status: {status}",
            f"content-type: {headers.get('content-type', 'unknown')}",
            f"body: {text}",
        ]
        if truncated:
            lines.append("truncated: true")
        return ToolResult(ok=True, result="\n".join(lines))


async def _execute(
    args: HttpRequestInput,
    allowed_hosts: list[str],
    resolver: Resolver,
    connector: Connector,
) -> ToolResult:
    try:
        return await _get(args.url, allowed_hosts, resolver, connector)
    except _HttpBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    except asyncio.TimeoutError:
        return ToolResult(ok=False, error="http_request: request timed out")
    except (OSError, ValueError) as exc:
        return ToolResult(ok=False, error=f"http_request: {type(exc).__name__}: {exc}")


def build_tool_spec(
    settings: Settings,
    *,
    resolver: Resolver | None = None,
    connector: Connector | None = None,
) -> ToolSpec:
    """Build http_request's ToolSpec; resolver/connector are test injection points."""
    allowed_hosts = settings.allowed_hosts
    effective_resolver = resolver if resolver is not None else _default_resolver
    effective_connector = connector if connector is not None else _default_connector

    async def executor(base: Any) -> ToolResult:
        return await _execute(
            cast(HttpRequestInput, base), allowed_hosts, effective_resolver, effective_connector
        )

    return HttpRequestToolSpec(
        name="http_request",
        description="Issue an HTTP GET request to an allow-listed host and return the response text (redirects validated hop by hop, limit 3)",
        input_model=HttpRequestInput,
        idempotency="non-idempotent",
        risk_level="medium",
        executor=executor,
    )
