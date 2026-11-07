"""Offline lifecycle/adapter tests; these do not prove a real browser login."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Literal

import pytest

import oauth_client
from oauth_client import BrowserOAuthClient
import transport
from transport import McpError, McpSession


class Result:
    def __init__(self, data: dict[str, object]) -> None:
        self.data = data

    def model_dump(
        self, *, mode: Literal["json"], by_alias: bool, exclude_none: bool,
    ) -> dict[str, object]:
        assert mode == "json" and by_alias and exclude_none
        return self.data


class StubClient:
    def __init__(self) -> None:
        self.initialize_result: Result | None = Result({
            "protocolVersion": "2025-11-25", "serverInfo": {"name": "OAuth test"},
            "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
        })
        self.calls: list[tuple[str, object]] = []
        self.enter_task: asyncio.Task[object] | None = None
        self.exit_task: asyncio.Task[object] | None = None
        self.gate: asyncio.Event | None = None
        self.started = asyncio.Event()
        self.error: Exception | None = None
        self.cancelled = False
        self.exits = 0

    async def __aenter__(self) -> StubClient:
        self.enter_task = asyncio.current_task()
        self.started.set()
        if self.error is not None:
            raise self.error
        if self.gate is not None:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_task = asyncio.current_task()
        self.exits += 1

    async def list_tools_mcp(self, *, cursor: str | None = None) -> Result:
        self.calls.append(("tools/list", cursor))
        return Result({"tools": [{"name": "second" if cursor else "first"}],
                       **({} if cursor else {"nextCursor": "page-2"})})

    async def list_prompts_mcp(self, *, cursor: str | None = None) -> Result:
        self.calls.append(("prompts/list", cursor))
        return Result({"prompts": [{"name": "example"}]})

    async def list_resources_mcp(self, *, cursor: str | None = None) -> Result:
        self.calls.append(("resources/list", cursor))
        return Result({"resources": [{"uri": "file:///readme"}]})

    async def list_resource_templates_mcp(self, *, cursor: str | None = None) -> Result:
        self.calls.append(("resources/templates/list", cursor))
        return Result({"resourceTemplates": [{"uriTemplate": "file:///{path}"}]})

    async def call_tool_mcp(self, name: str, arguments: dict[str, object]) -> Result:
        self.calls.append(("tools/call", (name, arguments)))
        return Result({"content": [{"type": "text", "text": "Hello"}], "isError": True})

    async def get_prompt_mcp(self, name: str, arguments: dict[str, object]) -> Result:
        self.calls.append(("prompts/get", (name, arguments)))
        return Result({"messages": [{"role": "user", "content": {"type": "text", "text": "Hi"}}]})

    async def read_resource_mcp(self, uri: str) -> Result:
        self.calls.append(("resources/read", uri))
        return Result({"contents": [{"uri": uri, "text": "Readme"}]})


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> StubClient:
    client = StubClient()

    def create(url: str) -> StubClient:
        assert url == "https://example.net/mcp"
        return client

    monkeypatch.setattr(oauth_client, "create_oauth_client", create)
    return client


@pytest.mark.parametrize(("method", "params", "key"), [
    ("tools/list", {}, "tools"),
    ("prompts/list", {}, "prompts"),
    ("resources/list", {}, "resources"),
    ("resources/templates/list", {}, "resourceTemplates"),
    ("tools/call", {"name": "echo", "arguments": {"message": "hello"}}, "content"),
    ("prompts/get", {"name": "example", "arguments": {"topic": "Python"}}, "messages"),
    ("resources/read", {"uri": "file:///readme"}, "contents"),
])
def test_oauth_requests_keep_wire_result_shapes(
    sdk: StubClient, method: str, params: dict[str, object], key: str,
) -> None:
    async def exercise() -> None:
        client = BrowserOAuthClient("https://example.net/mcp")
        try:
            result = await client.request("initialize", None)
            assert result["serverInfo"] == {"name": "OAuth test"}
            assert sdk.calls == []
            assert key in await client.request(method, params)
            assert sdk.calls[-1][0] == method
        finally:
            await client.close()
        assert sdk.enter_task is sdk.exit_task
        assert sdk.exits == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(("method", "params"), [
    ("tools/list", {"cursor": 12}),
    ("tools/call", {"name": "echo", "arguments": []}),
    ("tools/call", {"arguments": {}}),
    ("prompts/get", {"name": "example", "arguments": None}),
    ("resources/read", {"uri": 12}),
    ("not/a/method", {}),
])
def test_invalid_oauth_requests_stop_before_calling_sdk(
    sdk: StubClient, method: str, params: dict[str, object],
) -> None:
    async def exercise() -> None:
        client = BrowserOAuthClient("https://example.net/mcp")
        try:
            await client.request("initialize", None)
            with pytest.raises(ValueError):
                await client.request(method, params)
            assert sdk.calls == []
        finally:
            await client.close()

    asyncio.run(exercise())


def test_oauth_adapter_preserves_pagination_logs_and_remote_tool_errors(sdk: StubClient) -> None:
    async def exercise() -> None:
        session = McpSession("https://example.net/mcp", "unused-bearer", oauth=True)
        try:
            await session.initialize()
            tools = await session.list_items("tools/list", "tools")
            assert [item["name"] for item in tools] == ["first", "second"]
            assert sdk.calls == [("tools/list", None), ("tools/list", "page-2")]
            assert (await session.call_tool("echo", {}))["isError"] is True
            assert "messages" in await session.get_prompt("example", {})
            assert "contents" in await session.read_resource("file:///readme")
            assert "Authorization" not in session._headers("tools/list", {})
            assert "unused-bearer" not in "".join(event.payload for event in session.events)
            assert len(session.events) >= 10
        finally:
            await session.close()
        await session.close()
        assert sdk.exits == 1
        with pytest.raises(McpError, match="closed"):
            await session.call_tool("echo", {})

    asyncio.run(exercise())


def test_oauth_reply_size_limit_remains_enforced(sdk: StubClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        session = McpSession("https://example.net/mcp", oauth=True)
        try:
            await session.initialize()
            monkeypatch.setattr(transport, "MAX_REPLY_BYTES", 10)
            with pytest.raises(McpError, match="8 MB"):
                await session.call_tool("echo", {})
        finally:
            await session.close()

    asyncio.run(exercise())


def test_sdk_connection_failures_are_reported_and_cleaned_up(sdk: StubClient) -> None:
    sdk.error = RuntimeError("Authorization denied")

    async def exercise() -> None:
        client = BrowserOAuthClient("https://example.net/mcp")
        with pytest.raises(RuntimeError, match="Authorization denied"):
            await client.request("initialize", None)
        await client.close()
        assert sdk.exits == 0  # Entering the context failed.

    asyncio.run(exercise())


def test_close_interrupts_pending_authorization(sdk: StubClient) -> None:
    async def exercise() -> None:
        sdk.gate = asyncio.Event()
        client = BrowserOAuthClient("https://example.net/mcp")
        request = asyncio.create_task(client.request("initialize", None))
        await asyncio.wait_for(sdk.started.wait(), timeout=1)
        await client.close()
        with pytest.raises(RuntimeError, match="closed"):
            await request
        assert sdk.cancelled

    asyncio.run(exercise())


def test_cancelling_initialize_cleans_up_its_owner_task(sdk: StubClient) -> None:
    async def exercise() -> None:
        sdk.gate = asyncio.Event()
        client = BrowserOAuthClient("https://example.net/mcp")
        request = asyncio.create_task(client.request("initialize", None))
        await asyncio.wait_for(sdk.started.wait(), timeout=1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert sdk.cancelled
        await client.close()

    asyncio.run(exercise())


def test_missing_initialization_result_is_an_error(sdk: StubClient) -> None:
    sdk.initialize_result = None

    async def exercise() -> None:
        client = BrowserOAuthClient("https://example.net/mcp")
        try:
            with pytest.raises(RuntimeError, match="did not complete"):
                await client.request("initialize", None)
        finally:
            await client.close()
        assert sdk.exits == 1

    asyncio.run(exercise())


def test_requests_require_initialization_and_cannot_restart_closed_clients(sdk: StubClient) -> None:
    async def exercise() -> None:
        client = BrowserOAuthClient("https://example.net/mcp")
        with pytest.raises(RuntimeError, match="not connected"):
            await client.request("tools/list", {})
        await client.close()
        with pytest.raises(RuntimeError, match="closed"):
            await client.request("initialize", None)
        assert sdk.enter_task is None

    asyncio.run(exercise())
