"""Settings are local, persisted only for appearance, and safe to reload."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import flet as ft
import pytest

from app import main
from app_preferences import AppPreferences
from tests.ui_helpers import FakePage, find_control, select_screen
from ui_theme import DEFAULT_BRIGHTNESS, DEFAULT_PALETTE, PALETTES


def test_appearance_preferences_round_trip(tmp_path: Path) -> None:
    storage = tmp_path / "private" / "preferences.json"
    prefs = AppPreferences(storage)
    assert prefs.load() == (DEFAULT_PALETTE, DEFAULT_BRIGHTNESS)
    prefs.save("Ember", "light")
    assert storage.is_file()
    assert AppPreferences(storage).load() == ("Ember", "light")
    assert json.loads(storage.read_text()) == {"palette": "Ember", "mode": "light"}
    prefs.save("Aurora", "dark")
    assert AppPreferences(storage).load() == ("Aurora", "dark")


@pytest.mark.parametrize("contents", [
    "not json", "null", "[]", "42",
    '{"palette": "unknown", "mode": "invalid"}',
    '{"palette": [], "mode": null}',
])
def test_invalid_preferences_recover_defaults(tmp_path: Path, contents: str) -> None:
    file = tmp_path / "preferences.json"
    file.write_text(contents)
    assert AppPreferences(file).load() == (DEFAULT_PALETTE, DEFAULT_BRIGHTNESS)


def test_invalid_appearance_save_never_changes_file(tmp_path: Path) -> None:
    file = tmp_path / "preferences.json"
    prefs = AppPreferences(file)
    prefs.save("Aurora", "light")
    old = file.read_bytes()
    with pytest.raises(ValueError, match="Unknown appearance"):
        prefs.save("surprise", "dark")
    with pytest.raises(ValueError, match="Unknown appearance"):
        prefs.save("Aurora", "neon")
    assert file.read_bytes() == old


def test_no_storage_environment_keeps_preferences_ephemeral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLET_APP_STORAGE_DATA", raising=False)
    prefs = AppPreferences.from_flet_environment()
    assert prefs.path is None
    prefs.save("Ember", "light")
    assert prefs.load() == (DEFAULT_PALETTE, DEFAULT_BRIGHTNESS)


def test_settings_changes_reopen_in_same_local_appearance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    page = FakePage()
    main(cast(ft.Page, page))
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://private.example/mcp"
    token = cast(ft.TextField, find_control(page, "bearer-token"))
    token.value = "secret-test-token"

    select_screen(page, 2)
    palette = cast(ft.ListTile, find_control(page, "palette-graphite"))
    assert palette.on_click is not None
    cast(Callable[[object], None], palette.on_click)(None)
    light = cast(ft.FilledTonalButton, find_control(page, "mode-light"))
    assert light.on_click is not None
    cast(Callable[[object], None], light.on_click)(None)
    saved = tmp_path / "mcp-user-ui-appearance.json"
    data = saved.read_text()
    assert "secret-test-token" not in data
    assert "private.example" not in data
    assert json.loads(data) == {"palette": "Graphite", "mode": "light"}

    next_page = FakePage()
    main(cast(ft.Page, next_page))
    assert next_page.bgcolor == PALETTES["Graphite"]["light"].background
    assert next_page.theme_mode == ft.ThemeMode.LIGHT
    select_screen(next_page, 2)
    option = cast(ft.ListTile, find_control(next_page, "palette-graphite"))
    assert isinstance(option.trailing, ft.Icon)
    assert option.trailing.icon == ft.Icons.CHECK_CIRCLE
    select_screen(page, 0)
    assert endpoint.value == "https://private.example/mcp"
    assert token.value == "secret-test-token"


def test_settings_reports_disk_error_without_breaking_theme_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(self: AppPreferences, palette: str, mode: str) -> None:
        raise OSError("disk is unavailable")

    monkeypatch.setattr(AppPreferences, "save", denied)
    page = FakePage()
    main(cast(ft.Page, page))
    select_screen(page, 2)
    option = cast(ft.ListTile, find_control(page, "palette-ember"))
    assert option.on_click is not None
    cast(Callable[[object], None], option.on_click)(None)
    assert page.bgcolor == PALETTES["Ember"]["dark"].background
    settings = cast(ft.Column, find_control(page, "settings-view"))
    assert any(
        isinstance(item, ft.Text)
        and "save appearance" in str(item.value).lower()
        for item in settings.controls
    )



def test_nerd_mode_defaults_off_and_persists_without_credentials(tmp_path: Path) -> None:
    store = AppPreferences(tmp_path / "config" / "appearance.json")
    assert not store.load_nerd_mode()
    store.save_nerd_mode(True)
    assert store.load_nerd_mode()
    assert store.load() == (DEFAULT_PALETTE, DEFAULT_BRIGHTNESS)
    store.save("Ember", "light")
    assert store.load_nerd_mode(), "Changing the palette must not silently disable Nerd Mode"
    assert store.load() == ("Ember", "light")
    file = (tmp_path / "config" / "appearance.json").read_text()
    assert json.loads(file) == {"nerd_mode": True, "palette": "Ember", "mode": "light"}
    store.save_nerd_mode(False)
    assert not store.load_nerd_mode()
    assert store.load() == ("Ember", "light")


@pytest.mark.parametrize("bad", [None, 1, "true", [], {}, 0])
def test_malformed_nerd_mode_always_defaults_off(
    tmp_path: Path, bad: object,
) -> None:
    file = tmp_path / "config.json"
    file.write_text(json.dumps({"nerd_mode": bad}), encoding="utf-8")
    assert not AppPreferences(file).load_nerd_mode()


def test_nerd_mode_restores_on_reopen_but_raw_checkbox_resets_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    page = FakePage()
    main(cast(ft.Page, page))
    select_screen(page, 2)
    setting = cast(ft.Checkbox, find_control(page, "nerd-mode"))
    assert setting.value is False
    setting.value = True
    assert setting.on_change is not None
    cast(Callable[[], None], setting.on_change)()
    save_path = tmp_path / "mcp-user-ui-appearance.json"
    assert json.loads(save_path.read_text())["nerd_mode"] is True

    next_page = FakePage()
    main(cast(ft.Page, next_page))
    select_screen(next_page, 2)
    assert cast(ft.Checkbox, find_control(next_page, "nerd-mode")).value is True
    select_screen(next_page, 1)
    raw = cast(ft.Checkbox, find_control(next_page, "show-raw-json"))
    assert raw.visible
    assert raw.value is False
    select_screen(next_page, 0)
    assert not cast(ft.TextField, find_control(next_page, "endpoint")).value


def test_nerd_mode_save_failure_keeps_ui_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(self: AppPreferences, enabled: bool) -> None:
        raise OSError("disk is unavailable")

    monkeypatch.setattr(AppPreferences, "save_nerd_mode", denied)
    page = FakePage()
    main(cast(ft.Page, page))
    select_screen(page, 2)
    setting = cast(ft.Checkbox, find_control(page, "nerd-mode"))
    setting.value = True
    assert setting.on_change is not None
    cast(Callable[[], None], setting.on_change)()
    assert cast(ft.Checkbox, find_control(page, "nerd-mode")).value is True
    settings = cast(ft.Column, find_control(page, "settings-view"))
    assert any(
        isinstance(item, ft.Text) and "save nerd mode" in str(item.value).lower()
        for item in settings.controls
    )
    select_screen(page, 1)
    assert cast(ft.Checkbox, find_control(page, "show-raw-json")).visible
