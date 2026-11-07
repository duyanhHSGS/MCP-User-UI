"""Readable text scales are real font sizes, persisted and applied without rebuilds."""

import gc
import json
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import cast

import flet as ft
import pytest

from app import main
from app_preferences import AppPreferences
from tests.ui_helpers import FakePage, find_control, select_screen
from typography import (
    TypographyScaler, contrast_ratio, readable_link_color, readable_markdown_style,
    typography_theme, valid_text_scale,
)
from ui_theme import PALETTES


@pytest.mark.parametrize("value", [None, True, False, 90, 99, 101, 185, 200, "150", 140.0])
def test_invalid_text_scale_values_are_rejected(value: object) -> None:
    assert not valid_text_scale(value)


@pytest.mark.parametrize("value", list(range(100, 181, 10)))
def test_supported_scale_steps(value: int) -> None:
    assert valid_text_scale(value)
    theme = typography_theme(value)
    assert theme.label_large is not None
    assert theme.label_large.size == round(14 * value / 100, 1)


def test_scaler_restores_original_fonts_without_compounding_or_transform() -> None:
    scaler = TypographyScaler()
    heading = ft.Text("Tool title", size=18)
    natural = ft.Text("Tool result", selectable=True)
    field = ft.TextField(label="Repository", value="facebook/react")
    checkbox = ft.Checkbox(label="Nerd mode", value=False)
    markdown = ft.Markdown("## Answer\n\n- One\n- Two", selectable=True)
    controls = [heading, natural, field, checkbox, markdown]

    scaler.apply(controls)
    assert heading.size == 18
    assert natural.size is None
    assert field.text_size is None
    assert checkbox.label_style is None
    assert markdown.md_style_sheet is not None
    assert markdown.md_style_sheet.p_text_style is not None
    assert markdown.md_style_sheet.p_text_style.color == PALETTES["Lagoon"]["dark"].foreground
    assert markdown.md_style_sheet.p_text_style.size is None

    scaler.update(150, 170)
    scaler.apply(controls)
    assert heading.size == 27
    assert natural.size == 21
    assert field.text_size == 24
    assert field.label_style is not None and field.label_style.size == 19.5
    assert field.hint_style is not None and field.hint_style.size == 19.5
    assert checkbox.label_style is not None and checkbox.label_style.size == 21
    assert markdown.md_style_sheet is not None
    assert markdown.md_style_sheet.p_text_style is not None
    assert markdown.md_style_sheet.p_text_style.size == 25.5
    assert field.value == "facebook/react"

    scaler.apply(controls)
    assert heading.size == 27  # Reapplying the same scale never compounds it.

    scaler.update(180, 130)
    scaler.apply(controls)
    assert heading.size == 32.4
    assert field.text_size == 28.8
    assert markdown.md_style_sheet is not None
    assert markdown.md_style_sheet.p_text_style is not None
    assert markdown.md_style_sheet.p_text_style.size == 19.5

    scaler.update(100, 100)
    scaler.apply(controls)
    assert heading.size == 18
    assert natural.size is None
    assert field.text_size is None
    assert field.label_style is None
    assert checkbox.label_style is None
    assert markdown.md_style_sheet is not None
    assert markdown.md_style_sheet.p_text_style is not None
    assert markdown.md_style_sheet.p_text_style.color == PALETTES["Lagoon"]["dark"].foreground
    assert markdown.md_style_sheet.p_text_style.size is None
    assert field.value == "facebook/react"


def test_scaler_does_not_keep_closed_result_widgets_alive() -> None:
    scaler = TypographyScaler()
    result = ft.Markdown("Remote server response")
    ref = weakref.ref(result)
    scaler.update(140, 170)
    scaler.apply(result)
    del result
    gc.collect()
    assert ref() is None


def test_preferences_round_trip_preserves_all_other_settings(tmp_path: Path) -> None:
    path = tmp_path / "private" / "mcp-user-ui-appearance.json"
    prefs = AppPreferences(path)
    assert prefs.load_text_scales() == (100, 100)
    prefs.save("Graphite", "light")
    prefs.save_nerd_mode(True)
    prefs.save_text_scales(150, 180)
    assert AppPreferences(path).load_text_scales() == (150, 180)
    assert prefs.load() == ("Graphite", "light")
    assert prefs.load_nerd_mode()
    assert json.loads(path.read_text()) == {
        "palette": "Graphite", "mode": "light", "nerd_mode": True,
        "interface_text_scale": 150, "answer_text_scale": 180,
    }
    prefs.save("Ember", "dark")
    assert prefs.load_text_scales() == (150, 180)
    prefs.save_nerd_mode(False)
    assert prefs.load_text_scales() == (150, 180)


@pytest.mark.parametrize("invalid", [False, True, 80, 99, 181, 125, "140", None])
def test_malformed_text_preferences_cannot_break_app(tmp_path: Path, invalid: object) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "interface_text_scale": invalid,
        "answer_text_scale": invalid,
    }))
    assert AppPreferences(path).load_text_scales() == (100, 100)


