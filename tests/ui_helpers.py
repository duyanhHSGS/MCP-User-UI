"""Shared page double for tests that inspect real Flet controls."""

import asyncio
from collections.abc import Callable, Coroutine
from types import SimpleNamespace

import flet as ft


class FakePage:
    """Keep page state and scheduled callbacks without a Flutter backend."""

    def __init__(self) -> None:
        self.window = SimpleNamespace()
        self.title = ""
        self.padding = 0
        self.scroll: ft.ScrollMode | None = None
        self.theme: ft.Theme | None = None
        self.dark_theme: ft.Theme | None = None
        self.bgcolor: str | None = None
        self.theme_mode = ft.ThemeMode.SYSTEM
        self.appbar: ft.AppBar | None = None
        self.services: list[ft.Control] = []
        self.controls: list[ft.Control] = []
        self.tasks: list[asyncio.Task[None]] = []
        self.update_count = 0

    def add(self, control: ft.Control) -> None:
        self.controls.append(control)
        self.update()  # Real Page.add() already sends an update.

    def update(self) -> None:
        self.update_count += 1

    def run_task(
        self, handler: Callable[..., Coroutine[object, object, None]], *args: object
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(handler(*args))
        self.tasks.append(task)
        return task
