"""Connected Flet UI: real controls, fake MCP transport, no network or tools on connect."""

import asyncio
from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import cast

import flet as ft
import pytest

import app as app_module


class FakePage:
    """Capture widget updates and schedule callbacks without opening a window."""

    def __init__(self) -> None:
        self.window = SimpleNamespace()
        self.services: list[ft.Control] = []
        self.controls: list[ft.Control] = []
        self.scroll: ft.ScrollMode | None = None
        self.appbar: ft.AppBar | None = None
        self.title = ""

        self.tasks: list[asyncio.Task[None]] = []

    def add(self, control: ft.Control) -> None:
        self.controls.append(control)

    def update(self) -> None:
        """Avoid a GUI backend; the actual tree remains inspectable."""

    def run_task(
        self, handler: Callable[..., Coroutine[object, object, None]], *args: object
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(handler(*args))
        self.tasks.append(task)
        return task


class StubMcpSession:
    instances: list["StubMcpSession"] = []

    def __init__(self, url: str, bearer: str) -> None:
        self.url = url
        self.bearer = bearer
        self.capabilities: dict[str, object] = {"tools": {}, "prompts": {}, "resources": {}}
        self.server_info: dict[str, object] = {"name": "Isolated fake MCP"}
        self.version = "2025-11-25"
        self.events: list[object] = []
        self.tool_calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False
        self.instances.append(self)

    async def initialize(self) -> dict[str, object]:
        return {"serverInfo": self.server_info}

    async def list_items(self, method: str, collection: str) -> list[dict[str, object]]:
        if method == "tools/list":
            return [{
                "name": "inspect_status",
                "description": "Read a local fake status",
                "inputSchema": {
                    "type": "object",
                    "required": ["target"],
                    "properties": {
                        "target": {"type": "string", "default": "fake-machine"},
                    },
                },
            }]
        if method == "prompts/list":
            return [{"name": "sample_prompt"}]
        if method == "resources/list":
            return [{"uri": "file:///readme"}]
        return []

    async def call_tool(self, name: str, args: dict[str, object]) -> dict[str, object]:
        self.tool_calls.append((name, args))
        return {"content": [{"type": "text", "text": "hello from mock"}]}

    async def close(self) -> None:
        self.closed = True


async def _exercise_connected_ui() -> None:
    page = FakePage()
    app_module.main(cast(ft.Page, page))
    root = cast(ft.Column, page.controls[0])
    connection = cast(ft.Column, cast(ft.Container, root.controls[1]).content)
    endpoint = cast(ft.TextField, connection.controls[1])
    endpoint.value = "http://127.0.0.1:7777/mcp"
    actions = cast(ft.Row, connection.controls[3])
    connect = cast(ft.FilledTonalButton, actions.controls[0])
    assert connect.on_click is not None
    cast(Callable[[], None], connect.on_click)()
    await asyncio.gather(*page.tasks)

    stub = StubMcpSession.instances[-1]
    assert stub.url == endpoint.value
    assert stub.tool_calls == []  # Discovery must never execute a tool.

    workspace = cast(ft.ResponsiveRow, root.controls[-1])
    assert workspace.visible
    summary = cast(ft.Row, root.controls[3])
    assert summary.visible and len(summary.controls) == 3
    navigation = cast(ft.Row, root.controls[4])
    assert len(navigation.controls) == 4

    right = cast(ft.Container, workspace.controls[1])
    detail_panel = cast(ft.Container, right.content)
    detail = cast(ft.Column, detail_panel.content)
    action_row = cast(ft.Row, detail.controls[6])
    run = cast(ft.FilledButton, action_row.controls[0])
    assert run.on_click is not None
    cast(Callable[[], None], run.on_click)()
    await asyncio.gather(*page.tasks)
    assert stub.tool_calls == [("inspect_status", {"target": "fake-machine"})]
    feedback = cast(ft.Text, action_row.controls[1])
    assert feedback.value.startswith("Completed")


def test_connected_workspaces_stay_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    StubMcpSession.instances.clear()
    monkeypatch.setattr(app_module, "McpSession", StubMcpSession)
    asyncio.run(_exercise_connected_ui())
