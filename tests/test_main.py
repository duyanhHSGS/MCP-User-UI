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


@pytest.mark.parametrize("width", [None, 0, 320, 360, 440, 859, 860, 1080])
def test_search_and_discovery_fill_the_capabilities_screen(width: float | None) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    select_screen(page, 1)
    view = find_control(page, "capabilities-view")
    search = find_control(page, "capability-search")
    workspace = find_control(page, "capabilities-workspace")
    assert isinstance(view, ft.Column)
    assert view.horizontal_alignment == ft.CrossAxisAlignment.STRETCH
    assert view.width is None
    assert isinstance(search, ft.TextField)
    assert search.width is None and not search.expand
    assert search.label == "Search capabilities"
    assert search.prefix_icon == ft.Icons.SEARCH
    assert search.disabled
    assert isinstance(workspace, ft.ResponsiveRow)
    assert workspace.width is None
    introduction = view.controls[0]
    assert isinstance(introduction, ft.Row)
    assert introduction.controls[-1].expand
    empty = view.controls[-2]
    assert isinstance(empty, ft.Container)
    assert empty.visible and empty.width is None
    assert isinstance(empty.content, ft.Row)
    assert not empty.content.wrap
    assert empty.content.controls[-1].expand
    library = workspace.controls[0]
    assert isinstance(library, ft.Container)
    assert isinstance(library.content, ft.Container)
    assert isinstance(library.content.content, ft.Column)
    assert library.content.content.horizontal_alignment == ft.CrossAxisAlignment.STRETCH


@pytest.mark.parametrize("palette", PALETTES)
def test_settings_palette_and_light_mode_update_real_material_3_surfaces(palette: str) -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    select_screen(page, 2)
    settings = cast(ft.Column, find_control(page, "settings-view"))
    assert settings.horizontal_alignment == ft.CrossAxisAlignment.STRETCH
    option = cast(ft.ListTile, find_control(page, f"palette-{palette.lower()}"))
    assert option.on_click is not None
    cast(Callable[[object], None], option.on_click)(None)
    assert page.bgcolor == PALETTES[palette]["dark"].background
    assert page.theme_mode == ft.ThemeMode.DARK

    light = cast(ft.FilledTonalButton, find_control(page, "mode-light"))
    assert light.on_click is not None
    cast(Callable[[object], None], light.on_click)(None)
    assert page.bgcolor == PALETTES[palette]["light"].background
    assert page.theme_mode == ft.ThemeMode.LIGHT
    option = cast(ft.ListTile, find_control(page, f"palette-{palette.lower()}"))
    assert isinstance(option.trailing, ft.Icon)
    assert option.trailing.icon == ft.Icons.CHECK_CIRCLE


@pytest.mark.parametrize("width", [None, 0, 320, 360, 440, 599, 600, 859, 860, 1080])
@pytest.mark.parametrize("screen", [0, 1, 2])
def test_header_is_simple_and_settings_owns_appearance(
    width: float | None, screen: int,
) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    select_screen(page, screen)

    header = find_control(page, "app-header")
    identity = find_control(page, "app-identity")
    name = find_control(page, "app-name")
    assert isinstance(header, ft.Row)
    assert isinstance(identity, ft.Row)
    assert isinstance(name, ft.Text)
    assert header.controls == [identity]
    assert not header.wrap
    assert identity.expand
    assert identity.controls[-1] is name
    assert name.value == "MCP User UI"
    assert name.expand and name.no_wrap and name.max_lines == 1
    assert name.overflow == ft.TextOverflow.ELLIPSIS
    assert len(identity.controls) == 2
    assert isinstance(identity.controls[0], ft.Container)
    assert identity.controls[0].visible == ((width or 430) >= 600)
    with pytest.raises(AssertionError, match="not attached"):
        find_control(page, "appearance-actions")
    assert not any(
        isinstance(control, ft.Text) and control.value == "PLAYGROUND / INSPECTOR"
        for control in walk_controls(page.controls)
    )


@pytest.mark.parametrize("palette", PALETTES)
def test_settings_theme_controls_work_across_resize_and_screen_changes(palette: str) -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://example.net/mcp"
    select_screen(page, 2)

    for width in (320, 600, 1080, 440):
        page.width = width
        assert page.on_resize is not None
        page.on_resize(None)
        option = cast(ft.ListTile, find_control(page, f"palette-{palette.lower()}"))
        assert option.on_click is not None
        cast(Callable[[object], None], option.on_click)(None)
        for mode in ("light", "dark"):
            button = cast(ft.FilledTonalButton, find_control(page, f"mode-{mode}"))
            assert button.on_click is not None
            cast(Callable[[object], None], button.on_click)(None)
            assert page.bgcolor == PALETTES[palette][mode].background
            assert find_control(page, "settings-view") is not None
            assert cast(ft.Column, find_control(page, "page-body")).expand
    select_screen(page, 1)
    assert find_control(page, "capabilities-view") is not None
    select_screen(page, 0)
    assert find_control(page, "endpoint") is endpoint
    assert endpoint.value == "https://example.net/mcp"


