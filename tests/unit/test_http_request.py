"""M1-5 http_request unit tests (contract §3.2; matched by -k tool_security).

No real network: FakeResolver + FakeConnector (fake reader/writer streams) are injected;
real GET is only tested on blocked paths (the security-validation logic is fully covered).
"""

from __future__ import annotations

import ipaddress
from typing import Any

import pytest

from src.config import Settings
from src.models.tool_result import ToolResult
from src.tools import http_request


class FakeResolver:
    """Returns the preset results one per call (simulating rebinding: the second differs from the first)."""

    def __init__(self, *results: list[str]) -> None:
        self._results = [list(r) for r in results]
        self.calls: list[tuple[str, int]] = []

    def __call__(self, hostname: str, port: int) -> list[http_request.IPAddress]:
        self.calls.append((hostname, port))
        index = min(len(self.calls) - 1, len(self._results) - 1)
        return [ipaddress.ip_address(item) for item in self._results[index]]


class FakeReader:
    """Minimal read interface (a structural implementation of the http_request.Reader protocol)."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readline(self) -> bytes:
        idx = self._data.find(b"\n")
        if idx == -1:
            line, self._data = self._data, b""
        else:
            line, self._data = self._data[: idx + 1], self._data[idx + 1 :]
        return line

    async def readexactly(self, n: int) -> bytes:
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    async def read(self, n: int = -1) -> bytes:
        if n < 0:
            chunk, self._data = self._data, b""
        else:
            chunk, self._data = self._data[:n], self._data[n:]
        return chunk


class FakeWriter:
    """Minimal write interface (records what was written for assertions)."""

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class RecordingConnector:
    """Records the connect parameters of each call (IP/port/TLS/SNI); returns the preset raw responses per call."""

    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self.connections: list[tuple[str, int, bool, str | None]] = []
        self.writers: list[FakeWriter] = []

    async def __call__(
        self, ip: str, port: int, tls: bool, server_hostname: str | None
    ) -> tuple[FakeReader, FakeWriter]:
        self.connections.append((ip, port, tls, server_hostname))
        writer = FakeWriter()
        self.writers.append(writer)
        index = min(len(self.connections) - 1, len(self._responses) - 1)
        return FakeReader(self._responses[index]), writer


def _response(status: int = 200, body: bytes = b"ok", headers: dict[str, str] | None = None) -> bytes:
    head: dict[str, str] = {"Content-Length": str(len(body))}
    head.update(headers or {})
    lines = [f"HTTP/1.1 {status} Status"]
    lines.extend(f"{name}: {value}" for name, value in head.items())
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


async def _run(
    url: str,
    *,
    resolver: Any,
    connector: Any,
    allowed_hosts: str = "example.com",
) -> ToolResult:
    settings = Settings(http_allowed_hosts=allowed_hosts, data_sandbox_dir="data/.test-sandbox")
    spec = http_request.build_tool_spec(settings, resolver=resolver, connector=connector)
    return await spec.executor(http_request.HttpRequestInput(url=url))


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_allows_whitelisted_public_host() -> None:
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([_response(200, b"hello example")])
    result = await _run("https://example.com/index.html", resolver=resolver, connector=connector)

    assert result.ok
    assert "status: 200" in result.result
    assert "hello example" in result.result
    # evidence that resolve-then-connect works: the connect target == the validated IP, with no second resolution
    assert len(resolver.calls) == 1
    ip, port, tls, sni = connector.connections[0]
    assert ip == "93.184.216.34"
    assert port == 443
    # HTTPS: SNI/certificate validation against the original hostname (server_hostname separated)
    assert tls is True
    assert sni == "example.com"
    # the Host header keeps the original hostname
    assert b"Host: example.com\r\n" in connector.writers[0].written[0]


@pytest.mark.asyncio
@pytest.mark.tool_security
@pytest.mark.parametrize("private_ip", ["192.168.1.1", "10.0.0.5", "172.16.31.4"])
async def test_http_blocks_private_ip(private_ip: str) -> None:
    resolver = FakeResolver([private_ip])
    connector = RecordingConnector([])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert connector.connections == []  # no connection made


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_cloud_metadata() -> None:
    # an IP literal goes straight in (blocked by IP validation after passing the allow-list — cloud metadata 169.254.169.254)
    resolver = FakeResolver(["169.254.169.254"])
    connector = RecordingConnector([])
    result = await _run(
        "http://169.254.169.254/latest/meta-data",
        resolver=resolver,
        connector=connector,
        allowed_hosts="example.com,169.254.169.254",
    )
    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert connector.connections == []


@pytest.mark.asyncio
@pytest.mark.tool_security
@pytest.mark.parametrize("blocked_ipv6", ["::1", "fe80::1", "fc00::1"])
async def test_http_blocks_loopback_ipv6(blocked_ipv6: str) -> None:
    resolver = FakeResolver([blocked_ipv6])
    connector = RecordingConnector([])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert connector.connections == []


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_non_whitelisted_host() -> None:
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([])
    result = await _run("http://evil.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert resolver.calls == []  # the allow-list check precedes DNS


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_mixed_dns_records() -> None:
    resolver = FakeResolver(["93.184.216.34", "10.0.0.1"])  # multiple records incl. a private one → the whole set is rejected
    connector = RecordingConnector([])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert connector.connections == []


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_redirect_to_private() -> None:
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector(
        [_response(302, b"", headers={"Location": "http://10.0.0.1/x"})]
    )
    result = await _run("http://example.com/start", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert len(connector.connections) == 1  # the second hop never connects (rejected when re-running the full chain)


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_redirect_loop_and_limit() -> None:
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector(
        [_response(302, b"", headers={"Location": "http://example.com/loop"})] * 4
    )
    result = await _run("http://example.com/loop", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert "redirect" in result.error
    # the initial request + 3 hops = 4 connections; beyond that the limit trips
    assert len(connector.connections) == 4


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_dns_rebinding_fake_resolver() -> None:
    # the first resolution returns a public IP, the second a private one — an implementation with a second resolution (TOCTOU) would succeed
    resolver = FakeResolver(["93.184.216.34"], ["10.0.0.1"])
    connector = RecordingConnector([_response(200, b"stable")])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert len(resolver.calls) == 1  # resolved exactly once
    assert connector.connections[0][0] == "93.184.216.34"  # the connected IP == the first validated value


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_response_size_truncation() -> None:
    body = b"x" * (http_request.MAX_BODY_BYTES + 100)
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([_response(200, body)])
    result = await _run("http://example.com/big", resolver=resolver, connector=connector)

    assert result.ok
    assert "truncated: true" in result.result
    # body truncated to 1MB
    body_line = next(line for line in result.result.splitlines() if line.startswith("body: "))
    assert len(body_line) == len("body: ") + http_request.MAX_BODY_BYTES


@pytest.mark.tool_security
def test_http_idempotency_declarations() -> None:
    """Idempotency declarations and the call-level override (ARCHITECTURE §6.4; the snapshot basis for M2 recovery semantics)."""
    from src.tools import calc, file_write

    settings = Settings()
    assert calc.build_tool_spec(settings).idempotency == "idempotent"
    assert file_write.build_tool_spec(settings).idempotency == "non-idempotent"

    http_spec = http_request.build_tool_spec(settings)
    assert http_spec.idempotency == "non-idempotent"
    assert http_spec.effective_idempotency({"method": "GET"}) == "idempotent"  # GET override
    assert http_spec.effective_idempotency({}) == "idempotent"  # an omitted method means GET
    assert http_spec.effective_idempotency({"method": "POST"}) == "non-idempotent"


# ---------------------------------------------------------------------------
# G-2 regression supplements (qa-M1.md §3): chunked / EOF / malformed responses / URL errors / connection exceptions / timeouts
# ---------------------------------------------------------------------------


def _chunked_payload(chunks: list[bytes]) -> bytes:
    """Build a chunked-encoded response body byte stream."""
    return b"".join(b"%x\r\n%s\r\n" % (len(chunk), chunk) for chunk in chunks) + b"0\r\n\r\n"


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_reads_chunked_body() -> None:
    """Chunked transfer-encoding: multiple chunks concatenate correctly, no truncation."""
    raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + _chunked_payload(
        [b"hello ", b"chunked ", b"world"]
    )
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert "body: hello chunked world" in result.result
    assert "truncated" not in result.result


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_chunked_truncation() -> None:
    """Chunked over 1MB: truncated to 1MB and marked truncated."""
    raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + _chunked_payload(
        [b"x" * 600_000, b"y" * 600_000]
    )
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert "truncated: true" in result.result
    body_line = next(line for line in result.result.splitlines() if line.startswith("body: "))
    assert len(body_line) == len("body: ") + http_request.MAX_BODY_BYTES


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_reads_body_to_eof() -> None:
    """No content-length / transfer-encoding: read to connection EOF; the request line carries path?query."""
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nno length headers here"
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/path?q=1", resolver=resolver, connector=connector)

    assert result.ok
    assert "body: no length headers here" in result.result
    assert "truncated" not in result.result
    # the request line carries the full path?query (the L153 branch)
    assert b"GET /path?q=1 HTTP/1.1\r\n" in connector.writers[0].written[0]


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_eof_truncation() -> None:
    """EOF mode over 1MB: truncated to 1MB and marked truncated."""
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n" + b"z" * (
        http_request.MAX_BODY_BYTES + 100
    )
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert "truncated: true" in result.result
    body_line = next(line for line in result.result.splitlines() if line.startswith("body: "))
    assert len(body_line) == len("body: ") + http_request.MAX_BODY_BYTES


@pytest.mark.asyncio
@pytest.mark.tool_security
@pytest.mark.parametrize(
    "raw",
    [
        b"",  # empty response
        b"GARBAGE\r\n\r\n",  # the status line lacks a status code
        b"HTTP/1.1 NOT_A_NUMBER OK\r\n\r\n",  # the status code is not numeric
    ],
)
async def test_http_rejects_malformed_status_line(raw: bytes) -> None:
    """A malformed status line → a functional error (not BLOCKED) is returned."""
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("http_request: ")
    assert "BLOCKED" not in result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_rejects_malformed_content_length() -> None:
    """A non-numeric content-length → malformed content-length."""
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: abc\r\n\r\nhello"
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert "malformed content-length" in result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
@pytest.mark.parametrize(
    "url, reason",
    [
        ("ftp://example.com/", "scheme not allowed"),
        ("example.com/path", "scheme not allowed"),  # no scheme
        ("http://", "no hostname"),
        ("http://user:pass@example.com/", "userinfo not allowed"),
        ("http://example.com:99999999999999999999/", "invalid URL"),  # port out of range
    ],
)
async def test_http_rejects_bad_urls(url: str, reason: str) -> None:
    """URL parse error branches: scheme/hostname/userinfo/port."""
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([])
    result = await _run(url, resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert reason in result.error
    assert connector.connections == []


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_connection_oserror() -> None:
    """A connection raising OSError → a structured error is returned (no propagation)."""

    class FailingConnector:
        async def __call__(
            self, ip: str, port: int, tls: bool, server_hostname: str | None
        ) -> tuple[FakeReader, FakeWriter]:
            raise OSError("connection refused")

    resolver = FakeResolver(["93.184.216.34"])
    result = await _run("http://example.com/", resolver=resolver, connector=FailingConnector())

    assert not result.ok
    assert "http_request: OSError: connection refused" in result.error
    assert "BLOCKED" not in result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hanging connection → a timeout error (TIMEOUT_SECONDS monkeypatched to 0.05s for speed)."""
    import asyncio

    monkeypatch.setattr(http_request, "TIMEOUT_SECONDS", 0.05)

    class HangingConnector:
        async def __call__(
            self, ip: str, port: int, tls: bool, server_hostname: str | None
        ) -> tuple[FakeReader, FakeWriter]:
            await asyncio.sleep(10)
            raise AssertionError("should be cancelled by timeout")

    resolver = FakeResolver(["93.184.216.34"])
    result = await _run("http://example.com/", resolver=resolver, connector=HangingConnector())

    assert not result.ok
    assert "timed out" in result.error
    assert "BLOCKED" not in result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_writer_cleanup_failure_ignored() -> None:
    """A failed connection cleanup (wait_closed) does not affect an already-obtained response."""

    class CleanupFailingWriter(FakeWriter):
        async def wait_closed(self) -> None:
            raise RuntimeError("already closed")

    class CleanupFailingConnector:
        def __init__(self) -> None:
            self.connections: list[tuple[str, int, bool, str | None]] = []

        async def __call__(
            self, ip: str, port: int, tls: bool, server_hostname: str | None
        ) -> tuple[FakeReader, CleanupFailingWriter]:
            self.connections.append((ip, port, tls, server_hostname))
            raw = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
            return FakeReader(raw), CleanupFailingWriter()

    connector = CleanupFailingConnector()
    resolver = FakeResolver(["93.184.216.34"])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert "body: ok" in result.result


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_empty_dns_result() -> None:
    """DNS resolution returning an empty list → BLOCKED."""

    class EmptyResolver:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, hostname: str, port: int) -> list[http_request.IPAddress]:
            self.calls += 1
            return []

    resolver = EmptyResolver()
    connector = RecordingConnector([])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("BLOCKED")
    assert "no addresses" in result.error
    assert connector.connections == []


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_rejects_malformed_chunk_size() -> None:
    """A non-hexadecimal chunked size line → malformed chunk size."""
    raw = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nhello\r\n0\r\n\r\n"
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert "malformed chunk size" in result.error
    assert "BLOCKED" not in result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_content_length_short_read() -> None:
    """content-length longer than the actual body → an early EOF interrupts; the bytes already read are still returned."""
    # declares 10 bytes, only 4 bytes arrive before the connection closes
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\npart"
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert "body: part" in result.result
    assert "truncated" not in result.result
