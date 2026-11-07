"""Own a FastMCP browser-login context in one task for its entire lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Protocol, SupportsFloat

from key_value.aio._utils.sanitization import AlwaysHashStrategy
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.stores.memory import MemoryStore


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


def create_oauth_client(
    url: str, *, token_store: MemoryStore | FileTreeStore,
) -> OAuthClient:
    """Explicit OAuth token backend; never persist credentials until opted in."""
    try:
        from fastmcp import Client
        from fastmcp.client.auth import OAuth
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Browser login needs fastmcp-slim[client]. Install the project's runtime requirements."
        ) from exc
    # TODO: Verify packaged Android/iOS browser callbacks on physical devices.
    return Client(
        url,
        auth=OAuth(mcp_url=url, token_storage=token_store),
        mode="legacy",
        timeout=30,
        init_timeout=330,
    )


def private_oauth_store(directory: Path) -> FileTreeStore:
    """OAuth secrets are local plaintext, guarded by private POSIX directories."""
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.parent.chmod(0o700)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    # FastMCP keys contain entire URLs; hashing prevents path separators,
    # traversal, and leaking endpoint/query secrets in filenames.
    return FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=AlwaysHashStrategy(),
    )


class OptInOAuthMemoryStore(MemoryStore):
    """Keep OAuth ephemeral until Save, then mirror refreshes immediately to DATA."""

    def __init__(self) -> None:
        super().__init__()
        self._disk: FileTreeStore | None = None

    def enable_disk(self, disk: FileTreeStore) -> None:
        self._disk = disk

    def disable_disk(self) -> None:
        self._disk = None

    async def put(
        self, key: str, value: Mapping[str, Any], *,
        collection: str | None = None, ttl: SupportsFloat | None = None,
    ) -> None:
        await super().put(key, value, collection=collection, ttl=ttl)
        if self._disk is not None:
            await self._disk.put(key, value, collection=collection, ttl=ttl)

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        deleted = await super().delete(key, collection=collection)
        if self._disk is not None:
            removed = await self._disk.delete(key, collection=collection)
            return deleted or removed
        return deleted


class BrowserOAuthClient:
    """Delegate OAuth, token refresh, and MCP requests to FastMCP."""

    def __init__(self, url: str, *, stored_tokens: Path | None = None) -> None:
        self.url = url
        # A brand-new login stays memory-only until Save is explicitly pressed.
        self._store: OptInOAuthMemoryStore | FileTreeStore = (
            private_oauth_store(stored_tokens) if stored_tokens is not None
            else OptInOAuthMemoryStore()
        )
        self._saved_directory = stored_tokens
        self._client: OAuthClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._error: Exception | None = None
        self._closed = False

    async def _run(self) -> None:
        try:
            async with create_oauth_client(self.url, token_store=self._store) as client:
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

    async def persist_credentials(self, directory: Path) -> None:
        """Copy FastMCP OAuth token, client registration and expiry to DATA.

        On a successful opt-in, existing in-memory tokens are copied to disk.
        Later renewals mirror to disk immediately, including rotated refresh
        tokens. Loaded profiles use their FileTreeStore directly.
        """
        from fastmcp.client.auth.oauth import TokenStorageAdapter

        if self._saved_directory == directory and isinstance(self._store, FileTreeStore):
            return
        source = TokenStorageAdapter(async_key_value=self._store, server_url=self.url)
        tokens = await source.get_tokens()
        if tokens is None:
            raise ValueError("No OAuth credentials available yet. Finish browser sign-in first.")
        destination_store = private_oauth_store(directory)
        dest = TokenStorageAdapter(async_key_value=destination_store, server_url=self.url)
        client_info = await source.get_client_info()
        if client_info is not None:
            await dest.set_client_info(client_info)
        await dest.set_tokens(tokens)
        expires_at = await source.get_token_expiry()
        if expires_at is not None:
            await destination_store.put(
                f"{self.url}/token_expiry",
                {"expires_at": expires_at},
                collection="mcp-oauth-token-expiry",
                ttl=365 * 24 * 60 * 60,
            )
        if isinstance(self._store, OptInOAuthMemoryStore):
            self._store.enable_disk(destination_store)
        self._saved_directory = directory

    async def close(self) -> None:
        self._closed = True
        self._stop.set()
        if self._task is not None:
            if not self._ready.is_set():
                self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if self._saved_directory is not None and isinstance(self._store, OptInOAuthMemoryStore):
            # Catch any provider writes that completed before mirroring was enabled.
            await self.persist_credentials(self._saved_directory)

    def stop_persisting(self) -> None:
        """Stop writing credentials immediately when a saved profile is deleted."""
        self._saved_directory = None
        if isinstance(self._store, OptInOAuthMemoryStore):
            self._store.disable_disk()
