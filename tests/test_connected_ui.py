"""Connected Flet UI: real controls, fake MCP transport, no network or tools on connect."""

import asyncio
from collections.abc import Callable
import json
from typing import cast

import flet as ft
import pytest

import app as app_module
from tests.ui_helpers import FakePage, find_control, select_screen, walk_controls
from transport import RpcEvent
from ui_theme import PALETTES

Catalog = dict[str, list[dict[str, object]]]


class StubMcpSession:
    instances: list["StubMcpSession"] = []

    def __init__(self, url: str, bearer: str, *, oauth: bool = False) -> None:
        self.url = url
        self.bearer = bearer
        self.oauth = oauth
        self.capabilities: dict[str, object] = {"tools": {}, "prompts": {}, "resources": {}}
        self.server_info: dict[str, object] = {"name": "Isolated fake MCP"}
        self.version = "2025-11-25"
        self.events: list[RpcEvent] = []
        self.tool_calls: list[tuple[str, dict[str, object]]] = []
        self.prompt_calls: list[tuple[str, dict[str, object]]] = []
        self.resource_reads: list[str] = []
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

    async def get_prompt(self, name: str, args: dict[str, object]) -> dict[str, object]:
        self.prompt_calls.append((name, args))
        return {"messages": [{"role": "user", "content": {"type": "text", "text": "Prompt"}}]}

    async def read_resource(self, uri: str) -> dict[str, object]:
        self.resource_reads.append(uri)
        return {"contents": [{"uri": uri, "text": "Resource"}]}

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def isolate_session(monkeypatch: pytest.MonkeyPatch) -> None:
    StubMcpSession.instances.clear()
    monkeypatch.setattr(app_module, "McpSession", StubMcpSession)


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> Catalog:
    items: Catalog = {
        "tools/list": [
            {"name": "Alpha", "description": "First tool"},
            {"name": "Straße", "description": "Second tool"},
            {"name": "Duplicate", "description": "First duplicate"},
            {"name": "Duplicate", "description": "Second duplicate"},
        ],
        "prompts/list": [{"name": "Sample", "arguments": [{"name": "topic", "required": True}]}],
        "resources/list": [{"name": "Readme", "uri": "file:///readme"}],
        "resources/templates/list": [{"name": "Template", "uriTemplate": "file:///{name}"}],
    }

    async def list_items(self: StubMcpSession, method: str, collection: str) -> list[dict[str, object]]:
        return items.get(method, [])

    monkeypatch.setattr(StubMcpSession, "list_items", list_items)
    return items


def _fire(handler: object, *args: object) -> None:
    assert callable(handler)
    handler(*args)


def _root(page: FakePage) -> ft.Column:
    return cast(ft.Column, find_control(page, "capabilities-view"))


def _catalog_columns(page: FakePage) -> tuple[ft.Column, ft.Column]:
    workspace = cast(ft.ResponsiveRow, _root(page).controls[-1])
    left, right = (cast(ft.Container, item) for item in workspace.controls)
    left_panel = cast(ft.Column, cast(ft.Container, left.content).content)
    return (
        cast(ft.Column, left_panel.controls[-1]),
        cast(ft.Column, cast(ft.Container, right.content).content),
    )


def _card_names(column: ft.Column) -> list[str]:
    return [str(cast(ft.Text, cast(ft.Row, cast(ft.Container, card).content).controls[1]).value)
            for card in column.controls]


async def _connect(*, oauth: bool = False) -> tuple[FakePage, StubMcpSession]:
    page = FakePage()
    app_module.main(cast(ft.Page, page))
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "http://127.0.0.1:7777/mcp"
    authorization = cast(ft.Checkbox, find_control(page, "browser-oauth"))
    authorization.value = oauth
    actions = cast(ft.Row, find_control(page, "connection-actions"))
    connect = cast(ft.FilledTonalButton, actions.controls[0])
    assert connect.on_click is not None
    cast(Callable[[], None], connect.on_click)()
    await asyncio.gather(*page.tasks)
    select_screen(page, 1)
    return page, StubMcpSession.instances[-1]


async def _exercise_connected_ui() -> None:
    page, stub = await _connect()
    root = _root(page)

    assert stub.url == "http://127.0.0.1:7777/mcp"
    assert stub.tool_calls == []  # Discovery must never execute a tool.

    workspace = cast(ft.ResponsiveRow, root.controls[-1])
    assert workspace.visible
    summary = cast(ft.Row, find_control(page, "capability-summary"))
    assert summary.visible and len(summary.controls) == 3
    navigation = cast(ft.Row, find_control(page, "capability-categories"))
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


