"""A manual MCP playground: discover, inspect and invoke remote MCP capabilities."""

from collections.abc import Callable
import json
import time

import flet as ft

from rendering import content_views, preview
from schema_form import (
    create_fields,
    form_arguments,
    requires_advanced_json,
    validate_tool_arguments,
)
from transport import McpSession, validate_endpoint
from ui_theme import DEFAULT_BRIGHTNESS, DEFAULT_PALETTE, PALETTES, Palette

CATEGORIES = ("Tools", "Prompts", "Resources", "Logs")
CATEGORY_ICONS: dict[str, ft.IconData] = {
    "Tools": ft.Icons.BUILD_OUTLINED,
    "Prompts": ft.Icons.DESCRIPTION_OUTLINED,
    "Resources": ft.Icons.FOLDER_OPEN_OUTLINED,
    "Logs": ft.Icons.RECEIPT_LONG_OUTLINED,
}


def _name(item: dict[str, object], category: str) -> str:
    field = "name" if category != "Resources" else "uri"
    return str(item.get(field) or item.get("name") or item.get("uriTemplate") or "(unnamed)")


def _schema(item: dict[str, object]) -> dict[str, object]:
    value = item.get("inputSchema")
    return value if isinstance(value, dict) else {"type": "object", "properties": {}}


