"""Curated Google Material icon choices remain semantic, legible and native."""

from typing import cast

import flet as ft
import pytest

from app import main
from iconography import CATEGORY_ICONS, NAVIGATION_ICONS, TYPE_ICONS, argument_icon
from rendering import content_views
from schema_form import UnionField, create_fields
from tests.ui_helpers import FakePage, find_control, select_screen


def test_icon_palette_is_diverse_and_available_in_bundled_flet() -> None:
    icons = [
        *CATEGORY_ICONS.values(),
        *(icon for pair in NAVIGATION_ICONS.values() for icon in pair),
        *TYPE_ICONS.values(),
    ]
    assert len(set(icons)) >= 14
    assert all(isinstance(icon, ft.IconData) for icon in icons)
    assert len(set(CATEGORY_ICONS.values())) == 4
    assert len({pair[0] for pair in NAVIGATION_ICONS.values()}) == 3
    assert all(outline != filled for outline, filled in NAVIGATION_ICONS.values())


@pytest.mark.parametrize(("name", "kind", "expected"), [
    ("repoName", "string", ft.Icons.ACCOUNT_TREE_OUTLINED),
    ("question", "string", ft.Icons.QUESTION_ANSWER_OUTLINED),
    ("server_uri", "string", ft.Icons.ALT_ROUTE_OUTLINED),
    ("target", "string", ft.Icons.SENSORS_OUTLINED),
    ("description", "string", ft.Icons.SHORT_TEXT_OUTLINED),
    ("count", "integer", ft.Icons.PIN_OUTLINED),
    ("accuracy", "number", ft.Icons.NUMBERS_OUTLINED),
    ("items", "array", ft.Icons.VIEW_LIST_OUTLINED),
    ("configuration", "object", ft.Icons.ACCOUNT_TREE_OUTLINED),
])
def test_generic_schema_field_icons_are_semantic(
    name: str, kind: str, expected: ft.IconData,
) -> None:
    assert argument_icon(name, kind) == expected
    schema = {"properties": {name: {"type": kind}}}
    _, fields = create_fields(schema)
    control = fields[name]
    assert isinstance(control, ft.TextField)
    assert control.prefix_icon == expected


def test_deepwiki_union_fields_have_readable_icon_inputs() -> None:
    schema = {"properties": {"repoName": {"anyOf": [
        {"type": "string"}, {"type": "array", "items": {"type": "string"}},
    ]}}}
    _, fields = create_fields(schema)
    field = fields["repoName"]
    assert isinstance(field, UnionField)
    assert all(isinstance(editor, ft.TextField) for editor in field.inputs)
    assert all(
        isinstance(editor, ft.TextField)
        and editor.prefix_icon == ft.Icons.ACCOUNT_TREE_OUTLINED
        for editor in field.inputs
    )


@pytest.mark.parametrize("width", [320, 430, 1080])
def test_navigation_and_connection_use_curated_icons_without_new_widgets(
    width: float,
) -> None:
    page = FakePage()
    page.width = width
    main(cast(ft.Page, page))
    assert page.navigation_bar is not None
    assert [destination.icon for destination in page.navigation_bar.destinations] == [
        NAVIGATION_ICONS[part][0] for part in NAVIGATION_ICONS
    ]
    assert [destination.selected_icon for destination in page.navigation_bar.destinations] == [
        NAVIGATION_ICONS[part][1] for part in NAVIGATION_ICONS
    ]
    assert cast(ft.TextField, find_control(page, "endpoint")).prefix_icon == ft.Icons.ALT_ROUTE_OUTLINED
    assert cast(ft.TextField, find_control(page, "bearer-token")).prefix_icon == (
        ft.Icons.ENHANCED_ENCRYPTION_OUTLINED
    )
    select_screen(page, 1)
    search = cast(ft.TextField, find_control(page, "capability-search"))
    assert search.prefix_icon == ft.Icons.MANAGE_SEARCH_OUTLINED
    select_screen(page, 2)
    assert find_control(page, "settings-view") is not None


def test_raw_result_has_data_object_icon_and_human_answer_unchanged() -> None:
    views = content_views({"content": [{"type": "text", "text": "# Readable answer"}]})
    assert isinstance(views[1], ft.Markdown)
    assert views[1].value == "# Readable answer"
    raw = views[-1]
    assert isinstance(raw, ft.ExpansionTile)
    assert isinstance(raw.leading, ft.Icon)
    assert raw.leading.icon == ft.Icons.DATA_OBJECT_OUTLINED
