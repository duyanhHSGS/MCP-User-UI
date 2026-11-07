"""Curated, less-common Google Material icons bundled in Flet 1.1.

Keep icons semantic and platform-native: no external fonts, assets or downloads.
"""

import flet as ft


CATEGORY_ICONS: dict[str, ft.IconData] = {
    "Tools": ft.Icons.INTEGRATION_INSTRUCTIONS_OUTLINED,
    "Prompts": ft.Icons.PSYCHOLOGY_ALT_OUTLINED,
    "Resources": ft.Icons.ACCOUNT_TREE_OUTLINED,
    "Logs": ft.Icons.TERMINAL_OUTLINED,
}

# Each navigation destination has a deliberately paired outline/fill symbol.
NAVIGATION_ICONS: dict[str, tuple[ft.IconData, ft.IconData]] = {
    "Connection": (ft.Icons.CABLE_OUTLINED, ft.Icons.CABLE),
    "Capabilities": (ft.Icons.AUTO_AWESOME_MOSAIC_OUTLINED, ft.Icons.AUTO_AWESOME_MOSAIC),
    "Settings": (ft.Icons.DISPLAY_SETTINGS_OUTLINED, ft.Icons.DISPLAY_SETTINGS),
}

TYPE_ICONS: dict[str, ft.IconData] = {
    "string": ft.Icons.SHORT_TEXT_OUTLINED,
    "integer": ft.Icons.PIN_OUTLINED,
    "number": ft.Icons.NUMBERS_OUTLINED,
    "array": ft.Icons.VIEW_LIST_OUTLINED,
    "object": ft.Icons.ACCOUNT_TREE_OUTLINED,
}


def argument_icon(name: str, kind: str) -> ft.IconData:
    """Pick a meaningful glyph from a tool schema, without server-specific code."""
    normalized = name.casefold().replace("_", "").replace("-", "")
    if "question" in normalized or "prompt" in normalized:
        return ft.Icons.QUESTION_ANSWER_OUTLINED
    if "repo" in normalized or "branch" in normalized:
        return ft.Icons.ACCOUNT_TREE_OUTLINED
    if "uri" in normalized or "endpoint" in normalized or "url" in normalized:
        return ft.Icons.ALT_ROUTE_OUTLINED
    if "target" in normalized or "device" in normalized or "host" in normalized:
        return ft.Icons.SENSORS_OUTLINED
    return TYPE_ICONS.get(kind, ft.Icons.TUNE_OUTLINED)
