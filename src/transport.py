"""Small Streamable HTTP MCP client with inspectable JSON-RPC traffic.

Supports the established 2025-11-25 protocol and negotiates older compatible
versions. This is not a general replacement for the full Python MCP SDK.
"""

import base64
from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx

from oauth_client import BrowserOAuthClient

PROTOCOL_VERSION = "2025-11-25"
MAX_REPLY_BYTES = 8_000_000
MAX_EVENTS = 2_000
MAX_PAGES = 100
MAX_LOG_FRAME = 16_000


class McpError(RuntimeError):
    """HTTP transport, JSON-RPC, or MCP protocol failure."""


def validate_endpoint(raw: str) -> str:
    """Require an absolute HTTP(S) endpoint without URL credentials."""
    url = raw.strip()
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.port == 0
        ):
            raise ValueError
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTP(S) MCP URL without credentials or a fragment.") from exc
    return url


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise McpError(f"{label} must be a JSON object.")
    return value


def _ascii_header(value: str) -> str:
    if value.isascii() and all(32 <= ord(ch) < 127 for ch in value):
        return value
    return "base64:" + base64.b64encode(value.encode("utf-8")).decode("ascii")


@dataclass(frozen=True)
class RpcEvent:
    when: str
    direction: str
    method: str
    payload: str