def main(page: ft.Page) -> None:
    """A Lagoon-styled, fully manual MCP client with no automatic tool execution."""
    page.title = "MCP User UI · Playground"
    page.window.width = 1080
    page.window.height = 690
    page.padding = 0
    page.scroll = ft.ScrollMode.HIDDEN
    clipboard = ft.Clipboard()
    page.services.append(clipboard)

    theme_name = DEFAULT_PALETTE
    brightness = DEFAULT_BRIGHTNESS
    colors: Palette = PALETTES[theme_name][brightness]
    input_borders: dict[ft.ControlState, ft.InputBorder] = {}

    def text(value: str, size: int = 13, *, bold: bool = False,
             muted: bool = False, color: str | None = None) -> ft.Text:
        return ft.Text(
            value, size=size, selectable=True,
            weight=ft.FontWeight.W_600 if bold else ft.FontWeight.NORMAL,
            color=color or (colors.muted if muted else colors.foreground),
        )

    def panel(content: ft.Control, *, tinted: bool = False,
              padding: int = 18, radius: int = 16) -> ft.Container:
        return ft.Container(
            content=content,
            bgcolor=colors.accent_soft if tinted else colors.surface,
            padding=padding,
            border_radius=radius,
            border=ft.Border.all(1, colors.outline),
        )

    def icon_tile(icon: ft.IconData, *, tinted: bool = False,
                  size: int = 22) -> ft.Container:
        return ft.Container(
            content=ft.Icon(icon, color=colors.accent, size=size),
            padding=12, border_radius=12,
            bgcolor=colors.accent_soft if tinted else colors.raised,
        )

    def tint_field(field: ft.Control) -> None:
        if isinstance(field, (ft.TextField, ft.Dropdown)):
            field.bgcolor = colors.raised
            field.border = input_borders
            field.color = colors.foreground
        elif isinstance(field, ft.Column):
            for child in field.controls:
                tint_field(child)

    endpoint = ft.TextField(
        key="endpoint",
        label="Remote MCP endpoint", hint_text="https://server.example/mcp",
        expand=True, autofocus=True,
    )
    token = ft.TextField(key="bearer-token", label="Bearer token · optional", password=True,
                         can_reveal_password=True)
    browser_oauth = ft.Checkbox(
        key="browser-oauth", label="Use browser OAuth authorization", value=False,
    )
    connect_button = ft.FilledTonalButton("Connect server", icon=ft.Icons.LINK)
    disconnect_button = ft.OutlinedButton("Disconnect", disabled=True)
    refresh_button = ft.OutlinedButton("Refresh", icon=ft.Icons.REFRESH, disabled=True)
    progress = ft.ProgressRing(width=18, height=18, color=colors.accent, visible=False)
    status = text("Disconnected", bold=True, color=colors.muted)
    connection_detail = text(
        "Paste a running Streamable HTTP MCP URL. No local server is launched.",
        size=12, muted=True,
    )
    filter_box = ft.TextField(
        key="capability-search",
        label="Search capabilities", hint_text="Search by name or description",
        prefix_icon=ft.Icons.SEARCH,
        disabled=True, dense=True,
    )
    navigation = ft.Row(key="capability-categories", spacing=8, wrap=True)
    heading = text("Discover capabilities", size=17, bold=True)
    heading.key = "capability-heading"
    list_column = ft.Column(key="catalog-list", spacing=7,
                            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    detail_column = ft.Column(key="catalog-detail", spacing=12,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    workspace = ft.ResponsiveRow(visible=False)
    summary_row = ft.Row(key="capability-summary", spacing=12, wrap=True, visible=False)
    empty_state = ft.Container(visible=True)
    connection_view = ft.Column(
        key="connection-view", spacing=15,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    # TODO: Recheck full-width search/discovery with large text on physical phones.
    capabilities_view = ft.Column(
        key="capabilities-view", spacing=15,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    screen_host = ft.Container(key="screen-host", content=connection_view)
    selected_tab = 0

    session: McpSession | None = None
    pending_session: McpSession | None = None
    generation = 0
    loading = False
    running = False
    category = "Tools"
    selected_name: str | None = None
    catalog: dict[str, list[dict[str, object]]] = {name: [] for name in CATEGORIES}

    def update_connection() -> None:
        connected = session is not None
        endpoint.disabled = connected or loading
        token.disabled = connected or loading or bool(browser_oauth.value)
        browser_oauth.disabled = connected or loading
        connect_button.disabled = connected or loading
        disconnect_button.disabled = not connected and not loading
        refresh_button.disabled = not connected or loading or running
        progress.visible = loading
        filter_box.disabled = not connected
        workspace.visible = connected
        summary_row.visible = connected
        empty_state.visible = not connected
        status.value = "Connecting…" if loading else "Connected" if connected else "Disconnected"
        status.color = colors.accent if connected else colors.muted
        progress.color = colors.accent
        page.update()

    def set_category(next_category: str) -> None:
        nonlocal category, selected_name
        category = next_category
        selected_name = None
        filter_box.value = ""
        draw_catalog()

    def tab_handler(tab: str) -> Callable[[], None]:
        def select() -> None:
            set_category(tab)
        return select

    def draw_navigation() -> None:
        navigation.controls.clear()
        if session is None:
            return
        for label in CATEGORIES:
            if label != "Logs" and label.lower() not in session.capabilities:
                continue
            count = len(catalog[label]) if label != "Logs" else len(session.events)
            caption = f"{label}  ·  {count}"
            if category == label:
                button: ft.Control = ft.FilledTonalButton(
                    caption, icon=CATEGORY_ICONS[label],
                    bgcolor=colors.accent_soft, color=colors.accent,
                )
            else:
                button = ft.OutlinedButton(caption, icon=CATEGORY_ICONS[label])
            button.on_click = tab_handler(label)
            navigation.controls.append(button)

    def display_result(result: dict[str, object], target: ft.Column) -> None:
        target.controls = content_views(result)
        copy_button = ft.OutlinedButton("Copy complete JSON result")
        copy_button.on_click = lambda: page.run_task(
            clipboard.set, json.dumps(result, ensure_ascii=False, indent=2, default=str),
        )
        target.controls.append(copy_button)

    async def invoke(
        self_session: McpSession,
        method: str,
        params: dict[str, object],
        feedback: ft.Text,
        output: ft.Column,
        button: ft.FilledButton,
    ) -> None:
        nonlocal running
        if session is not self_session or running:
            return
        running = True
        button.disabled = True
        refresh_button.disabled = True
        feedback.value = "Running remote MCP request…"
        feedback.color = ft.Colors.OUTLINE
        output.controls.clear()
        page.update()
        started = time.perf_counter()
        try:
            if method == "tools/call":
                name = str(params["name"])
                args = params["arguments"]
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
                result = await self_session.call_tool(name, args)
            elif method == "prompts/get":
                name = str(params["name"])
                args = params["arguments"]
                if not isinstance(args, dict):
                    raise ValueError("Prompt arguments must be a JSON object.")
                result = await self_session.get_prompt(name, args)
            elif method == "resources/read":
                result = await self_session.read_resource(str(params["uri"]))
            else:
                raise ValueError("Unsupported MCP operation.")
            if session is self_session:
                display_result(result, output)
                failed = result.get("isError") is True
                feedback.value = (
                    f"{'Remote tool error' if failed else 'Completed'} "
                    f"in {(time.perf_counter() - started) * 1000:.0f} ms"
                )
                feedback.color = ft.Colors.ERROR if failed else ft.Colors.PRIMARY
        except Exception as exc:
            if session is self_session:
                feedback.value = f"{type(exc).__name__}: {exc}"
                feedback.color = ft.Colors.ERROR
        finally:
            if session is self_session:
                running = False
                button.disabled = False
                refresh_button.disabled = False
                if category == "Logs":
                    draw_catalog()
                page.update()

    def tool_editor(item: dict[str, object]) -> list[ft.Control]:
        schema = _schema(item)
        fields, controls = create_fields(schema, on_change=page.update)
        for field in fields:
            tint_field(field)
        must_use_json = requires_advanced_json(schema)
        advanced = ft.Checkbox(label="Advanced JSON arguments", value=must_use_json)
        raw_input = ft.TextField(label="Arguments as JSON object", value="{}", multiline=True,
                                 min_lines=3, max_lines=12, visible=must_use_json)
        tint_field(raw_input)
        form_panel = ft.Column(
            fields, spacing=12, visible=not must_use_json,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        feedback = ft.Text("No call yet.", selectable=True, color=ft.Colors.OUTLINE, expand=True)
        output = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        run_button = ft.FilledButton("Run tool", icon=ft.Icons.PLAY_ARROW)

        def toggle_mode() -> None:
            raw_input.visible = bool(advanced.value)
            form_panel.visible = not bool(advanced.value)
            if advanced.value and controls:
                try:
                    raw_input.value = json.dumps(form_arguments(schema, controls), indent=2, ensure_ascii=False)
                except ValueError:
                    pass
            page.update()

        def call_tool() -> None:
            active = session
            if active is None or running:
                return
            try:
                if advanced.value:
                    value: object = json.loads(raw_input.value or "{}")
                    if not isinstance(value, dict):
                        raise ValueError("Arguments must be a JSON object.")
                    args = value
                else:
                    args = form_arguments(schema, controls)
                validate_tool_arguments(schema, args)
            except ValueError as exc:
                feedback.value = f"Invalid arguments: {exc}"
                feedback.color = ft.Colors.ERROR
                page.update()
                return
            page.run_task(invoke, active, "tools/call", {"name": _name(item, "Tools"), "arguments": args},
                          feedback, output, run_button)

        advanced.on_change = toggle_mode
        run_button.on_click = call_tool
        views: list[ft.Control] = [advanced, form_panel, raw_input,
                                   ft.Row([run_button, feedback]), output]
        views.append(ft.ExpansionTile(
            title="Input schema",
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[ft.TextField(value=preview(schema), read_only=True, multiline=True,
                                   min_lines=3, max_lines=12)],
        ))
        if isinstance(item.get("outputSchema"), dict):
            views.append(ft.ExpansionTile(
                title="Output schema",
                expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[ft.TextField(value=preview(item["outputSchema"]), read_only=True,
                                       multiline=True, min_lines=3, max_lines=12)],
            ))
        return views

    def prompt_editor(item: dict[str, object]) -> list[ft.Control]:
        arg_fields: dict[str, tuple[ft.TextField, bool]] = {}
        fields: list[ft.Control] = []
        args = item.get("arguments")
        if isinstance(args, list):
            for arg in args:
                if not isinstance(arg, dict) or not isinstance(arg.get("name"), str):
                    continue
                name = arg["name"]
                required = arg.get("required") is True
                field = ft.TextField(label=f"{name}{' *' if required else ''}",
                                     hint_text=str(arg.get("description") or ""))
                tint_field(field)
                fields.append(field)
                arg_fields[name] = (field, required)
        feedback = ft.Text("No prompt retrieved.", color=ft.Colors.OUTLINE, expand=True)
        output = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        button = ft.FilledButton("Get prompt")

        def run_prompt() -> None:
            active = session
            if active is None or running:
                return
            arguments: dict[str, object] = {}
            for name, (field, required) in arg_fields.items():
                value = field.value or ""
                if required and not value.strip():
                    feedback.value = f"Required argument missing: {name}"
                    feedback.color = ft.Colors.ERROR
                    page.update()
                    return
                if value:
                    arguments[name] = value
            page.run_task(invoke, active, "prompts/get", {"name": _name(item, "Prompts"),
                           "arguments": arguments}, feedback, output, button)

        button.on_click = run_prompt
        return [*fields, ft.Row([button, feedback]), output]

    def resource_editor(item: dict[str, object]) -> list[ft.Control]:
        uri = item.get("uri") or item.get("uriTemplate") or ""
        uri_field = ft.TextField(label="Resource URI (expand template placeholders manually)",
                                 value=str(uri))
        tint_field(uri_field)
        feedback = ft.Text("No resource retrieved.", color=colors.muted, expand=True)
        output = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        button = ft.FilledButton("Read resource")

        def read_resource() -> None:
            active = session
            if active is None or running:
                return
            value = (uri_field.value or "").strip()
            if not value or "{" in value or "}" in value:
                feedback.value = "Enter a complete resource URI without template placeholders."
                feedback.color = ft.Colors.ERROR
                page.update()
                return
            page.run_task(invoke, active, "resources/read", {"uri": value},
                          feedback, output, button)

        button.on_click = read_resource
        return [uri_field, ft.Row([button, feedback]), output]

    def draw_detail(item: dict[str, object]) -> None:
        detail_column.controls.clear()
        name = _name(item, category)
        chosen_icon = CATEGORY_ICONS.get(category, ft.Icons.DATA_OBJECT)
        detail_column.controls.extend([
            ft.Row([
                icon_tile(chosen_icon, tinted=True),
                ft.Column([
                    text(category.upper() + " / SELECTED ITEM", 10, color=colors.secondary),
                    text(name, 21, bold=True),
                ], spacing=4),
            ], spacing=12, wrap=True),
            text(str(item.get("description") or "No description supplied by server."),
                 12, muted=True),
            ft.Divider(height=1, color=colors.outline),
        ])
        if category == "Tools":
            detail_column.controls.extend(tool_editor(item))
        elif category == "Prompts":
            detail_column.controls.extend(prompt_editor(item))
        elif category == "Resources":
            detail_column.controls.extend(resource_editor(item))

    def draw_catalog() -> None:
        nonlocal selected_name
        list_column.controls.clear()
        detail_column.controls.clear()
        if session is None:
            heading.value = "Connect to browse MCP capabilities."
            navigation.controls.clear()
            page.update()
            return
        draw_navigation()
        refresh_summary()
        if category == "Logs":
            heading.value = "JSON-RPC request and response log (current connection only)"
            list_column.controls.append(text(
                "Recent requests and responses, held only in memory.", 12, muted=True,
            ))
            raw = "\n\n".join(
                f"[{entry.when}] {entry.direction} {entry.method}\n{entry.payload}"
                for entry in session.events
            )
            detail_column.controls.append(text(
                "Traffic can include sensitive arguments. Logs stay in memory and are bounded.",
                12, muted=True,
            ))
            log_field = ft.TextField(
                label="JSON-RPC log", value=raw[-MAX_LOG_CHARS:] or "No traffic recorded.",
                read_only=True, multiline=True, min_lines=12, max_lines=25,
            )
            tint_field(log_field)
            detail_column.controls.append(log_field)

            def clear_log() -> None:
                if session is not None:
                    session.events.clear()
                    draw_catalog()
            clear_button = ft.OutlinedButton("Clear log")
            clear_button.on_click = clear_log
            list_column.controls.append(clear_button)
            page.update()
            return
        heading.value = f"{category} · {len(catalog[category])} discovered"
        query = (filter_box.value or "").strip().casefold()
        # TODO: Profile very large catalogs before adding a persistent search cache.
        matches: list[tuple[dict[str, object], str]] = []
        for item in catalog[category]:
            item_name = _name(item, category)
            if query in (item_name + " " + str(item.get("description") or "")).casefold():
                matches.append((item, item_name))
        if not matches:
            detail_column.controls.extend([
                icon_tile(ft.Icons.SEARCH),
                text("Nothing found", 17, bold=True),
                text("Refresh discovery or try another search.", 12, muted=True),
            ])
            page.update()
            return
        if not any(name == selected_name for _, name in matches):
            selected_name = matches[0][1]
        for item, item_name in matches:
            selected = item_name == selected_name

            def choose(_event: object, entry: dict[str, object] = item) -> None:
                nonlocal selected_name
                selected_name = _name(entry, category)
                draw_catalog()

            item_card = ft.Container(
                content=ft.Row([
                    ft.Icon(
                        ft.Icons.CHECK_CIRCLE if selected else ft.Icons.DATA_OBJECT,
                        size=18, color=colors.accent if selected else colors.muted,
                    ),
                    ft.Text(
                        item_name, size=12,
                        weight=ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL,
                        color=colors.foreground,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=2, expand=True,
                    ),
                ], spacing=9),
                bgcolor=colors.accent_soft if selected else colors.raised,
                border=ft.Border.all(1, colors.accent if selected else colors.outline),
                padding=11, border_radius=11, ink=True,
                on_click=choose,
            )
            list_column.controls.append(item_card)
        for item, item_name in matches:
            if item_name == selected_name:
                draw_detail(item)
                break
        page.update()

    async def discover(
        active: McpSession, initial_tools: list[dict[str, object]] | None = None,
    ) -> None:
        nonlocal catalog
        data: dict[str, list[dict[str, object]]] = {name: [] for name in CATEGORIES}
        errors: list[str] = []
        jobs = [
            ("Tools", "tools", "tools/list", "tools"),
            ("Prompts", "prompts", "prompts/list", "prompts"),
            ("Resources", "resources", "resources/list", "resources"),
            ("Resources", "resources", "resources/templates/list", "resourceTemplates"),
        ]
        for label, capability, method, key in jobs:
            if capability not in active.capabilities:
                continue
            if method == "tools/list" and initial_tools is not None:
                data[label].extend(initial_tools)
                continue
            try:
                data[label].extend(await active.list_items(method, key))
            except Exception as exc:
                errors.append(f"{method}: {type(exc).__name__}: {exc}")
        if session is active:
            catalog = data
            connection_detail.value = (
                f"{active.server_info.get('name', 'MCP server')} · protocol {active.version} · "
                f"{len(data['Tools'])} tools, {len(data['Prompts'])} prompts, "
                f"{len(data['Resources'])} resources/templates. "
                + ("Discovery warnings: " + "; ".join(errors) if errors else "")
            )
            connection_detail.color = colors.danger if errors else colors.muted
            draw_catalog()

    async def connect_task(epoch: int, url: str, bearer: str, use_oauth: bool) -> None:
        nonlocal session, pending_session, loading, category, selected_name
        if epoch != generation:
            return
        active = McpSession(url, "" if use_oauth else bearer, oauth=use_oauth)
        pending_session = active
        started = time.perf_counter()
        try:
            await active.initialize()
            initial_tools = None
            if use_oauth and "tools" in active.capabilities:
                initial_tools = await active.list_items("tools/list", "tools")
            if epoch != generation:
                return
            session = active
            category = "Tools" if "tools" in active.capabilities else (
                "Prompts" if "prompts" in active.capabilities else (
                    "Resources" if "resources" in active.capabilities else "Logs"
                )
            )
            selected_name = None
            connection_detail.value = f"Connected in {(time.perf_counter() - started) * 1000:.0f} ms. Discovering…"
            update_connection()
            await discover(active, initial_tools)
        except Exception as exc:
            if epoch == generation:
                connection_detail.value = f"Connection failed: {type(exc).__name__}: {exc}"
                connection_detail.color = colors.danger
                if session is active:
                    session = None
                draw_catalog()
        finally:
            if pending_session is active:
                pending_session = None
            if epoch != generation or session is not active:
                await active.close()
            if epoch == generation:
                loading = False
                update_connection()

    def on_connect() -> None:
        nonlocal generation, loading
        try:
            url = validate_endpoint(endpoint.value or "")
        except ValueError as exc:
            connection_detail.value = str(exc)
            connection_detail.color = colors.danger
            page.update()
            return
        generation += 1
        loading = True
        use_oauth = bool(browser_oauth.value)
        connection_detail.value = (
            "Browser sign-in… Complete authorization if prompted, or Disconnect to cancel."
            if use_oauth else "Connecting and negotiating MCP protocol…"
        )
        connection_detail.color = colors.muted
        update_connection()
        page.run_task(connect_task, generation, url, token.value or "", use_oauth)

    async def disconnect_task(active: McpSession) -> None:
        await active.close()

    def on_disconnect() -> None:
        nonlocal generation, session, pending_session, loading, running, selected_name
        generation += 1
        active = session or pending_session
        session = None
        pending_session = None
        loading = False
        running = False
        selected_name = None
        catalog.update({name: [] for name in CATEGORIES})
        connection_detail.value = "Disconnected. Previous results cleared; server-side effects are not undone."
        connection_detail.color = colors.muted
        draw_catalog()
        update_connection()
        if active is not None:
            page.run_task(disconnect_task, active)

    async def refresh_discovery(active: McpSession) -> None:
        if session is not active:
            return
        refresh_button.disabled = True
        page.update()
        try:
            await discover(active)
        finally:
            if session is active:
                refresh_button.disabled = False
                page.update()

    def refresh_summary() -> None:
        """Keep the displayed counts grounded in actual advertised capabilities."""
        summary_row.controls.clear()
        for name in CATEGORIES[:-1]:
            summary_row.controls.append(
                ft.Container(
                    content=ft.Row([
                        icon_tile(CATEGORY_ICONS[name]),
                        ft.Column([
                            text(str(len(catalog[name])), 22, bold=True),
                            text(name, 11, muted=True),
                        ], spacing=2),
                    ], spacing=12),
                    bgcolor=colors.surface,
                    border=ft.Border.all(1, colors.outline),
                    padding=14, border_radius=14, width=204,
                )
            )

    def set_appearance(*, palette: str | None = None,
                       mode: str | None = None) -> None:
        """Switch the watch app's palette/mode without contacting the server."""
        nonlocal theme_name, brightness, colors
        if palette is not None and palette in PALETTES:
            theme_name = palette
        if mode is not None and mode in ("light", "dark"):
            brightness = mode
        colors = PALETTES[theme_name][brightness]
        build_ui()
        if session is not None:
            draw_catalog()

    def select_screen(index: int) -> None:
        nonlocal selected_tab
        if index not in (0, 1):
            return
        selected_tab = index
        screen_host.content = connection_view if index == 0 else capabilities_view
        page.update()

    def build_ui() -> None:
        """Use watch-style tonal surfaces and one page-level scrollable layout."""
        nonlocal workspace, empty_state, input_borders
        # TODO: Recheck these equivalent border widths when upgrading Flet.
        input_borders = {
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(
                side=ft.BorderSide(width=1, color=colors.outline),
            ),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(
                side=ft.BorderSide(width=2, color=colors.accent),
            ),
        }
        page.bgcolor = colors.background
        page.theme_mode = (
            ft.ThemeMode.DARK if brightness == "dark" else ft.ThemeMode.LIGHT
        )
        page.theme = ft.Theme(use_material3=True, color_scheme_seed=colors.accent)
        page.dark_theme = ft.Theme(use_material3=True, color_scheme_seed=colors.accent)

        compact_header = (page.width or 430) < 600
        palette_choice = ft.Dropdown(
            label="Palette", width=124 if compact_header else 138,
            dense=True, value=theme_name,
            bgcolor=colors.raised, color=colors.foreground,
            options=[ft.DropdownOption(key=name, text=name) for name in PALETTES],
        )
        palette_choice.on_select = lambda: set_appearance(
            palette=palette_choice.value,
        )
        mode_button = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE if brightness == "dark" else ft.Icons.DARK_MODE,
            icon_color=colors.accent,
            tooltip="Switch to light mode" if brightness == "dark" else "Switch to dark mode",
        )
        mode_button.on_click = lambda: set_appearance(
            mode="light" if brightness == "dark" else "dark",
        )
        # Keep the top toolbar in the page body: this Flet desktop build clips
        # Page.appbar when combined with page-level scrolling.
        # TODO: Recheck title truncation and theme reachability on physical phones.
        page.appbar = None
        identity_controls: list[ft.Control] = []
        if not compact_header:
            identity_controls.append(icon_tile(ft.Icons.HUB, tinted=True, size=25))
        identity_controls.append(ft.Text(
            "MCP User UI", key="app-name", expand=True,
            size=16 if compact_header else 18,
            weight=ft.FontWeight.W_600, color=colors.foreground,
            max_lines=1, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
        ))
        top_bar = panel(
            ft.Row([
                ft.Row(
                    identity_controls, key="app-identity", spacing=11, expand=True,
                ),
                ft.Row(
                    [palette_choice, mode_button], spacing=9, tight=True,
                    key="appearance-actions",
                    alignment=ft.MainAxisAlignment.END,
                ),
            ], key="app-header", spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=13, radius=16,
        )

        for field in (endpoint, token, filter_box):
            tint_field(field)
        connect_button.bgcolor = colors.accent
        connect_button.color = colors.background
        connect_button.icon_color = colors.background
        status.color = colors.accent if session is not None else colors.muted
        connection_detail.color = colors.muted
        progress.color = colors.accent
        heading.color = colors.foreground
        refresh_summary()
        summary_row.visible = session is not None

        connection_card = panel(
            ft.Column([
                ft.Row([
                    icon_tile(ft.Icons.LINK),
                    ft.Column([
                        text("Connection", 17, bold=True),
                        text("Streamable HTTP · direct remote connection", 12, muted=True),
                    ], spacing=3),
                ], spacing=12, wrap=True),
                endpoint,
                token,
                browser_oauth,
                ft.Row([
                    connect_button, disconnect_button, refresh_button, progress,
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(
                                ft.Icons.CIRCLE,
                                color=colors.accent if session is not None else colors.faint,
                                size=9,
                            ),
                            status,
                        ], spacing=7, tight=True),
                        bgcolor=colors.raised, border_radius=99,
                        padding=ft.Padding(12, 8, 12, 8),
                    ),
                ], key="connection-actions", wrap=True, spacing=10, run_spacing=8),
                connection_detail,
            ], spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=20,
        )
        connection_card.key = "connection-card"

        empty_state = panel(
            ft.Row([
                icon_tile(ft.Icons.WIDGETS_OUTLINED, size=28),
                ft.Column([
                    text("Your workspace is ready", 17, bold=True),
                    text("Connect to an MCP endpoint to reveal its tools, prompts and resources.",
                         12, muted=True),
                ], spacing=5, expand=True),
            ], spacing=16),
            padding=24,
        )
        empty_state.visible = session is None

        workspace = ft.ResponsiveRow([
            ft.Container(
                content=panel(
                    ft.Column([
                        ft.Row([
                            icon_tile(ft.Icons.LIST_ALT, size=19),
                            ft.Column([
                                text("Library", 15, bold=True),
                                text("Discovered items", 11, muted=True),
                            ], spacing=3),
                        ], spacing=10),
                        ft.Divider(height=1, color=colors.outline),
                        list_column,
                    ], spacing=13, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    padding=14,
                ),
                col={"xs": 12, "sm": 12, "md": 4, "lg": 4},
            ),
            ft.Container(
                content=panel(
                    detail_column,
                    padding=20,
                ),
                col={"xs": 12, "sm": 12, "md": 8, "lg": 8},
            ),
        ], key="capabilities-workspace", spacing=12, run_spacing=12, visible=session is not None)

        connection_view.controls = [connection_card]
        capabilities_view.controls = [
            ft.Row([
                icon_tile(ft.Icons.WIDGETS_OUTLINED),
                ft.Column([
                    text("Capabilities", 18, bold=True),
                    text("Only what your server actually advertises.", 12, muted=True),
                ], spacing=3, expand=True),
            ], spacing=12),
            summary_row,
            navigation,
            heading,
            filter_box,
            empty_state,
            workspace,
        ]
        screen_host.content = connection_view if selected_tab == 0 else capabilities_view
        body = ft.Container(
            content=ft.Column(
                [top_bar, screen_host], key="page-body", spacing=15, expand=True,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            padding=22, expand=True,
        )
        wide = (page.width or 430) >= 860
        destinations = (
            ("Connection", ft.Icons.LINK_OUTLINED, ft.Icons.LINK),
            ("Capabilities", ft.Icons.WIDGETS_OUTLINED, ft.Icons.WIDGETS),
        )
        page.navigation_bar = ft.NavigationBar(
            key="screen-navigation-mobile", selected_index=selected_tab,
            destinations=[ft.NavigationBarDestination(label=label, icon=icon, selected_icon=selected)
                          for label, icon, selected in destinations],
            on_change=lambda event: select_screen(event.control.selected_index or 0),
            bgcolor=colors.surface, indicator_color=colors.accent_soft, visible=not wide,
        )
        if wide:
            rail = ft.NavigationRail(
                key="screen-navigation-wide", width=102, min_width=90,
                height=page.height or 690, selected_index=selected_tab,
                destinations=[ft.NavigationRailDestination(label=label, icon=icon, selected_icon=selected)
                              for label, icon, selected in destinations],
                label_type=ft.NavigationRailLabelType.ALL,
                on_change=lambda event: select_screen(event.control.selected_index or 0),
                bgcolor=colors.surface,
            )
            layout: ft.Control = ft.Row(
                [rail, body], spacing=0, expand=True, vertical_alignment=ft.CrossAxisAlignment.START,
            )
        else:
            layout = body
        page.controls.clear()
        page.add(ft.SafeArea(content=layout, expand=True))

    connect_button.on_click = on_connect
    disconnect_button.on_click = on_disconnect
    refresh_button.on_click = lambda: page.run_task(refresh_discovery, session) if session else None
    filter_box.on_change = draw_catalog
    browser_oauth.on_change = update_connection
    page.on_resize = lambda _event: build_ui()

    build_ui()


MAX_LOG_CHARS = 120_000
