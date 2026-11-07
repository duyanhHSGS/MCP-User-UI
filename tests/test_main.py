"""Build the real Flet widget tree without a remote server or GUI runtime."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import flet as ft

from app import main
from ui_theme import DEFAULT_PALETTE, PALETTES


class FakePage:
    """Only the page attributes needed during synchronous app initialization."""

    def __init__(self) -> None:
        self.window = SimpleNamespace()
        self.scroll: ft.ScrollMode | None = None
        self.theme: ft.Theme | None = None
        self.dark_theme: ft.Theme | None = None
        self.bgcolor: str | None = None
        self.theme_mode: ft.ThemeMode = ft.ThemeMode.SYSTEM
        self.appbar: ft.AppBar | None = None
        self.services: list[ft.Control] = []
        self.controls: list[ft.Control] = []

    def add(self, control: ft.Control) -> None:
        self.controls.append(control)

    def update(self) -> None:
        """Only the UI tree is being inspected; no Flutter client is needed."""


def test_starts_with_a_safe_disconnected_interface() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
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


def test_palette_and_light_mode_update_real_material_3_surfaces() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    root = cast(ft.Column, page.controls[0])
    header = cast(ft.ResponsiveRow, cast(ft.Container, root.controls[0]).content)
    header_actions = cast(ft.Row, cast(ft.Container, header.controls[1]).content)
    palette_dropdown = header_actions.controls[0]
    assert isinstance(palette_dropdown, ft.Dropdown)
    palette_dropdown.value = "Ember"
    assert palette_dropdown.on_select is not None
    cast(Callable[[], None], palette_dropdown.on_select)()
    assert page.bgcolor == PALETTES["Ember"]["dark"].background

    root = cast(ft.Column, page.controls[0])
    header = cast(ft.ResponsiveRow, cast(ft.Container, root.controls[0]).content)
    header_actions = cast(ft.Row, cast(ft.Container, header.controls[1]).content)
    mode_button = header_actions.controls[1]
    assert isinstance(mode_button, ft.IconButton)
    assert mode_button.on_click is not None
    cast(Callable[[], None], mode_button.on_click)()
    assert page.bgcolor == PALETTES["Ember"]["light"].background
    assert page.theme_mode == ft.ThemeMode.LIGHT
