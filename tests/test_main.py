"""Build the real Flet widget tree without a remote server or GUI runtime."""

from collections.abc import Callable
from typing import cast

import flet as ft
import pytest

from app import main
from tests.ui_helpers import FakePage, find_control, select_screen, walk_controls
from ui_theme import DEFAULT_PALETTE, PALETTES


def test_starts_with_a_safe_disconnected_interface() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    assert page.update_count == 1
    assert len(page.controls) == 1
    assert isinstance(page.controls[0], ft.SafeArea)
    assert page.scroll == ft.ScrollMode.HIDDEN
    assert page.theme is not None and page.theme.use_material3 is True
    assert page.dark_theme is not None and page.dark_theme.use_material3 is True
    assert page.bgcolor == PALETTES[DEFAULT_PALETTE]["dark"].background
    assert page.appbar is None  # Toolbar is visible inside the scrollable body.
    assert page.theme_mode == ft.ThemeMode.DARK
    connection_card = find_control(page, "connection-card")
    assert isinstance(connection_card, ft.Container)
    connection = connection_card.content
    assert isinstance(connection, ft.Column)
    assert isinstance(connection.controls[1], ft.TextField)
    assert "Explore. Test. Understand." not in repr(page.controls)
    select_screen(page, 1)
    workspace = find_control(page, "capabilities-workspace")
    assert isinstance(workspace, ft.ResponsiveRow)
    assert not workspace.visible
    assert not workspace.expand
    assert not any(isinstance(control, ft.VerticalDivider) for control in workspace.controls)


@pytest.mark.parametrize("palette", PALETTES)
def test_palette_and_light_mode_update_real_material_3_surfaces(palette: str) -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    header_actions = cast(ft.Row, find_control(page, "appearance-actions"))
    palette_dropdown = header_actions.controls[0]
    assert isinstance(palette_dropdown, ft.Dropdown)
    palette_dropdown.value = palette
    assert palette_dropdown.on_select is not None
    cast(Callable[[], None], palette_dropdown.on_select)()
    assert page.bgcolor == PALETTES[palette]["dark"].background

    header_actions = cast(ft.Row, find_control(page, "appearance-actions"))
    mode_button = header_actions.controls[1]
    assert isinstance(mode_button, ft.IconButton)
    assert mode_button.on_click is not None
    cast(Callable[[], None], mode_button.on_click)()
    assert page.bgcolor == PALETTES[palette]["light"].background
    assert page.theme_mode == ft.ThemeMode.LIGHT


@pytest.mark.parametrize("width", [None, 0, 320, 360, 440, 599, 600, 859, 860, 1080])
@pytest.mark.parametrize("screen", [0, 1])
def test_header_keeps_appearance_at_the_right_of_the_app_name(
    width: float | None, screen: int,
) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    select_screen(page, screen)

    header = find_control(page, "app-header")
    identity = find_control(page, "app-identity")
    name = find_control(page, "app-name")
    actions = find_control(page, "appearance-actions")
    assert isinstance(header, ft.Row)
    assert isinstance(identity, ft.Row)
    assert isinstance(name, ft.Text)
    assert isinstance(actions, ft.Row)
    assert header.controls[0] is identity
    assert header.controls[-1] is actions
    assert not header.wrap
    assert identity.expand
    assert identity.controls[-1] is name
    assert name.value == "MCP User UI"
    assert name.expand and name.no_wrap and name.max_lines == 1
    assert name.overflow == ft.TextOverflow.ELLIPSIS
    assert actions.tight and not actions.expand and not actions.wrap
    assert actions.alignment == ft.MainAxisAlignment.END
    dropdown = actions.controls[0]
    assert isinstance(dropdown, ft.Dropdown)
    compact = (width or 430) < 600
    assert dropdown.width == (124 if compact else 138)
    assert len(identity.controls) == (1 if compact else 2)
    assert not any(
        isinstance(control, ft.Text) and control.value == "PLAYGROUND / INSPECTOR"
        for control in walk_controls(page.controls)
    )


