"""Accessible text sizes without transform scaling or widget rebuilds."""

from dataclasses import fields, is_dataclass, replace
from weakref import WeakKeyDictionary

import flet as ft

from ui_theme import DEFAULT_BRIGHTNESS, DEFAULT_PALETTE, PALETTES, Palette

DEFAULT_TEXT_SCALE = 100
MIN_TEXT_SCALE = 100
MAX_TEXT_SCALE = 180
TEXT_SCALE_STEP = 10


def valid_text_scale(value: object) -> bool:
    return (
        type(value) is int
        and MIN_TEXT_SCALE <= value <= MAX_TEXT_SCALE
        and value % TEXT_SCALE_STEP == 0
    )


def typography_theme(percent: int) -> ft.TextTheme:
    """Material styles cover navigation labels, buttons and other defaults."""
    ratio = percent / 100
    sizes = {
        "body_small": 14, "body_medium": 14, "body_large": 16,
        "label_small": 14, "label_medium": 14, "label_large": 14,
        "title_small": 14, "title_medium": 16, "title_large": 22,
        "headline_small": 24, "headline_medium": 28, "headline_large": 32,
        "display_small": 36, "display_medium": 45, "display_large": 57,
    }
    return ft.TextTheme(**{
        key: ft.TextStyle(size=round(value * ratio, 1))
        for key, value in sizes.items()
    })