def test_invalid_save_does_not_corrupt_existing_preferences(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    prefs = AppPreferences(path)
    prefs.save_text_scales(140, 160)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Text scale"):
        prefs.save_text_scales(120, 125)
    with pytest.raises(ValueError, match="Text scale"):
        prefs.save_text_scales(90, 120)
    assert path.read_bytes() == before


@pytest.mark.parametrize("width", [320, 430, 860, 1080])
def test_settings_sliders_enlarge_real_widgets_without_rebuilding(
    width: float,
) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    original_root = page.controls[0]
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://test.example/mcp"

    select_screen(page, 2)
    interface = cast(ft.Slider, find_control(page, "interface-text-scale"))
    answer = cast(ft.Slider, find_control(page, "answer-text-scale"))
    sample = cast(ft.Text, find_control(page, "text-scale-preview"))
    answer_sample = cast(ft.Markdown, find_control(page, "answer-scale-preview"))
    assert interface.value == 100 and answer.value == 100
    assert sample.size is None
    assert answer_sample.md_style_sheet is not None
    assert answer_sample.md_style_sheet.p_text_style is not None
    assert answer_sample.md_style_sheet.p_text_style.color == PALETTES["Lagoon"]["dark"].foreground
    assert answer_sample.md_style_sheet.p_text_style.size is None

    interface.value = 160
    assert interface.on_change is not None
    cast(Callable[[], None], interface.on_change)()
    assert sample.size == 22.4
    assert cast(ft.Text, find_control(page, "interface-text-scale-label")).value == "160%"
    assert page.theme is not None and page.theme.text_theme is not None
    assert page.theme.text_theme.body_medium is not None
    assert page.theme.text_theme.body_medium.size == 22.4

    answer.value = 180
    assert answer.on_change is not None
    cast(Callable[[], None], answer.on_change)()
    assert answer_sample.md_style_sheet is not None
    assert answer_sample.md_style_sheet.h2_text_style is not None
    assert answer_sample.md_style_sheet.h2_text_style.size == 43.2
    assert page.controls[0] is original_root
    assert endpoint.value == "https://test.example/mcp"
    assert page.navigation_bar is not None
    assert page.navigation_bar.height == 128

    select_screen(page, 0)
    assert find_control(page, "endpoint") is endpoint
    assert endpoint.text_size == 25.6
    select_screen(page, 2)
    assert sample.size == 22.4
    reset = cast(ft.OutlinedButton, find_control(page, "reset-text-scales"))
    assert reset.on_click is not None
    cast(Callable[[], None], reset.on_click)()
    assert interface.value == 100 and answer.value == 100
    assert sample.size is None
    assert answer_sample.md_style_sheet is not None
    assert answer_sample.md_style_sheet.p_text_style is not None
    assert answer_sample.md_style_sheet.p_text_style.color == PALETTES["Lagoon"]["dark"].foreground
    assert answer_sample.md_style_sheet.p_text_style.size is None
    assert endpoint.value == "https://test.example/mcp"
    assert page.controls[0] is original_root
    assert page.navigation_bar is not None
    assert page.navigation_bar.height == 80


def test_scale_settings_save_and_restore_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(tmp_path))
    page = FakePage()
    main(cast(ft.Page, page))
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://do-not-store.example/mcp"
    token = cast(ft.TextField, find_control(page, "bearer-token"))
    token.value = "hidden-credential"

    select_screen(page, 2)
    ui = cast(ft.Slider, find_control(page, "interface-text-scale"))
    answers = cast(ft.Slider, find_control(page, "answer-text-scale"))
    ui.value = 150
    answers.value = 170
    assert ui.on_change is not None and answers.on_change is not None
    cast(Callable[[], None], ui.on_change)()
    cast(Callable[[], None], answers.on_change)()
    assert answers.on_change_end is not None
    cast(Callable[[], None], answers.on_change_end)()

    data = (tmp_path / "mcp-user-ui-appearance.json").read_text()
    assert '"interface_text_scale": 150' in data
    assert '"answer_text_scale": 170' in data
    assert "hidden-credential" not in data
    assert "do-not-store" not in data
    page2 = FakePage()
    main(cast(ft.Page, page2))
    select_screen(page2, 2)
    assert cast(ft.Slider, find_control(page2, "interface-text-scale")).value == 150
    assert cast(ft.Slider, find_control(page2, "answer-text-scale")).value == 170
    assert cast(ft.Text, find_control(page2, "text-scale-preview")).size == 21
    select_screen(page2, 0)
    assert cast(ft.TextField, find_control(page2, "endpoint")).text_size == 24
    assert not cast(ft.TextField, find_control(page2, "endpoint")).value


