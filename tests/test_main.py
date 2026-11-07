"""Build the real Flet widget tree without a remote server or GUI runtime."""

from collections.abc import Callable
from typing import cast

import flet as ft
import pytest

from app import main
from tests.ui_helpers import FakePage
from ui_theme import DEFAULT_PALETTE, PALETTES


def test_starts_with_a_safe_disconnected_interface() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    assert page.update_count == 1
    assert len(page.controls) == 1
    assert isinstance(page.controls[0], ft.Column)
    root = page.controls[0]
    assert len(root.controls) >= 6
    assert page.scroll == ft.ScrollMode.AUTO
    assert page.theme is not None and page.theme.use_material3 is True
    assert page.dark_theme is not None and page.dark_theme.use_material3 is True
    assert page.bgcolor == PALETTES[DEFAULT_PALETTE]["dark"].background
    assert page.appbar is None  # Toolbar is visible inside the scrollable body.
    assert page.theme_mode == ft.ThemeMode.DARK
    assert isinstance(root.controls[1], ft.Container)
    connection = root.controls[1].content
    assert isinstance(connection, ft.Column)
    assert isinstance(connection.controls[1], ft.TextField)
    assert "Explore. Test. Understand." not in repr(root)
    workspace = root.controls[-1]
    assert isinstance(workspace, ft.ResponsiveRow)
    assert not workspace.visible
    assert not workspace.expand
    assert not any(isinstance(control, ft.VerticalDivider) for control in workspace.controls)


@pytest.mark.parametrize("palette", PALETTES)
def test_palette_and_light_mode_update_real_material_3_surfaces(palette: str) -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    root = cast(ft.Column, page.controls[0])
    header = cast(ft.ResponsiveRow, cast(ft.Container, root.controls[0]).content)
    header_actions = cast(ft.Row, cast(ft.Container, header.controls[1]).content)
    palette_dropdown = header_actions.controls[0]
    assert isinstance(palette_dropdown, ft.Dropdown)
    palette_dropdown.value = palette
    assert palette_dropdown.on_select is not None
    cast(Callable[[], None], palette_dropdown.on_select)()
    assert page.bgcolor == PALETTES[palette]["dark"].background

    root = cast(ft.Column, page.controls[0])
    header = cast(ft.ResponsiveRow, cast(ft.Container, root.controls[0]).content)
    header_actions = cast(ft.Row, cast(ft.Container, header.controls[1]).content)
    mode_button = header_actions.controls[1]
    assert isinstance(mode_button, ft.IconButton)
    assert mode_button.on_click is not None
    cast(Callable[[], None], mode_button.on_click)()
    assert page.bgcolor == PALETTES[palette]["light"].background
    assert page.theme_mode == ft.ThemeMode.LIGHT