def test_connected_workspaces_stay_interactive() -> None:
    asyncio.run(_exercise_connected_ui())


@pytest.mark.parametrize(("query", "expected"), [
    (None, ["Alpha", "Straße", "Duplicate", "Duplicate"]),
    ("", ["Alpha", "Straße", "Duplicate", "Duplicate"]),
    ("   ", ["Alpha", "Straße", "Duplicate", "Duplicate"]),
    (" ALPHA ", ["Alpha"]),
    ("second tool", ["Straße"]),
    ("STRASSE", ["Straße"]),
    ("duplicate", ["Duplicate", "Duplicate"]),
    ("missing", []),
])
def test_search_preserves_order_unicode_and_empty_states(
    catalog: Catalog, query: str | None, expected: list[str],
) -> None:
    async def exercise() -> None:
        page, session = await _connect()
        search = cast(ft.TextField, find_control(page, "capability-search"))
        if query is not None:
            search.value = query
        previous = page.update_count
        _fire(search.on_change)
        left, detail = _catalog_columns(page)
        assert _card_names(left) == expected
        assert page.update_count == previous + 1
        if not expected:
            assert cast(ft.Text, detail.controls[1]).value == "Nothing found"
        assert session.tool_calls == []

    asyncio.run(exercise())


def test_selection_survives_filtering_and_duplicates_keep_first_detail(catalog: Catalog) -> None:
    async def exercise() -> None:
        page, _ = await _connect()
        left, _ = _catalog_columns(page)
        _fire(cast(ft.Container, left.controls[1]).on_click, None)
        _, detail = _catalog_columns(page)
        assert cast(ft.Text, detail.controls[1]).value == "Second tool"
        search = cast(ft.TextField, find_control(page, "capability-search"))
        search.value = "tool"
        _fire(search.on_change)
        _, detail = _catalog_columns(page)
        assert cast(ft.Text, detail.controls[1]).value == "Second tool"
        search.value = "duplicate"
        _fire(search.on_change)
        left, detail = _catalog_columns(page)
        assert _card_names(left) == ["Duplicate", "Duplicate"]
        assert cast(ft.Text, detail.controls[1]).value == "First duplicate"
        for card in left.controls:
            icon = cast(ft.Icon, cast(ft.Row, cast(ft.Container, card).content).controls[0])
            assert icon.icon == ft.Icons.CHECK_CIRCLE

    asyncio.run(exercise())


@pytest.mark.parametrize(("index", "category"), enumerate(app_module.CATEGORIES))
def test_tab_callbacks_select_their_own_category(catalog: Catalog, index: int, category: str) -> None:
    async def exercise() -> None:
        page, session = await _connect()
        search = cast(ft.TextField, find_control(page, "capability-search"))
        search.value = "stale filter"
        previous = page.update_count
        navigation = cast(ft.Row, find_control(page, "capability-categories"))
        _fire(cast(ft.OutlinedButton, navigation.controls[index]).on_click)
        heading = cast(ft.Text, find_control(page, "capability-heading")).value
        assert heading.startswith(category if category != "Logs" else "JSON-RPC")
        assert search.value == ""
        assert page.update_count == previous + 1
        assert session.tool_calls == []
        if category == "Resources":
            left, _ = _catalog_columns(page)
            assert _card_names(left) == ["file:///readme", "Template"]

    asyncio.run(exercise())


def test_log_render_and_clear_are_still_interactive() -> None:
    async def exercise() -> None:
        page, session = await _connect()
        session.events.append(RpcEvent("12:00:00", "←", "tools/list", '{"tools": []}'))
        navigation = cast(ft.Row, find_control(page, "capability-categories"))
        _fire(cast(ft.OutlinedButton, navigation.controls[-1]).on_click)
        left, detail = _catalog_columns(page)
        log = cast(ft.TextField, detail.controls[1])
        assert log.value == '[12:00:00] ← tools/list\n{"tools": []}'
        _fire(cast(ft.OutlinedButton, left.controls[-1]).on_click)
        assert session.events == []
        _, detail = _catalog_columns(page)
        assert cast(ft.TextField, detail.controls[1]).value == "No traffic recorded."

    asyncio.run(exercise())