class McpSession:
    """One manually controlled remote MCP session; no server is launched locally."""

    def __init__(
        self, url: str, token: str = "", *, client: httpx.AsyncClient | None = None,
        oauth: bool = False,
        oauth_store_path: Path | None = None,
    ):
        self.url = validate_endpoint(url)
        if oauth and client is not None:
            raise ValueError("Browser OAuth cannot use a custom HTTPX client.")
        self._oauth = (
            BrowserOAuthClient(self.url, stored_tokens=oauth_store_path)
            if oauth else None
        )
        self._owned_client = client is None
        self._client = None if oauth else (
            client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        )
        self._token = "" if oauth else token.strip()
        self._session_id: str | None = None
        self.version: str | None = None
        self.server_info: dict[str, object] = {}
        self.capabilities: dict[str, object] = {}
        self.events: list[RpcEvent] = []
        self._serial = 0
        self._closed = False

    def _record(self, direction: str, method: str, payload: object) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if len(serialized) > MAX_LOG_FRAME:
            serialized = serialized[:MAX_LOG_FRAME] + "\n... [Protocol log frame truncated]"
        self.events.append(RpcEvent(time.strftime("%H:%M:%S"), direction, method, serialized))
        if len(self.events) > 250:
            del self.events[: len(self.events) - 250]

    def _headers(self, method: str, params: dict[str, object] | None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Mcp-Method": method,
        }
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if method in {"tools/call", "prompts/get", "resources/read"} and params:
            key = "uri" if method == "resources/read" else "name"
            name = params.get(key)
            if isinstance(name, str):
                headers["Mcp-Name"] = _ascii_header(name)
        return headers

    def _unwrap(self, payload: object, request_id: int, method: str) -> dict[str, object]:
        message = _object(payload, "JSON-RPC response")
        if message.get("jsonrpc") != "2.0" or message.get("id") != request_id:
            raise McpError(f"Invalid JSON-RPC response id for {method}.")
        self._record("←", method, message)
        if "error" in message:
            error = message["error"]
            raise McpError(f"{method}: {json.dumps(error, ensure_ascii=False)}")
        return _object(message.get("result"), f"{method} result")

    async def _sse_result(
        self, lines: AsyncIterator[str], request_id: int, method: str
    ) -> dict[str, object]:
        data: list[str] = []
        count = 0
        size = 0
        async for line in lines:
            size += len(line.encode("utf-8"))
            if size > MAX_REPLY_BYTES:
                raise McpError("MCP SSE reply exceeded the 8 MB safety limit.")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line:
                if not data:
                    continue
                count += 1
                if count > MAX_EVENTS:
                    raise McpError("MCP SSE reply contained too many events.")
                try:
                    payload: object = json.loads("\n".join(data))
                except json.JSONDecodeError as exc:
                    raise McpError("Malformed JSON in MCP SSE event.") from exc
                data.clear()
                message = _object(payload, "SSE event")
                if message.get("id") == request_id:
                    return self._unwrap(message, request_id, method)
                self._record("← event", method, message)
                if "id" in message and "method" in message:
                    raise McpError("Server-requested interaction is not supported by this client.")
        raise McpError(f"MCP SSE stream ended before the response to {method}.")

    async def _post(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        if self._closed:
            raise McpError("MCP session is closed.")
        self._serial += 1
        request_id = self._serial
        message: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._record("→", method, message)
        if self._oauth is not None:
            result = await self._oauth.request(method, params)
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_REPLY_BYTES:
                raise McpError("MCP reply exceeded the 8 MB safety limit.")
            return self._unwrap({"jsonrpc": "2.0", "id": request_id, "result": result}, request_id, method)
        client = self._client
        if client is None:
            raise McpError("MCP HTTP client is not available.")
        try:
            async with client.stream(
                "POST", self.url, headers=self._headers(method, params), json=message
            ) as response:
                response.raise_for_status()
                if method == "initialize":
                    sid = response.headers.get("Mcp-Session-Id")
                    if sid:
                        self._session_id = sid
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type == "text/event-stream":
                    return await self._sse_result(response.aiter_lines(), request_id, method)
                if content_type != "application/json":
                    raise McpError(f"Unsupported MCP response media type: {content_type or 'missing'}.")
                if response.headers.get("content-length", "").isdecimal():
                    if int(response.headers["content-length"]) > MAX_REPLY_BYTES:
                        raise McpError("MCP reply exceeded the 8 MB safety limit.")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_REPLY_BYTES:
                        raise McpError("MCP reply exceeded the 8 MB safety limit.")
                try:
                    return self._unwrap(json.loads(raw), request_id, method)
                except json.JSONDecodeError as exc:
                    raise McpError("Server returned invalid JSON.") from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise McpError(f"HTTP {code} while calling {method}.") from exc
        except httpx.RequestError as exc:
            raise McpError(f"Network error while calling {method}: {exc}") from exc

    async def _notify_initialized(self) -> None:
        if self._oauth is not None:
            return  # FastMCP has already completed the handshake and notification.
        message = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self._record("→", "notifications/initialized", message)
        client = self._client
        if client is None:
            raise McpError("MCP HTTP client is not available.")
        try:
            async with client.stream(
                "POST", self.url, json=message,
                headers=self._headers("notifications/initialized", None),
            ) as response:
                response.raise_for_status()
                if response.status_code != 202:
                    self._record("←", "notifications/initialized", {"status": response.status_code})
        except httpx.HTTPError as exc:
            raise McpError(f"Could not finish MCP handshake: {exc}") from exc

    async def initialize(self) -> dict[str, object]:
        result = await self._post("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcp-user-ui", "version": "0.1.0"},
        })
        version = result.get("protocolVersion")
        if not isinstance(version, str) or not version:
            raise McpError("Server did not negotiate an MCP protocol version.")
        self.version = version
        self.server_info = _object(result.get("serverInfo", {}), "Server information")
        self.capabilities = _object(result.get("capabilities", {}), "Server capabilities")
        await self._notify_initialized()
        return result

    async def list_items(self, method: str, collection: str) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            params: dict[str, object] = {"cursor": cursor} if cursor else {}
            reply = await self._post(method, params)
            items = reply.get(collection)
            if not isinstance(items, list):
                raise McpError(f"{method} returned no valid '{collection}' array.")
            entries.extend(_object(item, collection + " item") for item in items)
            next_cursor = reply.get("nextCursor")
            if not next_cursor:
                return entries
            if not isinstance(next_cursor, str) or next_cursor in seen:
                raise McpError(f"{method} returned a repeated or invalid pagination cursor.")
            cursor = next_cursor
            seen.add(cursor)
        raise McpError(f"{method} exceeded the {MAX_PAGES}-page limit.")

    async def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return await self._post("tools/call", {"name": name, "arguments": arguments})

    async def get_prompt(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return await self._post("prompts/get", {"name": name, "arguments": arguments})

    async def read_resource(self, uri: str) -> dict[str, object]:
        return await self._post("resources/read", {"uri": uri})

    async def save_oauth_credentials(self, directory: Path) -> None:
        if self._oauth is None:
            raise ValueError("This connection does not use browser OAuth.")
        await self._oauth.persist_credentials(directory)

    def stop_oauth_persistence(self) -> None:
        if self._oauth is not None:
            self._oauth.stop_persisting()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._oauth is not None:
            await self._oauth.close()
        if self._session_id and self._client is not None:
            try:
                await self._client.delete(self.url, headers=self._headers("DELETE", None), timeout=5)
            except httpx.HTTPError:
                pass
        if self._owned_client and self._client is not None:
            await self._client.aclose()
        self._token = ""