def test_theme_changes_keep_scaled_text_and_inputs() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    endpoint = cast(ft.TextField, find_control(page, "endpoint"))
    endpoint.value = "https://server.test/mcp"
    select_screen(page, 2)
    slider = cast(ft.Slider, find_control(page, "interface-text-scale"))
    slider.value = 140
    assert slider.on_change is not None
    cast(Callable[[], None], slider.on_change)()
    light = cast(ft.FilledTonalButton, find_control(page, "mode-light"))
    assert light.on_click is not None
    cast(Callable[[object], None], light.on_click)(None)
    assert page.theme is not None and page.theme.text_theme is not None
    assert page.theme.text_theme.label_large is not None
    assert page.theme.text_theme.label_large.size == 19.6
    assert page.theme_mode == ft.ThemeMode.LIGHT
    assert cast(ft.Text, find_control(page, "text-scale-preview")).size == 19.6
    select_screen(page, 0)
    assert endpoint.value == "https://server.test/mcp"
    assert endpoint.text_size == 22.4



@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("percent", [100, 110, 150, 180])
def test_markdown_text_contrast_across_every_palette_and_scale(
    palette: str, mode: str, percent: int,
) -> None:
    """No black-on-black answer text, headings, bullets or links at any zoom."""
    selected = PALETTES[palette][mode]
    sheet = readable_markdown_style(selected, percent)
    from dataclasses import fields

    for attribute in fields(ft.MarkdownStyleSheet):
        if not attribute.name.endswith("_text_style"):
            continue
        style = getattr(sheet, attribute.name)
        assert isinstance(style, ft.TextStyle)
        assert isinstance(style.color, str)
        assert contrast_ratio(style.color, selected.raised) >= 4.5, (
            palette, mode, percent, attribute.name,
        )
        assert contrast_ratio(style.color, selected.surface) >= 4.5
        if attribute.name != "a_text_style":
            assert style.color == selected.foreground
        if percent != 100:
            assert style.size is not None and style.size >= 14 * percent / 100
        else:
            assert style.size is None
    assert sheet.a_text_style is not None
    assert sheet.a_text_style.color == readable_link_color(selected)
    assert sheet.a_text_style.decoration == ft.TextDecoration.UNDERLINE
    assert sheet.codeblock_decoration is not None
    assert sheet.codeblock_decoration.bgcolor == selected.raised


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_setting_appearance_recolors_existing_markdown_and_theme(
    palette: str, mode: str,
) -> None:
    """Palette changes update mounted Markdown instead of freezing the UI tree."""
    page = FakePage()
    main(cast(ft.Page, page))
    root = page.controls[0]
    select_screen(page, 2)
    preview = cast(ft.Markdown, find_control(page, "answer-scale-preview"))
    slider = cast(ft.Slider, find_control(page, "answer-text-scale"))
    slider.value = 110
    assert slider.on_change is not None
    cast(Callable[[], None], slider.on_change)()
    option = cast(ft.ListTile, find_control(page, f"palette-{palette.lower()}"))
    assert option.on_click is not None
    cast(Callable[[object], None], option.on_click)(None)
    button = cast(ft.FilledTonalButton, find_control(page, f"mode-{mode}"))
    assert button.on_click is not None
    cast(Callable[[object], None], button.on_click)(None)

    colors = PALETTES[palette][mode]
    assert page.controls[0] is root
    assert find_control(page, "answer-scale-preview") is preview
    assert page.bgcolor == colors.background
    assert page.theme is not None and page.theme.markdown_theme is not None
    assert page.dark_theme is not None and page.dark_theme.markdown_theme is not None
    for sheet in (
        preview.md_style_sheet,
        page.theme.markdown_theme,
        page.dark_theme.markdown_theme,
    ):
        assert sheet is not None
        assert sheet.p_text_style is not None
        assert sheet.h2_text_style is not None
        assert sheet.list_bullet_text_style is not None
        assert sheet.p_text_style.color == colors.foreground
        assert sheet.h2_text_style.color == colors.foreground
        assert sheet.list_bullet_text_style.color == colors.foreground
        assert sheet.a_text_style is not None
        assert contrast_ratio(str(sheet.a_text_style.color), colors.raised) >= 4.5
        assert sheet.h2_text_style.size == 26.4
    assert preview.code_theme == (
        ft.MarkdownCodeTheme.A11Y_DARK if mode == "dark"
        else ft.MarkdownCodeTheme.A11Y_LIGHT
    )


def test_reset_does_not_restore_unreadable_markdown_defaults() -> None:
    page = FakePage()
    main(cast(ft.Page, page))
    select_screen(page, 2)
    preview = cast(ft.Markdown, find_control(page, "answer-scale-preview"))
    slider = cast(ft.Slider, find_control(page, "answer-text-scale"))
    slider.value = 170
    assert slider.on_change is not None
    cast(Callable[[], None], slider.on_change)()
    reset = cast(ft.OutlinedButton, find_control(page, "reset-text-scales"))
    assert reset.on_click is not None
    cast(Callable[[], None], reset.on_click)()
    assert slider.value == 100
    assert preview.md_style_sheet is not None
    assert preview.md_style_sheet.p_text_style is not None
    assert preview.md_style_sheet.p_text_style.color == PALETTES["Lagoon"]["dark"].foreground
    assert preview.md_style_sheet.p_text_style.size is None
