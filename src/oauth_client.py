"""Own a FastMCP browser-login context in one task for its entire lifetime."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from types import TracebackType
from typing import Literal, Protocol


class WireResult(Protocol):
    def model_dump(
        self, *, mode: Literal["json"], by_alias: bool, exclude_none: bool,
    ) -> dict[str, object]: ...


class OAuthClient(Protocol):
    """The FastMCP operations used here; also the boundary for offline tests."""

    @property
    def initialize_result(self) -> WireResult | None: ...

    async def __aenter__(self) -> OAuthClient: ...
    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        traceback: TracebackType | None, /,
    ) -> bool | None: ...
    async def list_tools_mcp(self, *, cursor: str | None = None) -> WireResult: ...
    async def list_prompts_mcp(self, *, cursor: str | None = None) -> WireResult: ...
    async def list_resources_mcp(self, *, cursor: str | None = None) -> WireResult: ...
    async def list_resource_templates_mcp(self, *, cursor: str | None = None) -> WireResult: ...
    async def call_tool_mcp(self, name: str, arguments: dict[str, object]) -> WireResult: ...
    async def get_prompt_mcp(self, name: str, arguments: dict[str, object]) -> WireResult: ...
    async def read_resource_mcp(self, uri: str) -> WireResult: ...


def create_oauth_client(url: str) -> OAuthClient:
    """Load the client only for browser login; public/bearer connections stay light."""
    try:
        from fastmcp import Client
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Browser login needs fastmcp-slim[client]. Install the project's runtime requirements."
        ) from exc
    # TODO: Verify packaged Android/iOS browser callbacks on physical devices.
    return Client(url, auth="oauth", mode="legacy", timeout=30, init_timeout=330)


class BrowserOAuthClient:
    """Delegate OAuth, token refresh, and MCP requests to FastMCP."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._client: OAuthClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._error: Exception | None = None
        self._closed = False

    async def _run(self) -> None:
        try:
            async with create_oauth_client(self.url) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except Exception as exc:
            self._error = exc
        finally:
            self._client = None
            self._ready.set()

    async def request(self, method: str, params: dict[str, object] | None) -> dict[str, object]:
        if self._closed:
            raise RuntimeError("Browser login session is closed.")
        if method == "initialize":
            if self._task is None:
                self._task = asyncio.create_task(self._run())
            try:
                await self._ready.wait()
            except asyncio.CancelledError:
                await self.close()
                raise
        if self._closed:
            raise RuntimeError("Browser login session is closed.")
        if self._error is not None:
            raise self._error
        client = self._client
        if client is None:
            raise RuntimeError("Browser login session is not connected.")
        arguments = params or {}
        listings = {
            "tools/list": client.list_tools_mcp,
            "prompts/list": client.list_prompts_mcp,
            "resources/list": client.list_resources_mcp,
            "resources/templates/list": client.list_resource_templates_mcp,
        }
        result: WireResult | None
        if method == "initialize":
            result = client.initialize_result
        elif method in listings:
            cursor = arguments.get("cursor")
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError("Pagination cursor must be a string.")
            result = await listings[method](cursor=cursor)
        elif method in {"tools/call", "prompts/get"}:
            name = arguments.get("name")
            values = arguments.get("arguments")
            if not isinstance(name, str) or not isinstance(values, dict):
                raise ValueError("MCP calls need a name and an arguments object.")
            if method == "tools/call":
                result = await client.call_tool_mcp(name, values)
            else:
                result = await client.get_prompt_mcp(name, values)
        elif method == "resources/read":
            uri = arguments.get("uri")
            if not isinstance(uri, str):
                raise ValueError("Resource URI must be a string.")
            result = await client.read_resource_mcp(uri)
        else:
            raise ValueError(f"Unsupported MCP method: {method}")
        if result is None:
            raise RuntimeError("The server did not complete MCP initialization.")
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def close(self) -> None:
        self._closed = True
        self._stop.set()
        if self._task is not None:
            if not self._ready.is_set():
                self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
