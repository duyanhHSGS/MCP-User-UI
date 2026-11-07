"""Material 3 design tokens used by every screen.

Palette switching is visual-only in phase 1; no remote services are involved.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Semantic color roles shared by all app surfaces."""

    accent: str
    accent_soft: str
    secondary: str
    background: str
    surface: str
    raised: str
    foreground: str
    muted: str
    faint: str
    outline: str
    danger: str


PALETTES: dict[str, dict[str, Palette]] = {
    "Aurora": {
        "dark": Palette(
            "#9FD7C6", "#304B43", "#A4BDEA", "#161A1D", "#202529",
            "#2A3034", "#EDF0F1", "#ABB5BA", "#879399", "#3B4549", "#FFB4AB",
        ),
        "light": Palette(
            "#366F68", "#DCEEE8", "#6687B8", "#F7F8FA", "#FFFFFF",
            "#F0F3F5", "#232A31", "#62707B", "#7C8993", "#E0E5E8", "#BA1A1A",
        ),
    },
    "Graphite": {
        "dark": Palette(
            "#E5E7EB", "#2A2D33", "#9CA3AF", "#08090B", "#101216",
            "#1A1D22", "#F4F4F5", "#A1A1AA", "#6B7280", "#252A30", "#F87171",
        ),
        "light": Palette(
            "#191919", "#E4E4E7", "#52525B", "#FAFAFA", "#FFFFFF",
            "#F4F4F5", "#0A0A0B", "#3F3F46", "#71717A", "#E4E4E7", "#B91C1C",
        ),
    },
    "Ember": {
        "dark": Palette(
            "#FF9F6B", "#3A1F18", "#FFD27D", "#0B0807", "#161110",
            "#221A18", "#FBF6F2", "#C9B6AC", "#8A7669", "#30241E", "#FF6B7A",
        ),
        "light": Palette(
            "#B84727", "#FCE3D6", "#A65C18", "#FBF7F4", "#FFFFFF",
            "#F2EAE3", "#0A0A0B", "#4A3A30", "#7B6A60", "#E4D7CD", "#B91C1C",
        ),
    },
    "Lagoon": {
        "dark": Palette(
            "#5FB6FF", "#13243A", "#7CF5C4", "#070A0E", "#0E1420",
            "#171F2C", "#F2F6FB", "#A6B4C9", "#6E7C90", "#243047", "#FF7A8A",
        ),
        "light": Palette(
            "#1672D2", "#D8ECFB", "#0FA37C", "#F5F8FB", "#FFFFFF",
            "#EAF1F8", "#0A0A0B", "#3E4A5C", "#6F7C90", "#DDE5EF", "#D8344A",
        ),
    },
}

DEFAULT_PALETTE = "Lagoon"
DEFAULT_BRIGHTNESS = "dark"