@pytest.mark.parametrize("palette", PALETTES)
def test_header_theme_controls_work_across_resize_and_screen_changes(palette: str) -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://example.net/mcp"
    select_screen(page, 1)

    for width in (320, 600, 1080, 440):
        page.width = width
        assert page.on_resize is not None
        page.on_resize(None)
        actions = cast(ft.Row, find_control(page, "appearance-actions"))
        dropdown = cast(ft.Dropdown, actions.controls[0])
        dropdown.value = palette
        assert dropdown.on_select is not None
        cast(Callable[[], None], dropdown.on_select)()
        for mode in ("light", "dark"):
            actions = cast(ft.Row, find_control(page, "appearance-actions"))
            button = cast(ft.IconButton, actions.controls[1])
            assert button.on_click is not None
            cast(Callable[[], None], button.on_click)()
            assert page.bgcolor == PALETTES[palette][mode].background
            assert find_control(page, "capabilities-view") is not None
            header = cast(ft.Row, find_control(page, "app-header"))
            assert header.controls[-1] is find_control(page, "appearance-actions")
    select_screen(page, 0)
    assert find_control(page, "endpoint") is endpoint
    assert endpoint.value == "https://example.net/mcp"


def test_control_walker_visits_nested_controls_without_following_runtime_links() -> None:
    text = ft.Text("Nested")
    field = ft.TextField("Input")
    row = ft.Row([text])
    container = ft.Container(content=row)
    controls = list(walk_controls({"nested": (container, [field])}))
    assert [id(control) for control in controls] == [id(container), id(row), id(text), id(field)]
    assert list(walk_controls(None)) == []
    assert list(walk_controls("Not a control")) == []


def test_fake_page_updates_validate_the_actual_outbound_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    validated: list[ft.Control] = []
    monkeypatch.setattr("tests.ui_helpers.validate", validated.append)
    page = FakePage()
    text = ft.Text("Nested")
    row = ft.Row([text])
    page.add(row)
    assert [id(control) for control in validated] == [id(row), id(text)]
    assert page.update_count == 1


@pytest.mark.parametrize("width", [None, 0, 360, 859, 860, 1200])
def test_connection_and_capabilities_are_separate_responsive_screens(width: float | None) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    assert find_control(page, "connection-card") is not None
    with pytest.raises(AssertionError, match="not attached"):
        find_control(page, "capabilities-view")
    assert page.navigation_bar is not None
    assert page.navigation_bar.visible == ((width or 430) < 860)
    body = find_control(page, "page-body")
    assert isinstance(body, ft.Column)
    assert body.expand and body.scroll == ft.ScrollMode.AUTO
    if (width or 430) >= 860:
        assert isinstance(find_control(page, "screen-navigation-wide"), ft.NavigationRail)
    select_screen(page, 1)
    assert find_control(page, "capabilities-view") is not None
    with pytest.raises(AssertionError, match="not attached"):
        find_control(page, "connection-card")
    select_screen(page, 0)
    assert find_control(page, "connection-card") is not None


@pytest.mark.parametrize("width", [360, 1080])
def test_resize_preserves_selected_screen_and_connection_input(width: float) -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://example.net/mcp"
    select_screen(page, 1)
    page.width = width
    assert page.on_resize is not None
    page.on_resize(None)
    assert find_control(page, "capabilities-view") is not None
    select_screen(page, 0)
    assert find_control(page, "endpoint") is endpoint
    assert endpoint.value == "https://example.net/mcp"


def test_browser_login_disables_bearer_input_without_erasing_it() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    token = cast(ft.TextField, find_control(page, "bearer-token"))
    oauth = cast(ft.Checkbox, find_control(page, "browser-oauth"))
    token.value = "existing-bearer"
    assert not token.disabled
    assert oauth.on_change is not None
    for enabled in (True, False):
        oauth.value = enabled
        cast(Callable[[], None], oauth.on_change)()
        assert token.disabled == enabled
        assert token.value == "existing-bearer"
