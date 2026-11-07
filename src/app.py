"""A manual MCP playground: discover, inspect and invoke remote MCP capabilities."""

from collections.abc import Callable
from dataclasses import fields, is_dataclass, replace
import json
import time

import flet as ft

from app_preferences import AppPreferences
from saved_connections import SavedConnection, SavedConnectionStore, StorageAreas
from typography import DEFAULT_TEXT_SCALE, TypographyScaler, readable_markdown_style, typography_theme
from iconography import CATEGORY_ICONS, NAVIGATION_ICONS, argument_icon
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
    # ScrollMode.HIDDEN still scrolls (it only hides the scrollbar).
    # That made the entire page, including the desktop navigation rail,
    # move off-screen. Only the right-hand content column may scroll.
    page.scroll = None
    clipboard = ft.Clipboard()
    page.services.append(clipboard)

    preferences = AppPreferences.from_flet_environment()
    saved_store = SavedConnectionStore(StorageAreas.from_flet_environment())
    theme_name, brightness = preferences.load()
    nerd_mode = preferences.load_nerd_mode()
    ui_percent, answer_percent = preferences.load_text_scales()
    scaler = TypographyScaler()
    scaler.update(ui_percent, answer_percent)
    show_raw_json = False  # Independently opt-in each time the app starts.
    colors: Palette = PALETTES[theme_name][brightness]
    scaler.set_palette(colors, dark_mode=brightness == "dark")
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
        prefix_icon=ft.Icons.ALT_ROUTE_OUTLINED,
        expand=True, autofocus=True,
    )
    token = ft.TextField(key="bearer-token", label="Bearer token · optional", password=True,
                         prefix_icon=ft.Icons.ENHANCED_ENCRYPTION_OUTLINED,
                         can_reveal_password=True)
    browser_oauth = ft.Checkbox(
        key="browser-oauth", label="Use browser OAuth authorization", value=False,
    )
    connect_button = ft.FilledTonalButton("Connect server", icon=ft.Icons.CONNECT_WITHOUT_CONTACT_OUTLINED)
    disconnect_button = ft.OutlinedButton("Disconnect", icon=ft.Icons.LINK_OFF_OUTLINED, disabled=True)
    refresh_button = ft.OutlinedButton("Refresh", icon=ft.Icons.SYNC_OUTLINED, disabled=True)
    save_connection_button = ft.FilledTonalButton(
        "Save endpoint & tokens", key="save-connection",
        icon=ft.Icons.BOOKMARK_ADD_OUTLINED, disabled=True,
        bgcolor=colors.raised, color=colors.muted,
    )
    saved_list = ft.Column(
        key="saved-connections", spacing=9,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    save_notice = ft.Text(
        "", key="save-connection-notice", selectable=True,
        color=colors.muted,
    )
    saving_connection = False
    progress = ft.ProgressRing(width=18, height=18, color=colors.accent, visible=False)
    status = text("Disconnected", bold=True, color=colors.muted)
    connection_detail = text(
        "Paste a running Streamable HTTP MCP URL. No local server is launched.",
        size=12, muted=True,
    )
    raw_json_checkbox = ft.Checkbox(
        key="show-raw-json", label="Show raw JSON",
        value=False, visible=nerd_mode,
    )
    # These are only the controls owned by the currently selected capability.
    schema_technical_controls: list[ft.Control] = []
    result_technical_controls: list[ft.Control] = []
    current_tool_editor: tuple[ft.Checkbox, ft.TextField, ft.Column, bool] | None = None
    filter_box = ft.TextField(
        key="capability-search",
        label="Search capabilities", hint_text="Search by name or description",
        prefix_icon=ft.Icons.MANAGE_SEARCH_OUTLINED,
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
    library_surface: ft.Container | None = None
    details_surface: ft.Container | None = None
    library_contents: ft.Column | None = None
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
    settings_view = ft.Column(
        key="settings-view", spacing=15,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    screen_host = ft.Container(key="screen-host", content=connection_view)
    selected_tab = 0
    desktop_rail: ft.NavigationRail | None = None
    header_symbol: ft.Container | None = None
    appearance_buttons: dict[str, ft.FilledTonalButton] = {}
    palette_tiles: dict[str, ft.ListTile] = {}
    settings_warning = ft.Text(
        "", color=colors.danger, selectable=True, visible=False,
    )
    ui_scale_slider = ft.Slider(
        key="interface-text-scale", min=100, max=180, divisions=8,
        value=ui_percent, label="{value}%",
        expand=True,
    )
    answer_scale_slider = ft.Slider(
        key="answer-text-scale", min=100, max=180, divisions=8,
        value=answer_percent, label="{value}%",
        expand=True,
    )
    ui_scale_label = ft.Text(f"{ui_percent}%", key="interface-text-scale-label", selectable=True)
    answer_scale_label = ft.Text(
        f"{answer_percent}%", key="answer-text-scale-label", selectable=True,
    )

    session: McpSession | None = None
    pending_session: McpSession | None = None
    generation = 0
    loading = False
    running = False
    category = "Tools"
    selected_name: str | None = None
    catalog: dict[str, list[dict[str, object]]] = {name: [] for name in CATEGORIES}
    saved_snapshot: tuple[SavedConnection, ...] | None = None
    saved_use_buttons: list[ft.OutlinedButton] = []

    def refresh_saved_connections() -> None:
        """Keep mounted saved rows stable across status updates and resizes."""
        nonlocal saved_snapshot
        profiles = tuple(saved_store.list())
        if profiles == saved_snapshot:
            for button in saved_use_buttons:
                button.disabled = session is not None or loading
            return
        saved_snapshot = profiles
        saved_use_buttons.clear()
        saved_list.controls.clear()
        if not profiles:
            saved_list.controls.append(text("No saved connections yet.", 12, muted=True))
        for profile in profiles:
            use_button = ft.OutlinedButton(
                "Connect", key=f"saved-use-{profile.identifier}",
                icon=ft.Icons.LINK_OUTLINED,
                disabled=session is not None or loading,
                on_click=lambda _event=None, p=profile: use_saved_connection(p),
            )
            saved_use_buttons.append(use_button)
            saved_list.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            text(profile.url, 13, bold=True),
                            text(profile.auth_label, 11, muted=True),
                        ], spacing=3, expand=True),
                        use_button,
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_OUTLINED,
                            key=f"saved-remove-{profile.identifier}",
                            icon_color=colors.danger,
                            tooltip="Delete saved endpoint and credentials",
                            on_click=lambda _event=None, p=profile: page.run_task(
                                remove_saved_connection, p,
                            ),
                        ),
                    ], spacing=8, wrap=True),
                    padding=12, border_radius=12,
                    bgcolor=colors.raised, border=ft.Border.all(1, colors.outline),
                ),
            )
        scaler.apply(saved_list)

    def update_connection() -> None:
        connected = session is not None
        endpoint.disabled = connected or loading
        token.disabled = connected or loading or bool(browser_oauth.value)
        browser_oauth.disabled = connected or loading
        connect_button.disabled = connected or loading
        disconnect_button.disabled = not connected and not loading
        refresh_button.disabled = not connected or loading or running
        save_connection_button.disabled = not connected or loading or saving_connection
        save_connection_button.bgcolor = colors.accent if connected else colors.raised
        save_connection_button.color = colors.background if connected else colors.muted
        progress.visible = loading
        filter_box.disabled = not connected
        workspace.visible = connected
        empty_state.visible = not connected
        status.value = "Connecting…" if loading else "Connected" if connected else "Disconnected"
        status.color = colors.accent if connected else colors.muted
        progress.color = colors.accent
        refresh_saved_connections()
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

    def update_technical_visibility() -> None:
        exposed = nerd_mode and show_raw_json
        for control in schema_technical_controls + result_technical_controls:
            control.visible = exposed
        if current_tool_editor is not None:
            advanced, raw_input, form_panel, forced = current_tool_editor
            advanced.visible = nerd_mode or forced
            if not nerd_mode and not forced:
                advanced.value = False
                raw_input.visible = False
                form_panel.visible = True

    def toggle_raw_json() -> None:
        nonlocal show_raw_json
        show_raw_json = nerd_mode and raw_json_checkbox.value is True
        update_technical_visibility()
        page.update()

    raw_json_checkbox.on_change = toggle_raw_json

    def display_result(result: dict[str, object], target: ft.Column) -> None:
        result_technical_controls.clear()
        target.controls = content_views(result)
        raw_view = target.controls[-1]
        assert isinstance(raw_view, ft.ExpansionTile)
        result_technical_controls.append(raw_view)
        copy_button = ft.OutlinedButton("Copy complete JSON result", icon=ft.Icons.CONTENT_COPY_OUTLINED)
        copy_button.on_click = lambda: page.run_task(
            clipboard.set, json.dumps(result, ensure_ascii=False, indent=2, default=str),
        )
        result_technical_controls.append(copy_button)
        target.controls.append(copy_button)
        scaler.apply(target)
        update_technical_visibility()

    def result_target_is_current(target: ft.Column) -> bool:
        """Never update controls detached by switching tools during a slow call."""
        return any(control is target for control in detail_column.controls)

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
            if session is self_session and result_target_is_current(output):
                display_result(result, output)
                failed = result.get("isError") is True
                feedback.value = (
                    f"{'Remote tool error' if failed else 'Completed'} "
                    f"in {(time.perf_counter() - started) * 1000:.0f} ms"
                )
                feedback.color = ft.Colors.ERROR if failed else ft.Colors.PRIMARY
        except Exception as exc:
            if session is self_session and result_target_is_current(output):
                feedback.value = f"{type(exc).__name__}: {exc}"
                feedback.color = ft.Colors.ERROR
        finally:
            if session is self_session:
                running = False
                if result_target_is_current(output):
                    button.disabled = False
                refresh_button.disabled = False
                if category == "Logs":
                    draw_catalog()
                page.update()

    def tool_editor(item: dict[str, object]) -> list[ft.Control]:
        nonlocal current_tool_editor
        schema = _schema(item)
        fields, controls = create_fields(schema, on_change=page.update)
        for field in fields:
            tint_field(field)
        must_use_json = requires_advanced_json(schema)
        advanced = ft.Checkbox(
            label="Advanced JSON arguments", value=must_use_json,
            visible=nerd_mode or must_use_json,
        )
        raw_input = ft.TextField(label="Arguments as JSON object", value="{}",
                                 prefix_icon=ft.Icons.DATA_OBJECT_OUTLINED, multiline=True,
                                 min_lines=3, max_lines=12, visible=must_use_json)
        tint_field(raw_input)
        form_panel = ft.Column(
            fields, spacing=12, visible=not must_use_json,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        current_tool_editor = (advanced, raw_input, form_panel, must_use_json)
        feedback = ft.Text("No call yet.", selectable=True, color=ft.Colors.OUTLINE, expand=True)
        output = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        run_button = ft.FilledButton("Run tool", icon=ft.Icons.ELECTRIC_BOLT_OUTLINED)

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
        input_schema_tile = ft.ExpansionTile(
            title="Input schema", visible=nerd_mode and show_raw_json,
            leading=ft.Icon(ft.Icons.RULE_OUTLINED, color=colors.accent),
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[ft.TextField(value=preview(schema), read_only=True, multiline=True,
                                   min_lines=3, max_lines=12)],
        )
        schema_technical_controls.append(input_schema_tile)
        views.append(input_schema_tile)
        if isinstance(item.get("outputSchema"), dict):
            output_schema_tile = ft.ExpansionTile(
                title="Output schema", visible=nerd_mode and show_raw_json,
                leading=ft.Icon(ft.Icons.FACT_CHECK_OUTLINED, color=colors.accent),
                expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[ft.TextField(value=preview(item["outputSchema"]), read_only=True,
                                       multiline=True, min_lines=3, max_lines=12)],
            )
            schema_technical_controls.append(output_schema_tile)
            views.append(output_schema_tile)
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
                                     prefix_icon=argument_icon(name, "string"),
                                     hint_text=str(arg.get("description") or ""))
                tint_field(field)
                fields.append(field)
                arg_fields[name] = (field, required)
        feedback = ft.Text("No prompt retrieved.", color=ft.Colors.OUTLINE, expand=True)
        output = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        button = ft.FilledButton("Get prompt", icon=ft.Icons.QUESTION_ANSWER_OUTLINED)

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
                                 prefix_icon=ft.Icons.ALT_ROUTE_OUTLINED, value=str(uri))
        tint_field(uri_field)
        feedback = ft.Text("No resource retrieved.", color=colors.muted, expand=True)
        output = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        button = ft.FilledButton("Read resource", icon=ft.Icons.AUTO_STORIES_OUTLINED)

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
        nonlocal current_tool_editor
        detail_column.controls.clear()
        schema_technical_controls.clear()
        result_technical_controls.clear()
        current_tool_editor = None
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
        scaler.apply(detail_column)

    def draw_catalog() -> None:
        nonlocal selected_name, current_tool_editor
        list_column.controls.clear()
        detail_column.controls.clear()
        schema_technical_controls.clear()
        result_technical_controls.clear()
        current_tool_editor = None
        if session is None:
            heading.value = "Connect to browse MCP capabilities."
            navigation.controls.clear()
            scaler.apply(list_column, detail_column, navigation)
            page.update()
            return
        draw_navigation()
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
                prefix_icon=ft.Icons.TERMINAL_OUTLINED,
                read_only=True, multiline=True, min_lines=12, max_lines=25,
            )
            tint_field(log_field)
            detail_column.controls.append(log_field)

            def clear_log() -> None:
                if session is not None:
                    session.events.clear()
                    draw_catalog()
            clear_button = ft.OutlinedButton("Clear log", icon=ft.Icons.DELETE_SWEEP_OUTLINED)
            clear_button.on_click = clear_log
            list_column.controls.append(clear_button)
            scaler.apply(list_column, detail_column, navigation)
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
                icon_tile(ft.Icons.SEARCH_OFF_OUTLINED),
                text("Nothing found", 17, bold=True),
                text("Refresh discovery or try another search.", 12, muted=True),
            ])
            scaler.apply(list_column, detail_column, navigation)
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
                        ft.Icons.CHECK_CIRCLE if selected else CATEGORY_ICONS[category],
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
        scaler.apply(list_column, detail_column, navigation)
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
            saved_store.remember_discovery(
                active.url, tools=len(data["Tools"]),
                prompts=len(data["Prompts"]), resources=len(data["Resources"]),
            )
            draw_catalog()

    def use_saved_connection(profile: SavedConnection) -> None:
        """One click fills all fields and starts a new connection, never a tool."""
        if session is not None or loading:
            return
        endpoint.value = profile.url
        browser_oauth.value = profile.oauth
        token.value = profile.bearer
        save_notice.value = ""
        on_connect()

    async def save_current_connection() -> None:
        """Credentials become persistent only after this explicit user click."""
        nonlocal saving_connection
        active = session
        if active is None or loading or saving_connection:
            return
        saving_connection = True
        update_connection()
        use_oauth = bool(browser_oauth.value)
        oauth_was_saved = False
        url: str | None = None
        try:
            url = validate_endpoint(endpoint.value or "")
            if use_oauth:
                oauth_was_saved = saved_store.has_oauth_credentials(url)
                directory = saved_store.oauth_directory(url)
                await active.save_oauth_credentials(directory)
            saved_store.save(url, oauth=use_oauth, bearer=token.value or "")
        except (OSError, ValueError, RuntimeError) as exc:
            # A partially failed opt-in must not leave unlisted OAuth secrets.
            if use_oauth and url is not None and not oauth_was_saved:
                active.stop_oauth_persistence()
                try:
                    saved_store.discard_oauth_credentials(url)
                except OSError:
                    pass
            save_notice.value = f"Save failed: {exc}"
            save_notice.color = colors.danger
        else:
            save_notice.value = (
                "Saved locally. Credentials are NOT encrypted; anyone with access "
                "to your app data may read them. Use ✕ to forget."
            )
            save_notice.color = colors.accent
        finally:
            saving_connection = False
            update_connection()

    async def remove_saved_connection(profile: SavedConnection) -> None:
        """Forget saved credentials at any time, including an active login."""
        active = session
        if active is not None and (
            active.url == profile.url and bool(browser_oauth.value) == profile.oauth
        ):
            if profile.oauth:
                active.stop_oauth_persistence()
            on_disconnect()
            await active.close()
        try:
            saved_store.delete(profile)
        except OSError as exc:
            save_notice.value = f"Couldn't delete saved credentials: {exc}"
            save_notice.color = colors.danger
        else:
            save_notice.value = "Saved endpoint and its stored credentials deleted."
            save_notice.color = colors.muted
        refresh_saved_connections()
        page.update()

    async def connect_task(epoch: int, url: str, bearer: str, use_oauth: bool) -> None:
        nonlocal session, pending_session, loading, category, selected_name
        if epoch != generation:
            return
        active: McpSession | None = None
        started = time.perf_counter()
        try:
            oauth_directory = (
                saved_store.oauth_directory(url)
                if use_oauth and saved_store.has_oauth_credentials(url) else None
            )
            if oauth_directory is not None:
                active = McpSession(url, "", oauth=True, oauth_store_path=oauth_directory)
            else:
                active = McpSession(url, "" if use_oauth else bearer, oauth=use_oauth)
            pending_session = active
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
                if active is not None and session is active:
                    session = None
                draw_catalog()
        finally:
            if active is not None:
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

    def show_settings_warning(message: str) -> None:
        settings_warning.value = message
        settings_warning.visible = bool(message)
        settings_warning.color = colors.danger

    def update_text_scale() -> None:
        """Resize live text in place; preserve inputs, results and scroll positions."""
        nonlocal ui_percent, answer_percent
        ui_percent = max(100, min(180, round((ui_scale_slider.value or 100) / 10) * 10))
        answer_percent = max(100, min(180, round((answer_scale_slider.value or 100) / 10) * 10))
        scaler.update(ui_percent, answer_percent)
        ui_scale_label.value = f"{ui_percent}%"
        answer_scale_label.value = f"{answer_percent}%"
        page.theme = ft.Theme(
            use_material3=True, color_scheme_seed=colors.accent,
            text_theme=typography_theme(ui_percent),
            markdown_theme=readable_markdown_style(colors, answer_percent),
        )
        page.dark_theme = ft.Theme(
            use_material3=True, color_scheme_seed=colors.accent,
            text_theme=typography_theme(ui_percent),
            markdown_theme=readable_markdown_style(colors, answer_percent),
        )
        if desktop_rail is not None:
            desktop_rail.width = round(102 * ui_percent / 100)
            desktop_rail.min_width = round(90 * ui_percent / 100)
        if page.navigation_bar is not None:
            page.navigation_bar.height = round(80 * ui_percent / 100)
        size_workspace()
        scaler.apply(page.controls, page.navigation_bar)
        page.update()

    def persist_text_scale() -> None:
        try:
            preferences.save_text_scales(ui_percent, answer_percent)
        except OSError:
            show_settings_warning("Couldn't save text size preferences on this device.")
        else:
            show_settings_warning("")
        page.update()

    def reset_text_scale() -> None:
        ui_scale_slider.value = DEFAULT_TEXT_SCALE
        answer_scale_slider.value = DEFAULT_TEXT_SCALE
        update_text_scale()
        persist_text_scale()

    ui_scale_slider.on_change = update_text_scale
    ui_scale_slider.on_change_end = persist_text_scale
    answer_scale_slider.on_change = update_text_scale
    answer_scale_slider.on_change_end = persist_text_scale

    def set_nerd_mode(value: bool) -> None:
        """Update mounted settings and capability controls; never rebuild them."""
        nonlocal nerd_mode, show_raw_json
        nerd_mode = value
        if not nerd_mode:
            show_raw_json = False
            raw_json_checkbox.value = False
        raw_json_checkbox.visible = nerd_mode
        update_technical_visibility()
        error = ""
        try:
            preferences.save_nerd_mode(nerd_mode)
        except OSError:
            error = "Couldn't save Nerd mode on this device."
        show_settings_warning(error)
        page.update()

    def repaint_appearance(previous: Palette) -> None:
        """Recolor existing controls without removing and freezing reused widgets.

        In Flet 1.x a control removed from a view can become frozen; rebuilding
        entire pages while retaining TextFields causes runtime exceptions later.
        Update the live tree instead, preserving text, results and callbacks.
        """
        mapping = {
            getattr(previous, f.name): getattr(colors, f.name)
            for f in fields(Palette)
        }
        color_attributes = {
            "bgcolor", "color", "icon_color", "indicator_color", "divider_color",
            "border_color", "focused_border_color", "focus_color", "hover_color",
            "overlay_color", "fill_color", "selected_color", "cursor_color",
            "label_color", "floating_label_color", "disabled_color",
        }
        visited: set[int] = set()

        def recolor(node: object) -> None:
            if id(node) in visited:
                return
            if isinstance(node, (str, bytes, int, float, bool, type(None))):
                return
            visited.add(id(node))
            if isinstance(node, (list, tuple)):
                for child in node:
                    recolor(child)
            elif isinstance(node, dict):
                for child in node.values():
                    recolor(child)
            elif is_dataclass(node) and not isinstance(node, type):
                for attribute in fields(node):
                    if attribute.name.startswith("_"):
                        continue
                    current = getattr(node, attribute.name)
                    if attribute.name == "border" and isinstance(current, ft.Border):
                        sides: dict[str, ft.BorderSide] = {}
                        for edge in ("left", "top", "right", "bottom"):
                            side = getattr(current, edge)
                            if isinstance(side, ft.BorderSide):
                                original = side.color
                                new_color = (
                                    mapping.get(original, original)
                                    if isinstance(original, str) else original
                                )
                                sides[edge] = replace(side, color=new_color)
                        if sides:
                            # A fresh border value is needed for Flet's Prop
                            # tracking; nested in-place mutations may not patch.
                            setattr(node, attribute.name, replace(current, **sides))
                    elif attribute.name == "border" and isinstance(current, dict):
                        updated: dict[object, object] = {}
                        changed = False
                        for state, outline in current.items():
                            if isinstance(outline, ft.OutlineInputBorder):
                                side = outline.side
                                if isinstance(side, ft.BorderSide) and isinstance(side.color, str):
                                    new_color = mapping.get(side.color, side.color)
                                    if new_color != side.color:
                                        outline = replace(
                                            outline, side=replace(side, color=new_color),
                                        )
                                        changed = True
                            updated[state] = outline
                        if changed:
                            setattr(node, attribute.name, updated)
                    elif (
                        attribute.name in color_attributes
                        and isinstance(current, str)
                        and current in mapping
                    ):
                        setattr(node, attribute.name, mapping[current])
                    else:
                        recolor(current)

        recolor(page.controls)
        recolor(page.navigation_bar)
        for screen in (connection_view, capabilities_view, settings_view):
            recolor(screen)

        # Markdown is not a regular Text widget: its stylesheet must be
        # explicitly rebuilt for each palette and mode, even at 100% zoom.
        scaler.set_palette(colors, dark_mode=brightness == "dark")
        scaler.apply(
            page.controls, page.navigation_bar,
            connection_view, capabilities_view, settings_view,
        )

        for mode, button in appearance_buttons.items():
            active = mode == brightness
            button.content = ("Light" if mode == "light" else "Dark") + (
                " ✓" if active else ""
            )
            button.bgcolor = colors.accent_soft if active else colors.raised
            button.color = colors.accent if active else colors.foreground

        for name, tile in palette_tiles.items():
            active = name == theme_name
            tile.bgcolor = colors.accent_soft if active else colors.raised
            if isinstance(tile.title, ft.Text):
                tile.title.weight = (
                    ft.FontWeight.W_600 if active else ft.FontWeight.NORMAL
                )
                tile.title.color = colors.foreground
            if isinstance(tile.leading, ft.Container):
                tile.leading.bgcolor = PALETTES[name][brightness].accent
            if isinstance(tile.trailing, ft.Icon):
                tile.trailing.icon = (
                    ft.Icons.CHECK_CIRCLE if active
                    else ft.Icons.RADIO_BUTTON_UNCHECKED
                )
                tile.trailing.color = colors.accent if active else colors.muted

        page.bgcolor = colors.background
        page.theme_mode = (
            ft.ThemeMode.DARK if brightness == "dark" else ft.ThemeMode.LIGHT
        )
        page.theme = ft.Theme(
            use_material3=True, color_scheme_seed=colors.accent,
            text_theme=typography_theme(ui_percent),
            markdown_theme=readable_markdown_style(colors, answer_percent),
        )
        page.dark_theme = ft.Theme(
            use_material3=True, color_scheme_seed=colors.accent,
            text_theme=typography_theme(ui_percent),
            markdown_theme=readable_markdown_style(colors, answer_percent),
        )
        show_settings_warning("")
        page.update()

    def set_appearance(*, palette: str | None = None,
                       mode: str | None = None) -> None:
        """Retheme in-place; do not detach, freeze or erase any live controls."""
        nonlocal theme_name, brightness, colors
        previous = colors
        if palette is not None and palette in PALETTES:
            theme_name = palette
        if mode is not None and mode in ("light", "dark"):
            brightness = mode
        colors = PALETTES[theme_name][brightness]
        error = ""
        try:
            preferences.save(theme_name, brightness)
        except OSError:
            error = "Couldn't save appearance preferences on this device."
        repaint_appearance(previous)
        show_settings_warning(error)
        if error:
            page.update()

    def select_screen(index: int) -> None:
        nonlocal selected_tab
        screens = (connection_view, capabilities_view, settings_view)
        if not 0 <= index < len(screens):
            return
        selected_tab = index
        screen_host.content = screens[index]
        scaler.apply(screen_host)
        if desktop_rail is not None:
            desktop_rail.selected_index = index
        if page.navigation_bar is not None:
            page.navigation_bar.selected_index = index
        page.update()

    def size_workspace() -> None:
        """Pin the desktop Library while the separate details pane scrolls.

        A fixed, viewport-sized panel gives both Columns bounded scroll areas.
        On phones those bounds disappear, so the page remains one natural scroller.
        Only layout properties change; no mounted controls are replaced.
        """
        # The navigation rail takes 102px and the body has 44px of padding.
        # A >=920px window leaves enough room for ResponsiveRow's 768px
        # two-column breakpoint. Below that, let the panels stack and page-scroll.
        rail_extra = max(0, round(102 * ui_percent / 100) - 102)
        side_by_side = (page.width or 430) >= 920 + rail_extra
        pane_height = max(220, (page.height or 690) - 330) if side_by_side else None
        if library_surface is not None:
            library_surface.height = pane_height
        if details_surface is not None:
            details_surface.height = pane_height
        if library_contents is not None:
            library_contents.expand = side_by_side
        list_column.expand = side_by_side
        list_column.scroll = ft.ScrollMode.AUTO if side_by_side else None
        detail_column.expand = side_by_side
        detail_column.scroll = ft.ScrollMode.AUTO if side_by_side else None

    def resize_layout() -> None:
        """Resize the existing tree; never reattach input fields or result widgets."""
        wide = (page.width or 430) >= 860
        if desktop_rail is not None:
            desktop_rail.visible = wide
            desktop_rail.height = page.height or 690
        if page.navigation_bar is not None:
            page.navigation_bar.visible = not wide
        if header_symbol is not None:
            header_symbol.visible = (page.width or 430) >= 600
        size_workspace()
        page.update()

    def build_ui() -> None:
        """Use watch-style tonal surfaces and one page-level scrollable layout."""
        nonlocal workspace, empty_state, input_borders, desktop_rail, header_symbol
        nonlocal library_surface, details_surface, library_contents
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
        page.theme = ft.Theme(
            use_material3=True, color_scheme_seed=colors.accent,
            text_theme=typography_theme(ui_percent),
            markdown_theme=readable_markdown_style(colors, answer_percent),
        )
        page.dark_theme = ft.Theme(
            use_material3=True, color_scheme_seed=colors.accent,
            text_theme=typography_theme(ui_percent),
            markdown_theme=readable_markdown_style(colors, answer_percent),
        )

        compact_header = (page.width or 430) < 600
        # Unlike the original two-screen layout, appearance lives on Settings
        # just as it does in the I-Bought-My-Watch app.
        page.appbar = None
        header_symbol = icon_tile(ft.Icons.POLYMER_OUTLINED, tinted=True, size=25)
        header_symbol.visible = not compact_header
        identity_controls: list[ft.Control] = [header_symbol]
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
            ], key="app-header", spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=13, radius=16,
        )

        display_modes: list[ft.Control] = []
        appearance_buttons.clear()
        palette_tiles.clear()
        for label, mode, icon in (
            ("Light", "light", ft.Icons.WB_SUNNY_OUTLINED),
            ("Dark", "dark", ft.Icons.NIGHTLIGHT_OUTLINED),
        ):
            selected = mode == brightness
            button = ft.FilledTonalButton(
                label + (" ✓" if selected else ""),
                key=f"mode-{mode}",
                icon=icon,
                bgcolor=colors.accent_soft if selected else colors.raised,
                color=colors.accent if selected else colors.foreground,
                on_click=lambda _event=None, mode=mode: set_appearance(mode=mode),
            )
            appearance_buttons[mode] = button
            display_modes.append(button)

        palette_options: list[ft.Control] = []
        for name in PALETTES:
            selected = name == theme_name
            tile = ft.ListTile(
                key=f"palette-{name.lower()}",
                title=text(name, 14, bold=selected),
                leading=ft.Container(
                    width=26, height=26, border_radius=99,
                    bgcolor=PALETTES[name][brightness].accent,
                ),
                trailing=ft.Icon(
                    ft.Icons.CHECK_CIRCLE if selected
                    else ft.Icons.RADIO_BUTTON_UNCHECKED,
                    color=colors.accent if selected else colors.muted,
                ),
                bgcolor=colors.accent_soft if selected else colors.raised,
                on_click=lambda _event, name=name: set_appearance(palette=name),
                dense=True,
            )
            palette_tiles[name] = tile
            palette_options.append(tile)

        nerd_checkbox = ft.Checkbox(
            key="nerd-mode", label="Nerd mode", value=nerd_mode,
            on_change=lambda: set_nerd_mode(bool(nerd_checkbox.value)),
        )
        settings_controls: list[ft.Control] = [
            ft.Row([
                icon_tile(ft.Icons.SETTINGS_SUGGEST_OUTLINED),
                ft.Column([
                    text("Settings", 18, bold=True),
                    text("Customize your MCP playground.", 12, muted=True),
                ], spacing=3, expand=True),
            ], spacing=12),
            panel(ft.Column([
                ft.Row([
                    icon_tile(ft.Icons.MODEL_TRAINING_OUTLINED, size=19),
                    text("Developer options", 16, bold=True),
                ], spacing=10),
                nerd_checkbox,
                text(
                    "Off by default. Enable to reveal the Show raw JSON checkbox "
                    "in Capabilities and optional advanced tool inputs.",
                    12, muted=True,
                ),
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                padding=18),
            panel(ft.Column([
                ft.Row([
                    icon_tile(ft.Icons.TEXT_FIELDS_OUTLINED, size=19),
                    text("Text & readability", 16, bold=True),
                ], spacing=10),
                text("Interface text size", 13, bold=True),
                ft.Row([ui_scale_slider, ui_scale_label], spacing=8),
                text("Enlarge menus, tool names, forms, labels, and navigation.",
                     12, muted=True),
                ft.Divider(height=1, color=colors.outline),
                text("Answer text size", 13, bold=True),
                ft.Row([answer_scale_slider, answer_scale_label], spacing=8),
                text("Make Markdown answers, headings, lists, and code easier to read.",
                     12, muted=True),
                ft.Container(
                    content=ft.Column([
                        text("Live preview · readable at a glance", 14, bold=True),
                        ft.Text("The quick brown fox jumps over the lazy dog.",
                                key="text-scale-preview", selectable=True),
                        ft.Markdown(
                            "## Answer preview\n\n- Clear, readable MCP responses",
                            key="answer-scale-preview", selectable=True,
                        ),
                    ], spacing=7),
                    padding=12, border_radius=12, bgcolor=colors.raised,
                ),
                ft.OutlinedButton(
                    "Reset text sizes", key="reset-text-scales",
                    icon=ft.Icons.SETTINGS_BACKUP_RESTORE_OUTLINED,
                    on_click=lambda _event=None: reset_text_scale(),
                ),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                padding=18),
            panel(ft.Column([
                ft.Row([
                    icon_tile(ft.Icons.GRADIENT_OUTLINED, size=19),
                    text("Appearance", 16, bold=True),
                ], spacing=10),
                text("Display mode", 13, bold=True),
                ft.Row(display_modes, spacing=8, wrap=True, run_spacing=8),
                ft.Divider(height=1, color=colors.outline),
                text("Color palette", 13, bold=True),
                ft.Column(
                    palette_options, spacing=6,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                ft.OutlinedButton(
                    "Reset to default appearance",
                    key="reset-appearance",
                    icon=ft.Icons.SETTINGS_BACKUP_RESTORE_OUTLINED,
                    on_click=lambda _event=None: set_appearance(
                        palette=DEFAULT_PALETTE, mode=DEFAULT_BRIGHTNESS,
                    ),
                ),
            ], spacing=13, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                padding=18),
            panel(ft.Column([
                ft.Row([
                    icon_tile(ft.Icons.FINGERPRINT_OUTLINED, size=19),
                    text("About", 16, bold=True),
                ], spacing=10),
                text("MCP User UI · human-operated MCP client", 13),
                text(
                    "Appearance and Nerd mode are saved locally when app storage "
                    "is available. Raw JSON viewing is off at every launch. "
                    "Server URLs and bearer tokens are never saved in preferences.",
                    12, muted=True,
                ),
            ], spacing=11, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                padding=18),
        ]
        settings_controls.insert(2, settings_warning)
        settings_view.controls = settings_controls

        for field in (endpoint, token, filter_box):
            tint_field(field)
        connect_button.bgcolor = colors.accent
        connect_button.color = colors.background
        connect_button.icon_color = colors.background
        status.color = colors.accent if session is not None else colors.muted
        connection_detail.color = colors.muted
        progress.color = colors.accent
        heading.color = colors.foreground

        connection_card = panel(
            ft.Column([
                ft.Row([
                    icon_tile(ft.Icons.SENSORS_OUTLINED),
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
                ft.Divider(height=1, color=colors.outline),
                ft.Row([
                    icon_tile(ft.Icons.BOOKMARKS_OUTLINED, size=19),
                    text("Saved connections", 16, bold=True),
                ], spacing=10),
                save_connection_button,
                text(
                    "Credentials save ONLY when you press the button after "
                    "connecting. Saved bearer and OAuth tokens are local plaintext "
                    "in app-private DATA, not encrypted; never on shared machines. "
                    "Deleting an active profile disconnects it.",
                    12, muted=True,
                ),
                saved_list,
                save_notice,
                connection_detail,
            ], spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=20,
        )
        connection_card.key = "connection-card"
        refresh_saved_connections()

        empty_state = panel(
            ft.Row([
                icon_tile(ft.Icons.SCHEMA_OUTLINED, size=28),
                ft.Column([
                    text("Your workspace is ready", 17, bold=True),
                    text("Connect to an MCP endpoint to reveal its tools, prompts and resources.",
                         12, muted=True),
                ], spacing=5, expand=True),
            ], spacing=16),
            padding=24,
        )
        empty_state.visible = session is None

        # Each desktop pane owns its scrolling; the Library stays visible while
        # a long result scrolls on the right. The Library header itself is fixed.
        library_contents = ft.Column([
            ft.Row([
                icon_tile(ft.Icons.DYNAMIC_FEED_OUTLINED, size=19),
                ft.Column([
                    text("Library", 15, bold=True),
                    text("Discovered items", 11, muted=True),
                ], spacing=3),
            ], spacing=10),
            ft.Divider(height=1, color=colors.outline),
            list_column,
        ], spacing=13, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        library_surface = panel(library_contents, padding=14)
        details_surface = panel(detail_column, padding=20)
        workspace = ft.ResponsiveRow([
            ft.Container(
                content=library_surface,
                col={"xs": 12, "sm": 12, "md": 4, "lg": 4},
            ),
            ft.Container(
                content=details_surface,
                col={"xs": 12, "sm": 12, "md": 8, "lg": 8},
            ),
        ], key="capabilities-workspace", spacing=12, run_spacing=12,
            visible=session is not None)
        size_workspace()

        connection_view.controls = [connection_card]
        capabilities_view.controls = [
            ft.Row([
                icon_tile(ft.Icons.DATA_EXPLORATION_OUTLINED),
                ft.Column([
                    text("Capabilities", 18, bold=True),
                    text("Only what your server actually advertises.", 12, muted=True),
                ], spacing=3, expand=True),
            ], spacing=12),
            navigation,
            raw_json_checkbox,
            heading,
            filter_box,
            empty_state,
            workspace,
        ]
        screen_host.content = (connection_view, capabilities_view, settings_view)[selected_tab]
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
            ("Connection", *NAVIGATION_ICONS["Connection"]),
            ("Capabilities", *NAVIGATION_ICONS["Capabilities"]),
            ("Settings", *NAVIGATION_ICONS["Settings"]),
        )
        page.navigation_bar = ft.NavigationBar(
            key="screen-navigation-mobile", selected_index=selected_tab,
            destinations=[ft.NavigationBarDestination(label=label, icon=icon, selected_icon=selected)
                          for label, icon, selected in destinations],
            on_change=lambda event: select_screen(event.control.selected_index or 0),
            bgcolor=colors.surface, indicator_color=colors.accent_soft,
            height=round(80 * ui_percent / 100), visible=not wide,
        )
        desktop_rail = ft.NavigationRail(
            key="screen-navigation-wide",
            width=round(102 * ui_percent / 100),
            min_width=round(90 * ui_percent / 100),
            height=page.height or 690, selected_index=selected_tab,
            destinations=[ft.NavigationRailDestination(label=label, icon=icon, selected_icon=selected)
                          for label, icon, selected in destinations],
            label_type=ft.NavigationRailLabelType.ALL,
            on_change=lambda event: select_screen(event.control.selected_index or 0),
            bgcolor=colors.surface,
            visible=wide,
        )
        layout = ft.Row(
            [desktop_rail, body], spacing=0, expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        scaler.apply(layout, page.navigation_bar)
        page.add(ft.SafeArea(content=layout, expand=True))

    save_connection_button.on_click = lambda _event=None: page.run_task(
        save_current_connection,
    )
    connect_button.on_click = on_connect
    disconnect_button.on_click = on_disconnect
    refresh_button.on_click = lambda: page.run_task(refresh_discovery, session) if session else None
    filter_box.on_change = draw_catalog
    browser_oauth.on_change = update_connection
    page.on_resize = lambda _event: resize_layout()

    build_ui()


MAX_LOG_CHARS = 120_000
