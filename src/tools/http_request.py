"""http_request 工具：SSRF 防护六步安全链路（契约 §2.2；ARCHITECTURE §6.2 / ADR-005）。

实现说明（契约 §2.2 链路 4 允许"等价物"）：不依赖 httpx transport 的 DNS 行为，
改用手写最小 HTTP/1.1 客户端——``asyncio.open_connection`` 原生支持连接地址与
``server_hostname`` 分离，天然满足 resolve-then-connect 与 HTTPS SNI/证书校验
以原域名进行（未使用 verify=False）。
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

# DNS 解析步骤抽象（可注入——FakeResolver 是 M1-5 rebinding 用例的测试通道）
Resolver = Callable[[str, int], list[IPAddress]]


class Reader(Protocol):
    """读取侧最小接口（asyncio.StreamReader 结构兼容）。"""

    async def readline(self) -> bytes: ...

    async def readexactly(self, n: int) -> bytes: ...

    async def read(self, n: int = -1) -> bytes: ...


class Writer(Protocol):
    """写入侧最小接口（asyncio.StreamWriter 结构兼容）。"""

    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


# 连接步骤抽象（可注入——测试用 FakeReader/FakeWriter 断言实际连接目标）
Connector = Callable[[str, int, bool, "str | None"], Awaitable[tuple[Reader, Writer]]]


class HttpRequestInput(BaseModel):
    """http_request 参数（M1 仅 GET）。"""

    url: str
    method: Literal["GET"] = "GET"


class HttpRequestToolSpec(ToolSpec):
    """http_request 专用 spec：GET 覆写为 idempotent（ARCHITECTURE §6.4 调用级覆写）。"""

    def effective_idempotency(self, args: dict[str, Any]) -> Literal["idempotent", "non-idempotent"]:
        if args.get("method", "GET") == "GET":
            return "idempotent"
        return self.idempotency


class _HttpBlocked(Exception):
    """安全拒绝（→ BLOCKED: 前缀）。"""


def _default_resolver(hostname: str, port: int) -> list[IPAddress]:
    """默认 DNS 解析：getaddrinfo 全量地址。"""
    results: list[IPAddress] = []
    for info in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM):
        sockaddr = info[4]
        results.append(ipaddress.ip_address(sockaddr[0]))
    return results


async def _default_connector(ip: str, port: int, tls: bool, server_hostname: str | None) -> tuple[Reader, Writer]:
    """默认连接器：直接绑定已校验 IP 建连（resolve-then-connect）。

    HTTPS：server_hostname=原域名 → TLS SNI 与证书校验均以原域名进行；
    连接地址为已校验 IP，不发生二次解析。
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
    """私有/保留/环回/链路本地（含云元数据 169.254.169.254）/组播/未指定一律拒绝。"""
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
    """链路 1~3：URL 解析 → 域名白名单 → DNS 全量 IP 校验。

    返回 (hostname, port, tls, 已校验 IP, 请求目标 path?query)。
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
    if hostname not in allowed_hosts:  # 精确匹配，先于 DNS
        raise _HttpBlocked(f"host not allowed: {hostname}")
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    addresses = resolver(hostname, port)
    if not addresses:
        raise _HttpBlocked(f"DNS resolution returned no addresses for {hostname}")
    for address in addresses:  # 全量校验，任一违规整条拒绝（防多记录 rebinding）
        if not _ip_allowed(address):
            raise _HttpBlocked(f"non-public IP address: {address}")
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return hostname, port, parts.scheme == "https", str(addresses[0]), target


async def _read_body(reader: Reader, headers: dict[str, str]) -> tuple[bytes, bool]:
    """读响应体：chunked / content-length / 读到 EOF；累计 ≤1MB，超限截断。"""
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
    while True:  # 无长度指示，读到 EOF
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
    """单跳请求：校验 → 连已校验 IP → 发送 → 读响应。"""
    hostname, port, tls, ip, target = _validate_and_resolve(url, allowed_hosts, resolver)
    reader, writer = await connector(ip, port, tls, hostname if tls else None)
    try:
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {hostname}\r\n"  # Host 头保留原域名
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
            pass  # fake/已断开连接的清理失败不影响结果


async def _get(
    url: str,
    allowed_hosts: list[str],
    resolver: Resolver,
    connector: Connector,
) -> ToolResult:
    """完整 GET：重定向手动逐跳 ≤3，每跳重新走完整安全链路。"""
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
            # 相对 Location 以当前 URL 解析为绝对（RFC 3986）
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
    """构造 http_request 的 ToolSpec；resolver/connector 为测试注入点。"""
    allowed_hosts = settings.allowed_hosts
    effective_resolver = resolver if resolver is not None else _default_resolver
    effective_connector = connector if connector is not None else _default_connector

    async def executor(base: Any) -> ToolResult:
        return await _execute(
            cast(HttpRequestInput, base), allowed_hosts, effective_resolver, effective_connector
        )

    return HttpRequestToolSpec(
        name="http_request",
        description="向白名单域名发起 HTTP GET 请求并返回响应文本（重定向逐跳校验，上限 3 跳）",
        input_model=HttpRequestInput,
        idempotency="non-idempotent",
        risk_level="medium",
        executor=executor,
    )