def _brightness(color: str) -> float:
    """WCAG relative luminance of an RGB hex color."""
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return sum(weight * channel for weight, channel in zip(
        (0.2126, 0.7152, 0.0722), linear,
    ))


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio; 4.5:1 is the AA threshold for normal text."""
    lighter, darker = sorted((_brightness(foreground), _brightness(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_link_color(palette: Palette) -> str:
    """Never use an accent that disappears against a Markdown reading surface."""
    if min(
        contrast_ratio(palette.accent, palette.surface),
        contrast_ratio(palette.accent, palette.raised),
    ) >= 4.5:
        return palette.accent
    return palette.foreground


_MARKDOWN_BASE_SIZES: dict[str, int] = {
    "p_text_style": 15,
    "a_text_style": 15,
    "h1_text_style": 30,
    "h2_text_style": 24,
    "h3_text_style": 20,
    "h4_text_style": 18,
    "h5_text_style": 16,
    "h6_text_style": 15,
    "code_text_style": 14,
    "blockquote_text_style": 15,
    "list_bullet_text_style": 15,
    "table_body_text_style": 15,
    "table_head_text_style": 15,
}


def readable_markdown_style(
    palette: Palette, percent: int,
    original: ft.MarkdownStyleSheet | None = None,
) -> ft.MarkdownStyleSheet:
    """Set explicit readable colors in EVERY Markdown text style at any scale.

    The Flet Markdown renderer can otherwise fall back to a light-mode black
    text style inside a dark surface, even when ordinary Text renders correctly.
    """
    if not valid_text_scale(percent):
        raise ValueError("Answer scale must be 100–180% in steps of 10%.")
    base = original or ft.MarkdownStyleSheet()
    overrides: dict[str, object] = {}
    for item in fields(ft.MarkdownStyleSheet):
        if not item.name.endswith("_text_style"):
            continue
        existing = getattr(base, item.name)
        style = existing if isinstance(existing, ft.TextStyle) else ft.TextStyle()
        original_size = style.size
        default_size = _MARKDOWN_BASE_SIZES.get(item.name, 15)
        size = (
            round((original_size if original_size is not None else default_size) * percent / 100, 1)
            if percent != 100 else original_size
        )
        link = item.name == "a_text_style"
        overrides[item.name] = replace(
            style,
            color=readable_link_color(palette) if link else palette.foreground,
            size=size,
            decoration=ft.TextDecoration.UNDERLINE if link else style.decoration,
        )
    overrides["codeblock_decoration"] = ft.BoxDecoration(
        bgcolor=palette.raised, border_radius=8,
    )
    return replace(base, **overrides)


class TypographyScaler:
    """Resize existing Flet controls in place and keep original sizes weakly."""

    def __init__(self) -> None:
        self.interface_percent = DEFAULT_TEXT_SCALE
        self.answer_percent = DEFAULT_TEXT_SCALE
        self.palette = PALETTES[DEFAULT_PALETTE][DEFAULT_BRIGHTNESS]
        self.dark_mode = DEFAULT_BRIGHTNESS == "dark"
        self._base: WeakKeyDictionary[ft.Control, dict[str, object]] = WeakKeyDictionary()

    def update(self, interface_percent: int, answer_percent: int) -> None:
        if not valid_text_scale(interface_percent) or not valid_text_scale(answer_percent):
            raise ValueError("Text scale must be 100–180% in steps of 10%.")
        self.interface_percent = interface_percent
        self.answer_percent = answer_percent

    def _original(self, control: ft.Control, name: str, current: object) -> object:
        attributes = self._base.setdefault(control, {})
        if name not in attributes:
            attributes[name] = current
        return attributes[name]

    @staticmethod
    def _font_size(base: object, default: float, percent: int) -> float | None:
        if percent == 100:
            return base if isinstance(base, (float, int)) else None
        size = base if isinstance(base, (float, int)) else default
        return round(size * percent / 100, 1)

    def _style(
        self, control: ft.Control, name: str,
        current: ft.TextStyle | None, default_size: float,
    ) -> ft.TextStyle | None:
        base = self._original(control, name, current)
        if self.interface_percent == 100:
            return base if isinstance(base, ft.TextStyle) else None
        style = base if isinstance(base, ft.TextStyle) else ft.TextStyle()
        baseline = style.size if style.size is not None else default_size
        return replace(
            style, size=round(baseline * self.interface_percent / 100, 1),
        )

    def set_palette(self, palette: Palette, *, dark_mode: bool) -> None:
        """Keep markdown colors and code highlighting in sync with Appearance."""
        self.palette = palette
        self.dark_mode = dark_mode

    def _scale_control(self, control: ft.Control) -> None:
        percent = self.interface_percent
        if isinstance(control, ft.Text):
            baseline = self._original(control, "size", control.size)
            control.size = self._font_size(baseline, 14, percent)
        elif isinstance(control, (ft.TextField, ft.Dropdown)):
            baseline = self._original(control, "text_size", control.text_size)
            control.text_size = self._font_size(baseline, 16, percent)
            control.label_style = self._style(
                control, "label_style", control.label_style, 14,
            )
            control.hint_style = self._style(
                control, "hint_style", control.hint_style, 14,
            )
            control.helper_style = self._style(
                control, "helper_style", control.helper_style, 14,
            )
        elif isinstance(control, ft.Checkbox):
            control.label_style = self._style(
                control, "label_style", control.label_style, 14,
            )
        elif isinstance(control, ft.Markdown):
            baseline = self._original(
                control, "md_style_sheet", control.md_style_sheet,
            )
            original = (
                baseline if isinstance(baseline, ft.MarkdownStyleSheet) else None
            )
            control.md_style_sheet = readable_markdown_style(
                self.palette, self.answer_percent, original,
            )
            control.code_theme = (
                ft.MarkdownCodeTheme.A11Y_DARK if self.dark_mode
                else ft.MarkdownCodeTheme.A11Y_LIGHT
            )

    def apply(self, *roots: object) -> None:
        """Walk public control fields once, without retaining dead result widgets."""
        seen: set[int] = set()

        def walk(item: object) -> None:
            if isinstance(item, (str, bytes, int, float, bool, type(None))):
                return
            identifier = id(item)
            if identifier in seen:
                return
            seen.add(identifier)
            if isinstance(item, ft.Control):
                self._scale_control(item)
            if isinstance(item, (list, tuple)):
                for child in item:
                    walk(child)
            elif isinstance(item, dict):
                for child in item.values():
                    walk(child)
            elif is_dataclass(item) and not isinstance(item, type):
                for field in fields(item):
                    if not field.name.startswith("_"):
                        walk(getattr(item, field.name))

        for root in roots:
            walk(root)
