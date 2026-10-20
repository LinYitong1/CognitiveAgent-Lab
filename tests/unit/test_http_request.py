"""M1-5 http_request 单元测试（契约 §3.2；-k tool_security 命中）。

不真正联网：FakeResolver + FakeConnector（reader/writer 假流）注入，
真实 GET 只测被阻断路径（安全校验逻辑全量覆盖）。
"""

from __future__ import annotations

import ipaddress
from typing import Any

import pytest

from src.config import Settings
from src.models.tool_result import ToolResult
from src.tools import http_request


class FakeResolver:
    """每次调用依次返回预设结果（模拟 rebinding：第二次与第一次不同）。"""

    def __init__(self, *results: list[str]) -> None:
        self._results = [list(r) for r in results]
        self.calls: list[tuple[str, int]] = []

    def __call__(self, hostname: str, port: int) -> list[http_request.IPAddress]:
        self.calls.append((hostname, port))
        index = min(len(self.calls) - 1, len(self._results) - 1)
        return [ipaddress.ip_address(item) for item in self._results[index]]


class FakeReader:
    """最小读取接口（http_request.Reader 协议的结构实现）。"""

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
    """最小写入接口（记录写入内容供断言）。"""

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
    """记录每次连接参数（IP/端口/TLS/SNI），按次返回预设原始响应。"""

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
    # resolve-then-connect 生效证据：连接目标 == 已校验 IP，且无二次解析
    assert len(resolver.calls) == 1
    ip, port, tls, sni = connector.connections[0]
    assert ip == "93.184.216.34"
    assert port == 443
    # HTTPS：SNI/证书校验以原域名进行（server_hostname 分离）
    assert tls is True
    assert sni == "example.com"
    # Host 头保留原域名
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
    assert connector.connections == []  # 未建连


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_cloud_metadata() -> None:
    # IP 字面量直填（进入白名单后由 IP 校验阻断——云元数据 169.254.169.254）
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
    assert resolver.calls == []  # 白名单先于 DNS


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_blocks_mixed_dns_records() -> None:
    resolver = FakeResolver(["93.184.216.34", "10.0.0.1"])  # 多记录含私有 → 整条拒绝
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
    assert len(connector.connections) == 1  # 第二跳未建连（重新走完整链路时被拒）


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
    # 初始请求 + 3 跳 = 4 次连接，之后超限
    assert len(connector.connections) == 4


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_dns_rebinding_fake_resolver() -> None:
    # 第一次解析公网、第二次私有——若实现存在二次解析（TOCTOU）将得逞
    resolver = FakeResolver(["93.184.216.34"], ["10.0.0.1"])
    connector = RecordingConnector([_response(200, b"stable")])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert len(resolver.calls) == 1  # 仅解析一次
    assert connector.connections[0][0] == "93.184.216.34"  # 连接 IP == 首次校验值


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_response_size_truncation() -> None:
    body = b"x" * (http_request.MAX_BODY_BYTES + 100)
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([_response(200, body)])
    result = await _run("http://example.com/big", resolver=resolver, connector=connector)

    assert result.ok
    assert "truncated: true" in result.result
    # body 截断到 1MB
    body_line = next(line for line in result.result.splitlines() if line.startswith("body: "))
    assert len(body_line) == len("body: ") + http_request.MAX_BODY_BYTES


@pytest.mark.tool_security
def test_http_idempotency_declarations() -> None:
    """幂等性声明与调用级覆写（ARCHITECTURE §6.4；M2 恢复语义的快照依据）。"""
    from src.tools import calc, file_write

    settings = Settings()
    assert calc.build_tool_spec(settings).idempotency == "idempotent"
    assert file_write.build_tool_spec(settings).idempotency == "non-idempotent"

    http_spec = http_request.build_tool_spec(settings)
    assert http_spec.idempotency == "non-idempotent"
    assert http_spec.effective_idempotency({"method": "GET"}) == "idempotent"  # GET 覆写
    assert http_spec.effective_idempotency({}) == "idempotent"  # 缺省 method 即 GET
    assert http_spec.effective_idempotency({"method": "POST"}) == "non-idempotent"


# ---------------------------------------------------------------------------
# G-2 退回补测（qa-M1.md §三）：chunked / EOF / 畸形响应 / URL 错误 / 连接异常 / 超时
# ---------------------------------------------------------------------------


def _chunked_payload(chunks: list[bytes]) -> bytes:
    """构造 chunked 编码的响应体字节流。"""
    return b"".join(b"%x\r\n%s\r\n" % (len(chunk), chunk) for chunk in chunks) + b"0\r\n\r\n"


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_reads_chunked_body() -> None:
    """chunked 传输编码：多 chunk 正常拼接，无截断。"""
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
    """chunked 超 1MB：截断至 1MB 并标注 truncated。"""
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
    """无 content-length / transfer-encoding：读至连接 EOF；请求行携带 path?query。"""
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nno length headers here"
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/path?q=1", resolver=resolver, connector=connector)

    assert result.ok
    assert "body: no length headers here" in result.result
    assert "truncated" not in result.result
    # 请求行含完整 path?query（L153 分支）
    assert b"GET /path?q=1 HTTP/1.1\r\n" in connector.writers[0].written[0]


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_eof_truncation() -> None:
    """EOF 模式超 1MB：截断至 1MB 并标注 truncated。"""
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
        b"",  # 空响应
        b"GARBAGE\r\n\r\n",  # 状态行缺状态码
        b"HTTP/1.1 NOT_A_NUMBER OK\r\n\r\n",  # 状态码非数字
    ],
)
async def test_http_rejects_malformed_status_line(raw: bytes) -> None:
    """畸形状态行 → 功能错误（非 BLOCKED）回传。"""
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert not result.ok
    assert result.error.startswith("http_request: ")
    assert "BLOCKED" not in result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_http_rejects_malformed_content_length() -> None:
    """content-length 非数字 → malformed content-length。"""
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
        ("example.com/path", "scheme not allowed"),  # 无 scheme
        ("http://", "no hostname"),
        ("http://user:pass@example.com/", "userinfo not allowed"),
        ("http://example.com:99999999999999999999/", "invalid URL"),  # 端口超范围
    ],
)
async def test_http_rejects_bad_urls(url: str, reason: str) -> None:
    """URL 解析错误分支：scheme/hostname/userinfo/端口。"""
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
    """连接抛 OSError → 结构化错误回传（不外抛）。"""

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
    """连接挂起 → 超时错误（TIMEOUT_SECONDS monkeypatch 为 0.05s 加速）。"""
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
    """连接清理（wait_closed）失败不影响已有响应结果。"""

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
    """DNS 解析返回空列表 → BLOCKED。"""

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
    """chunked size 行非十六进制 → malformed chunk size。"""
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
    """content-length 声明长于实际 body → 提前 EOF 中断，已读部分仍返回。"""
    # 声明 10 字节，实际只有 4 字节即连接关闭
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\npart"
    resolver = FakeResolver(["93.184.216.34"])
    connector = RecordingConnector([raw])
    result = await _run("http://example.com/", resolver=resolver, connector=connector)

    assert result.ok
    assert "body: part" in result.result
    assert "truncated" not in result.result
