"""No external requests: all transport calls go through HTTPX MockTransport."""

import asyncio
import json

import httpx
import pytest

from transport import McpError, McpSession, validate_endpoint


@pytest.mark.parametrize("endpoint", [
    "", "file:///etc/passwd", "not-a-url", "https://a:b@host/mcp",
    "https://example.com/mcp#fragment", "http://localhost:0/mcp",
])
def test_rejects_invalid_urls(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_accepts_standard_endpoint() -> None:
    assert validate_endpoint(" https://example.net/mcp ") == "https://example.net/mcp"


async def _async_test_handshake_discovery_paginated_execution_and_close() -> None:
    requests: list[tuple[str, dict[str, object], httpx.Headers]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            assert request.headers.get("Mcp-Session-Id") == "test-session"
            return httpx.Response(204)
        body = json.loads(request.content)
        assert isinstance(body, dict)
        method = str(body["method"])
        requests.append((method, body, request.headers))
        if method == "notifications/initialized":
            assert "id" not in body
            assert request.headers.get("Mcp-Session-Id") == "test-session"
            return httpx.Response(202)
        result: dict[str, object]
        if method == "initialize":
            assert body["params"]["capabilities"] == {}
            result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "Mock"},
                      "capabilities": {"tools": {}, "prompts": {}, "resources": {}}}
        elif method == "tools/list":
            if body["params"].get("cursor"):
                result = {"tools": [{"name": "two"}]}
            else:
                result = {"tools": [{"name": "one"}], "nextCursor": "page-2"}
        elif method == "tools/call":
            assert body["params"]["arguments"] == {"q": "hello"}
            assert request.headers.get("Mcp-Name") == "one"
            assert request.headers.get("MCP-Protocol-Version") == "2025-06-18"
            result = {"content": [{"type": "text", "text": "hello"}]}
        elif method == "prompts/get":
            result = {"messages": [{"role": "user", "content": {"type": "text", "text": "ok"}}]}
        elif method == "resources/read":
            assert request.headers.get("Mcp-Name") == "file:///readme"
            result = {"contents": [{"uri": "file:///readme", "text": "Read me"}]}
        else:
            raise AssertionError(f"Unexpected method {method}")
        headers = {"Mcp-Session-Id": "test-session"} if method == "initialize" else {}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result},
                              headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        session = McpSession("https://example.net/mcp", "secret", client=client)
        info = await session.initialize()
        assert info["serverInfo"] == {"name": "Mock"}
        assert [item["name"] for item in await session.list_items("tools/list", "tools")] == ["one", "two"]
        assert (await session.call_tool("one", {"q": "hello"}))["content"] == [
            {"type": "text", "text": "hello"}
        ]
        assert "messages" in await session.get_prompt("demo", {})
        assert "contents" in await session.read_resource("file:///readme")
        assert len(session.events) >= 10
        assert "secret" not in "".join(event.payload for event in session.events)
        assert all(headers.get("Authorization") == "Bearer secret" for _, _, headers in requests)
        await session.close()
        with pytest.raises(McpError, match="closed"):
            await session.call_tool("one", {})


async def _async_test_streamable_sse_response_keeps_notifications_and_result() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)
        if message["method"] == "notifications/initialized":
            return httpx.Response(202)
        if message["method"] == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})
        sse = (
            'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":1}}\n\n'
            + 'event: message\ndata: '
            + json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": []}})
            + "\n\n"
        )
        return httpx.Response(200, text=sse, headers={"Content-Type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        session = McpSession("http://localhost:9999/mcp", client=client)
        await session.initialize()
        assert await session.list_items("tools/list", "tools") == []
        assert any(event.direction == "← event" for event in session.events)
        await session.close()


async def _async_test_jsonrpc_error_is_not_reported_as_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        msg = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"],
                                         "error": {"code": -32601, "message": "unknown method"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        session = McpSession("https://example.org/mcp", client=client)
        with pytest.raises(McpError, match="unknown method"):
            await session.list_items("tools/list", "tools")
        await session.close()


async def _async_test_pagination_refuses_repeated_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        msg = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"],
                                         "result": {"tools": [], "nextCursor": "repeat"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        session = McpSession("https://example.org/mcp", client=client)
        with pytest.raises(McpError, match="repeated"):
            await session.list_items("tools/list", "tools")
        await session.close()


def test_handshake_discovery_paginated_execution_and_close() -> None:
    asyncio.run(_async_test_handshake_discovery_paginated_execution_and_close())


def test_streamable_sse_response_keeps_notifications_and_result() -> None:
    asyncio.run(_async_test_streamable_sse_response_keeps_notifications_and_result())


def test_jsonrpc_error_is_not_reported_as_success() -> None:
    asyncio.run(_async_test_jsonrpc_error_is_not_reported_as_success())


def test_pagination_refuses_repeated_cursor() -> None:
    asyncio.run(_async_test_pagination_refuses_repeated_cursor())


def test_protocol_log_frames_are_bounded() -> None:
    session = McpSession("https://example.org/mcp")
    session._record("←", "tool", {"data": "x" * 50000})
    assert len(session.events[0].payload) < 17000
    assert "truncated" in session.events[0].payload
