"""Private local UI preferences; never save MCP credentials or endpoint data."""

import json
import os
from pathlib import Path

from typography import DEFAULT_TEXT_SCALE, valid_text_scale
from ui_theme import DEFAULT_BRIGHTNESS, DEFAULT_PALETTE, PALETTES


class AppPreferences:
    """Store palette, display mode and an opt-in developer display flag."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    @classmethod
    def from_flet_environment(cls) -> "AppPreferences":
        data = os.environ.get("FLET_APP_STORAGE_DATA")
        return cls(Path(data) / "mcp-user-ui-appearance.json" if data else None)

    def _read_settings(self) -> dict[str, object]:
        if self.path is None:
            return {}
        try:
            settings: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def load(self) -> tuple[str, str]:
        settings = self._read_settings()
        palette = settings.get("palette")
        mode = settings.get("mode")
        return (
            palette if isinstance(palette, str) and palette in PALETTES
            else DEFAULT_PALETTE,
            mode if mode in ("light", "dark") else DEFAULT_BRIGHTNESS,
        )

    def load_nerd_mode(self) -> bool:
        """Default OFF, even if the persisted field contains a malformed value."""
        return self._read_settings().get("nerd_mode") is True

    def _write_settings(self, settings: dict[str, object]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(settings), encoding="utf-8")
        temporary.replace(self.path)

    def save(self, palette: str, mode: str) -> None:
        if palette not in PALETTES or mode not in ("light", "dark"):
            raise ValueError("Unknown appearance choice")
        settings = self._read_settings()
        settings.update({"palette": palette, "mode": mode})
        self._write_settings(settings)

    def save_nerd_mode(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("Nerd mode must be on or off")
        settings = self._read_settings()
        settings["nerd_mode"] = enabled
        self._write_settings(settings)


    def load_text_scales(self) -> tuple[int, int]:
        """Missing, corrupt and out-of-range settings are safe default sizes."""
        settings = self._read_settings()
        interface = settings.get("interface_text_scale")
        answer = settings.get("answer_text_scale")
        return (
            interface if isinstance(interface, int) and valid_text_scale(interface)
            else DEFAULT_TEXT_SCALE,
            answer if isinstance(answer, int) and valid_text_scale(answer)
            else DEFAULT_TEXT_SCALE,
        )

    def save_text_scales(self, interface: int, answer: int) -> None:
        if not valid_text_scale(interface) or not valid_text_scale(answer):
            raise ValueError("Text scale must be 100–180% in steps of 10%.")
        settings = self._read_settings()
        settings.update({
            "interface_text_scale": interface,
            "answer_text_scale": answer,
        })
        self._write_settings(settings)