@pytest.mark.parametrize("category_index", [1, 2])
def test_prompt_and_resource_calls_keep_result_and_copy_controls(
    catalog: Catalog, category_index: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []

    async def copy(self: ft.Clipboard, value: str) -> None:
        copied.append(value)

    monkeypatch.setattr(ft.Clipboard, "set", copy)

    async def exercise() -> None:
        page, session = await _connect()
        navigation = cast(ft.Row, find_control(page, "capability-categories"))
        _fire(cast(ft.OutlinedButton, navigation.controls[category_index]).on_click)
        _, detail = _catalog_columns(page)
        field = cast(ft.TextField, detail.controls[3])
        if category_index == 1:
            field.value = "Python"
        action_row = cast(ft.Row, detail.controls[4])
        _fire(cast(ft.FilledButton, action_row.controls[0]).on_click)
        await asyncio.gather(*page.tasks)
        assert session.tool_calls == []
        assert session.prompt_calls == ([("Sample", {"topic": "Python"})] if category_index == 1 else [])
        assert session.resource_reads == (["file:///readme"] if category_index == 2 else [])
        assert cast(ft.Text, action_row.controls[1]).value.startswith("Completed")
        output = cast(ft.Column, detail.controls[5])
        assert any(isinstance(control, ft.ExpansionTile) for control in output.controls)
        copy_button = cast(ft.OutlinedButton, output.controls[-1])
        assert copy_button.content == "Copy complete JSON result"
        _fire(copy_button.on_click)
        await asyncio.gather(*page.tasks)
        assert len(copied) == 1
        assert json.loads(copied[0]) == (
            {"messages": [{"role": "user", "content": {"type": "text", "text": "Prompt"}}]}
            if category_index == 1 else {"contents": [{"uri": "file:///readme", "text": "Resource"}]}
        )

    asyncio.run(exercise())


def test_discovery_failures_remain_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    original = StubMcpSession.list_items

    async def list_items(self: StubMcpSession, method: str, collection: str) -> list[dict[str, object]]:
        if method == "prompts/list":
            raise ValueError("Discovery failed")
        return await original(self, method, collection)

    monkeypatch.setattr(StubMcpSession, "list_items", list_items)

    async def exercise() -> None:
        page, _ = await _connect()
        select_screen(page, 0)
        connection = cast(ft.Column, cast(ft.Container, find_control(page, "connection-card")).content)
        warning = cast(ft.Text, connection.controls[-1])
        assert "Discovery warnings: prompts/list: ValueError: Discovery failed" in warning.value
        select_screen(page, 1)
        left, _ = _catalog_columns(page)
        assert _card_names(left) == ["inspect_status"]

    asyncio.run(exercise())


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("enum_field", [False, True])
def test_input_borders_preserve_palette_shape_and_focus_width(
    catalog: Catalog, palette: str, mode: str, enum_field: bool,
) -> None:
    definition: dict[str, object] = {"type": "string"}
    if enum_field:
        definition["enum"] = ["one", "two"]
    catalog["tools/list"] = [{"name": "Styled field", "inputSchema": {
        "type": "object", "properties": {"value": definition},
    }}]

    async def exercise() -> None:
        page, _ = await _connect()

        def appearance_controls() -> ft.Row:
            return cast(ft.Row, find_control(page, "appearance-actions"))

        dropdown = cast(ft.Dropdown, appearance_controls().controls[0])
        dropdown.value = palette
        _fire(dropdown.on_select)
        if mode == "light":
            _fire(cast(ft.IconButton, appearance_controls().controls[1]).on_click)

        colors = PALETTES[palette][mode]
        tinted = [field for field in walk_controls(page.controls)
                  if isinstance(field, (ft.TextField, ft.Dropdown))
                  and field.label != "Palette"
                  and not (isinstance(field, ft.TextField) and field.read_only)]
        assert len(tinted) == 3  # Search, form input, and advanced JSON on this screen.
        assert any(isinstance(field, ft.Dropdown) for field in tinted) == enum_field
        for field in tinted:
            assert field.border_color is None
            assert field.focused_border_color is None
            assert field.bgcolor == colors.raised
            assert field.color == colors.foreground
            assert isinstance(field.border, dict)
            assert set(field.border) == {ft.ControlState.DEFAULT, ft.ControlState.FOCUSED}
            for state, color, width in (
                (ft.ControlState.DEFAULT, colors.outline, 1),
                (ft.ControlState.FOCUSED, colors.accent, 2),
            ):
                border = field.border[state]
                assert isinstance(border, ft.OutlineInputBorder)
                assert border.border_radius == 4
                assert border.gap_padding == 4
                assert border.side is not None
                assert border.side.color == color
                assert border.side.width == width

    asyncio.run(exercise())


def test_screen_changes_and_resize_keep_search_and_tool_results() -> None:
    async def exercise() -> None:
        page, session = await _connect()
        search = cast(ft.TextField, find_control(page, "capability-search"))
        search.value = "status"
        _fire(search.on_change)
        _, detail = _catalog_columns(page)
        action = cast(ft.Row, detail.controls[6])
        _fire(cast(ft.FilledButton, action.controls[0]).on_click)
        await asyncio.gather(*page.tasks)
        output = cast(ft.Column, detail.controls[7])
        result_controls = list(output.controls)
        select_screen(page, 0)
        assert cast(ft.TextField, find_control(page, "endpoint")).disabled
        select_screen(page, 1)
        assert find_control(page, "capability-search") is search
        assert search.value == "status"
        assert output.controls == result_controls
        page.width = 400
        assert page.on_resize is not None
        page.on_resize(None)
        assert find_control(page, "catalog-detail") is detail
        assert output.controls == result_controls
        assert len(session.tool_calls) == 1

    asyncio.run(exercise())


def test_browser_login_uses_oauth_and_discovers_tools_once(monkeypatch: pytest.MonkeyPatch) -> None:
    listed: list[str] = []
    original = StubMcpSession.list_items

    async def list_items(self: StubMcpSession, method: str, collection: str) -> list[dict[str, object]]:
        listed.append(method)
        return await original(self, method, collection)

    monkeypatch.setattr(StubMcpSession, "list_items", list_items)

    async def exercise() -> None:
        page, session = await _connect(oauth=True)
        assert session.oauth and session.bearer == ""
        assert listed.count("tools/list") == 1
        assert session.tool_calls == []
        select_screen(page, 0)
        assert cast(ft.Checkbox, find_control(page, "browser-oauth")).disabled

    asyncio.run(exercise())


def test_disconnect_cancels_pending_browser_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        started = asyncio.Event()
        finish = asyncio.Event()

        async def initialize(self: StubMcpSession) -> dict[str, object]:
            started.set()
            await finish.wait()
            return {}

        async def close(self: StubMcpSession) -> None:
            self.closed = True
            finish.set()

        monkeypatch.setattr(StubMcpSession, "initialize", initialize)
        monkeypatch.setattr(StubMcpSession, "close", close)
        page = FakePage()
        app_module.main(cast(ft.Page, page))
        cast(ft.TextField, find_control(page, "endpoint")).value = "https://example.net/mcp"
        cast(ft.Checkbox, find_control(page, "browser-oauth")).value = True
        actions = cast(ft.Row, find_control(page, "connection-actions"))
        _fire(cast(ft.FilledTonalButton, actions.controls[0]).on_click)
        await started.wait()
        _fire(cast(ft.OutlinedButton, actions.controls[1]).on_click)
        await asyncio.gather(*page.tasks)
        assert StubMcpSession.instances[-1].closed
        assert not cast(ft.FilledTonalButton, actions.controls[0]).disabled
        assert not cast(ft.Checkbox, find_control(page, "browser-oauth")).disabled
        select_screen(page, 1)
        assert not cast(ft.ResponsiveRow, find_control(page, "capabilities-workspace")).visible

    asyncio.run(exercise())


def test_oauth_discovery_failure_never_marks_connection_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    async def list_items(self: StubMcpSession, method: str, collection: str) -> list[dict[str, object]]:
        raise RuntimeError("Tool access denied")

    monkeypatch.setattr(StubMcpSession, "list_items", list_items)

    async def exercise() -> None:
        page, session = await _connect(oauth=True)
        assert session.closed
        assert not cast(ft.ResponsiveRow, find_control(page, "capabilities-workspace")).visible
        select_screen(page, 0)
        connection = cast(ft.Column, cast(ft.Container, find_control(page, "connection-card")).content)
        assert "Tool access denied" in cast(ft.Text, connection.controls[-1]).value

    asyncio.run(exercise())
