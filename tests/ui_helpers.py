"""Shared page double for tests that inspect real Flet controls."""

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import fields, is_dataclass
from types import SimpleNamespace
from typing import cast

import flet as ft
from flet.utils.validation import validate


def walk_controls(value: object) -> Iterator[ft.Control]:
    """Visit controls inside public dataclass fields without following runtime links."""
    if isinstance(value, ft.Control):
        yield value
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            if not field.name.startswith("_"):
                yield from walk_controls(getattr(value, field.name))
    elif isinstance(value, dict):
        for child in value.values():
            yield from walk_controls(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk_controls(child)


class FakePage:
    """Keep page state and scheduled callbacks without a Flutter backend."""

    def __init__(self) -> None:
        self.window = SimpleNamespace()
        self.title = ""
        self.padding = 0
        self.width: float | None = 1080
        self.height: float | None = 690
        self.scroll: ft.ScrollMode | None = None
        self.theme: ft.Theme | None = None
        self.dark_theme: ft.Theme | None = None
        self.bgcolor: str | None = None
        self.theme_mode = ft.ThemeMode.SYSTEM
        self.appbar: ft.AppBar | None = None
        self.navigation_bar: ft.NavigationBar | None = None
        self.dialog: ft.AlertDialog | None = None
        self.on_resize: Callable[[object], None] | None = None
        self.services: list[ft.Control] = []
        self.controls: list[ft.Control] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.update_count = 0

    def add(self, control: ft.Control) -> None:
        self.controls.append(control)
        self.update()  # Real Page.add() already sends an update.

    def update(self) -> None:
        for control in walk_controls([
            self.controls, self.services, self.navigation_bar, self.dialog,
        ]):
            validate(control)  # Flet checks deprecated fields when sending updates.
        self.update_count += 1

    def show_dialog(self, dialog: ft.AlertDialog) -> None:
        self.dialog = dialog
        self.update()

    def pop_dialog(self) -> None:
        self.dialog = None
        self.update()

    def run_task(
        self, handler: Callable[..., Coroutine[object, object, None]], *args: object
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(handler(*args))
        self.tasks.append(task)
        return task


def find_control(page: FakePage, key: str) -> ft.Control:
    for control in walk_controls([page.controls, page.navigation_bar]):
        if control.key == key:
            return control
    raise AssertionError(f"Control {key!r} is not attached to the active screen.")


def select_screen(page: FakePage, index: int) -> None:
    key = "screen-navigation-wide" if (page.width or 430) >= 860 else "screen-navigation-mobile"
    navigation = find_control(page, key)
    assert isinstance(navigation, (ft.NavigationRail, ft.NavigationBar))
    navigation.selected_index = index
    assert navigation.on_change is not None
    cast(Callable[[object], None], navigation.on_change)(SimpleNamespace(control=navigation))
