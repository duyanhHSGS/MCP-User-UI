"""Meaningful labels remain readable; security details are never buried in 12px text."""

from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import cast

import flet as ft
import pytest

from app import main
from saved_connections import SavedConnectionStore, StorageAreas
from tests.ui_helpers import FakePage, find_control, select_screen, walk_controls
from ui_theme import PALETTES


@pytest.mark.parametrize("width", [320, 430, 860, 1080])
def test_all_visible_interface_text_is_at_least_14_pixels(width: int) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))

    for screen in (0, 1, 2):
        select_screen(page, screen)
        text_controls = [
            c for c in walk_controls(page.controls) if isinstance(c, ft.Text)
        ]
        assert text_controls
        for item in text_controls:
            if item.size is not None:
                assert item.size >= 14, (screen, item.value, item.size)

    assert page.theme is not None
    assert page.theme.text_theme is not None
    for field in fields(ft.TextTheme):
        style = getattr(page.theme.text_theme, field.name)
        if isinstance(style, ft.TextStyle):
            assert style.size is None or style.size >= 14


@pytest.mark.parametrize("width", [320, 860, 1080])
def test_short_security_warning_and_readable_dialog_without_saved_data_changes(
    width: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    store = SavedConnectionStore(StorageAreas(tmp_path, None, None))
    profile = store.save("https://example.org/mcp", oauth=False, bearer="test-secret")
    old_bytes = (tmp_path / "saved-mcp-connections.json").read_bytes()
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    root = page.controls[0]

    notice = cast(ft.Text, find_control(page, "credential-security-warning"))
    assert notice.value == "Saved tokens are not encrypted."
    assert notice.size == 16
    assert notice.color == PALETTES["Lagoon"]["dark"].foreground
    button = cast(ft.IconButton, find_control(page, "credential-security-info"))
    assert button.tooltip == "How saved credentials are stored"
    assert button.on_click is not None

    body_words = " ".join(
        str(c.value) for c in walk_controls(page.controls)
        if isinstance(c, ft.Text)
    )
    assert "Credentials save ONLY when" not in body_words
    assert "not encrypted" in body_words
    assert "server-side" not in body_words
    assert find_control(page, f"saved-use-{profile.identifier}")

    cast(Callable[[], None], button.on_click)()
    dialog = page.dialog
    assert isinstance(dialog, ft.AlertDialog)
    assert dialog.modal
    assert dialog.key == "credential-security-dialog"
    assert isinstance(dialog.title, ft.Text)
    assert dialog.title.value == "Saved credential security"
    assert dialog.title.size is not None and dialog.title.size >= 18
    paragraphs = [
        c for c in walk_controls(dialog.content) if isinstance(c, ft.Text)
    ]
    assert len(paragraphs) >= 5
    for para in paragraphs:
        assert para.size is not None and para.size >= 16
    details = " ".join(str(para.value) for para in paragraphs)
    assert "not encrypted" in details
    assert "only" in details.lower() or "optional" in details
    assert "disconnects" in details
    assert "server-side" in details
    assert "test-secret" not in details
    assert page.controls[0] is root
    assert (tmp_path / "saved-mcp-connections.json").read_bytes() == old_bytes

    close = cast(ft.TextButton, dialog.actions[0])
    assert close.key == "close-credential-info"
    assert close.on_click is not None
    cast(Callable[[], None], close.on_click)()
    assert page.dialog is None
    assert page.controls[0] is root
    assert (tmp_path / "saved-mcp-connections.json").read_bytes() == old_bytes


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_security_dialog_uses_current_palette_and_no_unreadable_text(
    palette: str, mode: str,
) -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    select_screen(page, 2)
    option = cast(ft.ListTile, find_control(page, f"palette-{palette.lower()}"))
    assert option.on_click is not None
    cast(Callable[[object], None], option.on_click)(None)
    theme_mode = cast(ft.FilledTonalButton, find_control(page, f"mode-{mode}"))
    assert theme_mode.on_click is not None
    cast(Callable[[object], None], theme_mode.on_click)(None)
    colors = PALETTES[palette][mode]

    select_screen(page, 0)
    warning = cast(ft.Text, find_control(page, "credential-security-warning"))
    assert warning.color == colors.foreground
    info = cast(ft.IconButton, find_control(page, "credential-security-info"))
    assert info.on_click is not None
    cast(Callable[[], None], info.on_click)()
    dialog = page.dialog
    assert isinstance(dialog, ft.AlertDialog)
    assert dialog.bgcolor == colors.surface
    assert isinstance(dialog.title, ft.Text)
    assert dialog.title.color == colors.foreground
    for field in walk_controls(dialog.content):
        if isinstance(field, ft.Text):
            assert field.color == colors.foreground
            assert field.size is not None and field.size >= 16


def test_decorative_subtitles_are_absent_from_the_active_screens() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    forbidden = (
        "Customize your MCP playground.",
        "Streamable HTTP · direct remote connection",
        "Credentials save ONLY when",
        "Discovered items",
        "Only what your server actually advertises.",
        "Live preview · readable at a glance",
        "Enlarge menus, tool names",
        "Make Markdown answers",
        "Off by default. Enable to reveal",
    )
    for index in (0, 1, 2):
        select_screen(page, index)
        words = " ".join(
            str(c.value) for c in walk_controls(page.controls)
            if isinstance(c, ft.Text)
        )
        for sentence in forbidden:
            assert sentence not in words