def test_settings_reset_appearance_to_defaults() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    select_screen(page, 2)
    option = cast(ft.ListTile, find_control(page, "palette-ember"))
    assert option.on_click is not None
    cast(Callable[[object], None], option.on_click)(None)
    light = cast(ft.FilledTonalButton, find_control(page, "mode-light"))
    assert light.on_click is not None
    cast(Callable[[object], None], light.on_click)(None)

    reset = cast(ft.OutlinedButton, find_control(page, "reset-appearance"))
    assert reset.on_click is not None
    cast(Callable[[object], None], reset.on_click)(None)
    assert page.bgcolor == PALETTES[DEFAULT_PALETTE]["dark"].background
    assert page.theme_mode == ft.ThemeMode.DARK
    assert find_control(page, "settings-view") is not None



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
def test_three_tabs_are_separate_responsive_screens(width: float | None) -> None:
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
    select_screen(page, 2)
    assert find_control(page, "settings-view") is not None
    with pytest.raises(AssertionError, match="not attached"):
        find_control(page, "connection-card")
    with pytest.raises(AssertionError, match="not attached"):
        find_control(page, "capabilities-view")
    select_screen(page, 0)
    assert find_control(page, "connection-card") is not None
    nav = find_control(
        page, "screen-navigation-wide" if (width or 430) >= 860
        else "screen-navigation-mobile",
    )
    assert isinstance(nav, (ft.NavigationRail, ft.NavigationBar))
    assert len(nav.destinations) == 3


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



@pytest.mark.parametrize("width", [320, 430, 1080])
def test_nerd_mode_is_first_settings_card_on_mobile(width: float) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    select_screen(page, 2)
    settings = cast(ft.Column, find_control(page, "settings-view"))
    card = settings.controls[1]
    assert isinstance(card, ft.Container)
    assert any(
        isinstance(child, ft.Text) and child.value == "Developer options"
        for child in walk_controls(card)
    )
    checkbox = cast(ft.Checkbox, find_control(page, "nerd-mode"))
    assert checkbox.value is False
    select_screen(page, 1)
    raw = cast(ft.Checkbox, find_control(page, "show-raw-json"))
    assert not raw.visible and not raw.value



@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("palette", PALETTES)
def test_settings_and_resizing_retain_the_original_mounted_root(
    mode: str, palette: str,
) -> None:
    """Do not remove+re-add retained controls: Flet freezes them after removal."""
    page = FakePage()
    main(cast(ft.Page, page))
    root = page.controls[0]
    original_navigation = page.navigation_bar
    assert root is not None and original_navigation is not None
    select_screen(page, 0)
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://example.org/mcp"
    select_screen(page, 2)
    settings = cast(ft.Column, find_control(page, "settings-view"))
    appearance_panel = cast(ft.Container, settings.controls[3])
    # The settings tree has developer options before appearance.
    assert isinstance(appearance_panel.content, ft.Column)

    option = cast(ft.ListTile, find_control(page, f"palette-{palette.lower()}"))
    assert option.on_click is not None
    cast(Callable[[object], None], option.on_click)(None)
    button = cast(ft.FilledTonalButton, find_control(page, f"mode-{mode}"))
    assert button.on_click is not None
    cast(Callable[[object], None], button.on_click)(None)

    for width in (320, 600, 859, 860, 1080, 440):
        page.width = width
        assert page.on_resize is not None
        page.on_resize(None)
        assert page.controls == [root]
        assert page.controls[0] is root
        assert page.navigation_bar is original_navigation
        rail = cast(ft.NavigationRail, find_control(page, "screen-navigation-wide"))
        assert rail.visible == (width >= 860)
        assert original_navigation.visible == (width < 860)
        icon = cast(ft.Row, find_control(page, "app-identity")).controls[0]
        assert isinstance(icon, ft.Container)
        assert icon.visible == (width >= 600)

    assert page.theme_mode == (
        ft.ThemeMode.LIGHT if mode == "light" else ft.ThemeMode.DARK
    )
    assert page.bgcolor == PALETTES[palette][mode].background
    card_border = appearance_panel.border
    assert isinstance(card_border, ft.Border)
    assert card_border.top.color == PALETTES[palette][mode].outline
    select_screen(page, 0)
    assert find_control(page, "endpoint") is endpoint
    assert endpoint.value == "https://example.org/mcp"


def test_nerd_mode_toggles_do_not_replace_root_or_existing_connection_state() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    root = page.controls[0]
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://example.net/mcp"
    select_screen(page, 2)
    nerd = cast(ft.Checkbox, find_control(page, "nerd-mode"))
    for value in (True, False, True, False):
        nerd.value = value
        assert nerd.on_change is not None
        cast(Callable[[], None], nerd.on_change)()
        assert page.controls[0] is root
    select_screen(page, 0)
    assert find_control(page, "endpoint") is endpoint
    assert endpoint.value == "https://example.net/mcp"
