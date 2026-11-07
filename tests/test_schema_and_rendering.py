"""Independent validation and result display tests."""

import base64
import io

import flet as ft
from PIL import Image
import pytest

from app import _name
from rendering import _valid_png, content_views, preview
from schema_form import create_fields, form_arguments, validate_tool_arguments


def test_primitive_form_and_constraints() -> None:
    schema: dict[str, object] = {
        "type": "object", "required": ["name", "count"],
        "properties": {"name": {"type": "string", "minLength": 2},
                       "count": {"type": "integer", "minimum": 1},
                       "enabled": {"type": "boolean"}},
    }
    views, fields = create_fields(schema)
    assert len(views) == 3
    name = fields["name"]
    count = fields["count"]
    assert isinstance(name, ft.TextField)
    assert isinstance(count, ft.TextField)
    name.value = "Alice"
    count.value = "2"
    assert form_arguments(schema, fields)["count"] == 2
    with pytest.raises(ValueError, match="minimum"):
        validate_tool_arguments(schema, {"name": "Alice", "count": 0})


def test_enum_works_with_flet_1_1() -> None:
    controls, _ = create_fields({"properties": {
        "flavor": {"type": "string", "enum": ["vanilla", "mango"]}
    }})
    assert isinstance(controls[0], ft.Dropdown)


def test_names_are_generalized() -> None:
    assert _name({"name": "do_something"}, "Tools") == "do_something"
    assert _name({"uriTemplate": "file:///{name}"}, "Resources") == "file:///{name}"


def test_json_preview_is_bounded() -> None:
    assert "truncated" in preview({"data": "x" * 1000}, 30).lower()


def test_png_validation_and_structured_views() -> None:
    img = Image.new("RGB", (2, 2), (255, 0, 0))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    assert _valid_png(encoded) == buffer.getvalue()
    assert _valid_png("abcd!!!!") is None
    views = content_views({"content": [{"type": "image", "mimeType": "image/png", "data": encoded}],
                           "structuredContent": {"status": "ok"}})
    assert any(isinstance(view, ft.Container) for view in views)
    assert any(isinstance(view, ft.ExpansionTile) for view in views)


def test_prompt_messages_and_terminal_streams_are_visible() -> None:
    prompt = content_views({"messages": [
        {"role": "user", "content": {"type": "text", "text": "Show example"}}
    ]})
    assert any(isinstance(view, ft.TextField) and view.value == "Show example" for view in prompt)
    terminal = content_views({"structuredContent": {
        "stdout": "done", "stderr": "warning", "exit_code": 3,
    }})
    assert any(isinstance(view, ft.TextField) and view.value == "done" for view in terminal)
    assert any(isinstance(view, ft.TextField) and view.value == "warning" for view in terminal)


@pytest.mark.parametrize("properties", [
    {},
    {"title": {"type": "string"}},
    {"enabled": {"type": "boolean"}, "count": {"type": "integer"},
     "mode": {"type": "string", "enum": ["one", "two"]}},
    {"unsupported": {"oneOf": [{"type": "string"}]}, "title": {"type": "string"}},
])
def test_form_views_keep_control_identity_and_property_order(properties: dict[str, object]) -> None:
    views, controls = create_fields({"properties": properties})
    assert len(views) == len(controls)
    assert all(view is control for view, control in zip(views, controls.values(), strict=True))
    assert list(controls) == [name for name in properties if name != "unsupported"]


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "not a number"])
def test_numeric_forms_still_reject_invalid_or_nonfinite_values(raw: str) -> None:
    schema: dict[str, object] = {"properties": {"amount": {"type": "number"}}}
    _, controls = create_fields(schema)
    field = controls["amount"]
    assert isinstance(field, ft.TextField)
    field.value = raw
    with pytest.raises(ValueError, match="number"):
        form_arguments(schema, controls)


@pytest.mark.parametrize("raw", [None, 123, "!not-base64!", "aGVsbG8=", "iVBORw0KGgo="])
def test_invalid_pngs_remain_rejected(raw: object) -> None:
    assert _valid_png(raw) is None


def test_schema_patterns_still_validate_and_report_invalid_patterns() -> None:
    schema: dict[str, object] = {"type": "object", "properties": {
        "code": {"type": "string", "pattern": "^[A-Z]+$"},
    }}
    validate_tool_arguments(schema, {"code": "MCP"})
    with pytest.raises(ValueError, match="does not match"):
        validate_tool_arguments(schema, {"code": "mcp"})
    with pytest.raises(ValueError, match="invalid schema pattern"):
        validate_tool_arguments({"type": "object", "properties": {
            "code": {"type": "string", "pattern": "["},
        }}, {"code": "MCP"})
