"""Independent validation and result display tests."""

import base64
import io
from collections.abc import Callable
from typing import cast

import flet as ft
from PIL import Image
import pytest

from app import _name
from rendering import _valid_png, content_views, preview
from tests.ui_helpers import walk_controls
from schema_form import (UnionField, create_fields, form_arguments, requires_advanced_json, union_branches, validate_tool_arguments)


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
    assert any(isinstance(view, ft.Markdown) and view.value == "Show example" for view in prompt)
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


def _deepwiki_schema(composition: str = "anyOf") -> dict[str, object]:
    """A representative published DeepWiki ask_wiki_question input schema."""
    return {
        "type": "object",
        "required": ["repoName", "question"],
        "additionalProperties": False,
        "properties": {
            "repoName": {
                composition: [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                ],
                "description": "GitHub repository or list of repositories",
            },
            "question": {"type": "string"},
        },
    }


@pytest.mark.parametrize("composition", ["anyOf", "oneOf"])
def test_deepwiki_union_form_uses_plain_inputs_without_raw_json(composition: str) -> None:
    schema = _deepwiki_schema(composition)
    assert not requires_advanced_json(schema)
    views, fields = create_fields(schema)
    assert len(views) == 2
    repository = fields["repoName"]
    assert isinstance(repository, UnionField)
    assert repository.view is views[0]
    assert isinstance(repository.selector, ft.Dropdown)
    assert repository.selector.value == "0"
    assert repository.inputs[0].visible
    assert not repository.inputs[1].visible

    single = repository.inputs[0]
    question = fields["question"]
    assert isinstance(single, ft.TextField)
    assert isinstance(question, ft.TextField)
    single.value = "facebook/react"
    question.value = "How does reconciliation work?"
    expected: dict[str, object] = {"repoName": "facebook/react", "question": "How does reconciliation work?"}
    assert form_arguments(schema, fields) == expected
    validate_tool_arguments(schema, expected)
    with pytest.raises(ValueError, match="repoName"):
        validate_tool_arguments(schema, {**expected, "repoName": 42})

    repository.selector.value = "1"
    assert repository.selector.on_select is not None
    cast(Callable[[], None], repository.selector.on_select)()
    assert not single.visible
    multi = repository.inputs[1]
    assert multi.visible and isinstance(multi, ft.TextField)
    multi.value = "facebook/react\nvuejs/core"
    expected["repoName"] = ["facebook/react", "vuejs/core"]
    assert form_arguments(schema, fields) == expected
    validate_tool_arguments(schema, expected)

    multi.value = "facebook/react\n" * 11
    with pytest.raises(ValueError, match="at most 10 items"):
        form_arguments(schema, fields)


def test_union_editing_switches_types_without_erasing_inactive_values() -> None:
    schema = {"type": "object", "required": ["option"], "properties": {
        "option": {"oneOf": [{"type": "integer"}, {"type": "boolean"}]},
    }}
    changed: list[str] = []
    _, fields = create_fields(schema, on_change=lambda: changed.append("updated"))
    option = fields["option"]
    assert isinstance(option, UnionField)
    integer = option.inputs[0]
    assert isinstance(integer, ft.TextField)
    integer.value = "7"
    assert form_arguments(schema, fields) == {"option": 7}

    option.selector.value = "1"
    assert option.selector.on_select is not None
    cast(Callable[[], None], option.selector.on_select)()
    assert changed == ["updated"]
    boolean = option.inputs[1]
    assert isinstance(boolean, ft.Checkbox)
    boolean.value = True
    assert form_arguments(schema, fields) == {"option": True}

    option.selector.value = "0"
    cast(Callable[[], None], option.selector.on_select)()
    assert integer.value == "7"
    assert form_arguments(schema, fields) == {"option": 7}
    assert changed == ["updated", "updated"]


@pytest.mark.parametrize("composition", ["anyOf", "oneOf"])
def test_schema_union_validation_checks_nested_types(composition: str) -> None:
    schema = {"type": "object", "properties": {
        "value": {composition: [
            {"type": "string", "minLength": 3},
            {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        ]},
    }}
    validate_tool_arguments(schema, {"value": "abc"})
    validate_tool_arguments(schema, {"value": [1, 2]})
    with pytest.raises(ValueError, match="value.*allowed type"):
        validate_tool_arguments(schema, {"value": "ab"})
    with pytest.raises(ValueError, match="value.*allowed type"):
        validate_tool_arguments(schema, {"value": [1, "bad"]})
    with pytest.raises(ValueError, match="value.*allowed type"):
        validate_tool_arguments(schema, {"value": None})


def test_unrepresentable_union_remains_advanced_json_only() -> None:
    schemas = [
        {"oneOf": [{"type": "string"}, {"type": "string"}]},
        {"anyOf": [{"type": "integer"}, {"type": "number"}]},
        {"oneOf": [{"type": "string"}]},
        {"anyOf": [{"$ref": "#/$defs/example"}, {"type": "array"}]},
        {"oneOf": [{"type": "string", "oneOf": [{"type": "string"}]}, {"type": "boolean"}]},
    ]
    for definition in schemas:
        schema = {"type": "object", "required": ["value"],
                  "properties": {"value": definition}}
        assert union_branches(definition) is None
        assert requires_advanced_json(schema)
        assert create_fields(schema)[1] == {}


def test_nullable_union_still_validates_null_and_rejects_invalid_values() -> None:
    schema = {"type": "object", "properties": {
        "nickname": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }}
    validate_tool_arguments(schema, {"nickname": "human"})
    validate_tool_arguments(schema, {"nickname": None})
    with pytest.raises(ValueError, match="nickname.*allowed type"):
        validate_tool_arguments(schema, {"nickname": 123})


def test_multiple_union_selectors_control_only_their_own_field() -> None:
    schema = {"type": "object", "required": ["first", "second"], "properties": {
        "first": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
        "second": {"oneOf": [{"type": "string"}, {"type": "boolean"}]},
    }}
    views, fields = create_fields(schema)
    assert len(views) == 2
    first = fields["first"]
    second = fields["second"]
    assert isinstance(first, UnionField) and isinstance(second, UnionField)
    first.selector.value = "1"
    assert first.selector.on_select is not None
    cast(Callable[[], None], first.selector.on_select)()
    assert first.inputs[1].visible and not first.inputs[0].visible
    assert second.inputs[0].visible and not second.inputs[1].visible
    second.selector.value = "1"
    assert second.selector.on_select is not None
    cast(Callable[[], None], second.selector.on_select)()
    assert first.inputs[1].visible and not first.inputs[0].visible
    assert second.inputs[1].visible and not second.inputs[0].visible



@pytest.mark.parametrize("payload", [
    {"structuredContent": {"status": "ok", "items": [1, 2]},
     "content": [{"type": "text", "text": "result"}]},
    {"structuredContent": {"stdout": "out", "stderr": "err", "exit_code": 1},
     "content": [{"type": "text", "text": "details"}], "isError": True},
    {"messages": [{"role": "assistant", "content": {"text": "answer"}}]},
    {"content": [{"type": "resource", "resource": {"uri": "a", "text": "hello"}}]},
    {"content": [{"type": "text", "text": "long " * 1000}]},
    {},
])
def test_every_result_section_expands_across_available_width(payload: dict[str, object]) -> None:
    """The host column stretches fields; expanded raw response must stretch its children."""
    host = ft.Column(
        content_views(payload),
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    assert host.horizontal_alignment == ft.CrossAxisAlignment.STRETCH
    assert any(isinstance(item, ft.ExpansionTile) for item in host.controls)
    for item in host.controls:
        if isinstance(item, ft.ExpansionTile):
            assert item.expanded_cross_axis_alignment == ft.CrossAxisAlignment.STRETCH
            assert item.controls
            for child in item.controls:
                assert isinstance(child, ft.TextField)
                assert child.width is None  # Stretches with the viewport, not a fixed width.
        if isinstance(item, ft.TextField):
            assert item.width is None


def test_rendered_png_viewport_keeps_full_width_available() -> None:
    image = Image.new("RGB", (4, 4), "red")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    payload: dict[str, object] = {
        "content": [{"type": "image", "mimeType": "image/png",
                     "data": base64.b64encode(stream.getvalue()).decode("ascii")}],
    }
    controls = content_views(payload)
    viewport = next(item for item in controls if isinstance(item, ft.Container))
    assert viewport.width is None  # Parent stretch determines available viewport width.
    assert isinstance(viewport.content, ft.InteractiveViewer)



def _readable_controls(payload: dict[str, object]) -> list[ft.Control]:
    return list(walk_controls(content_views(payload)))


def test_deepwiki_answer_is_readable_markdown_not_json() -> None:
    markdown = "# How React works\n\n- Components\n- Reconciliation"
    controls = content_views({"content": [{"type": "text", "text": markdown}]})
    assert isinstance(controls[0], ft.Text)
    assert controls[0].value == "Answer"
    assert isinstance(controls[1], ft.Markdown)
    assert controls[1].value == markdown
    assert controls[1].selectable
    assert controls[1].extension_set == ft.MarkdownExtensionSet.GITHUB_FLAVORED
    assert all(not isinstance(control, ft.TextField) for control in controls[:-1])
    assert isinstance(controls[-1], ft.ExpansionTile)


def test_text_json_is_parsed_into_readable_fields_not_displayed_as_json() -> None:
    wire: dict[str, object] = {
        "content": [{"type": "text", "text":
                     '{"answer":"It works","total":3,"passed":true,'
                     '"metadata":{"repoName":"facebook/react"},"items":["first","second"]}'}],
    }
    controls = _readable_controls(wire)
    labels = [c.value for c in controls if isinstance(c, ft.Text)]
    assert {"Answer", "Total", "Passed", "Metadata", "Repo Name", "Items",
            "3", "Yes"} <= set(labels)
    assert any(isinstance(c, ft.Text) and c.value == "• first" for c in controls)
    assert any(isinstance(c, ft.Text) and c.value == "• second" for c in controls)
    assert any(isinstance(c, ft.Markdown) and c.value == "It works" for c in controls)
    assert not any(
        isinstance(c, ft.TextField) and c.value.startswith('{"answer"')
        for c in controls
    )


def test_structured_content_is_formatted_as_human_fields() -> None:
    wire: dict[str, object] = {
        "structuredContent": {
            "toolStatus": "success", "count": 2,
            "issues": [{"fileName": "README.md", "lineNumber": 4}],
            "ready": False, "optional": None,
        },
    }
    controls = _readable_controls(wire)
    labels = [c.value for c in controls if isinstance(c, ft.Text)]
    assert {"More information", "Tool Status", "Count", "Issues", "Entry 1", "File Name",
            "Line Number", "Ready", "No", "Optional", "Not provided"} <= set(labels)
    raw_fields = [c for c in controls if isinstance(c, ft.TextField)]
    assert len(raw_fields) == 1  # Only the collapsed advanced JSON viewer.
    assert raw_fields[0].read_only


def test_structured_and_text_duplicate_is_not_shown_twice() -> None:
    answer = {"answer": "The solution", "sources": ["README.md"]}
    wire: dict[str, object] = {
        "content": [{"type": "text", "text": '{"answer":"The solution","sources":["README.md"]}'}],
        "structuredContent": answer,
    }
    controls = _readable_controls(wire)
    assert sum(
        isinstance(c, ft.Text) and c.value == "Answer" for c in controls
    ) == 2  # Heading for content and field named answer.
    assert not any(isinstance(c, ft.Text) and c.value == "More information" for c in controls)


def test_error_result_renders_message_and_details_instead_of_only_flag() -> None:
    wire: dict[str, object] = {
        "isError": True,
        "content": [{"type": "text", "text": "Permission denied: repository is private"}],
        "structuredContent": {"errorCode": 403, "retryable": False},
    }
    controls = _readable_controls(wire)
    assert any(
        isinstance(c, ft.Text) and c.color == ft.Colors.ERROR
        and "error" in str(c.value).lower()
        for c in controls
    )
    assert any(isinstance(c, ft.Markdown) and "Permission denied" in c.value for c in controls)
    assert any(isinstance(c, ft.Text) and c.value == "Error details" for c in controls)
    assert any(isinstance(c, ft.Text) and c.value == "Error Code" for c in controls)
    assert any(isinstance(c, ft.Text) and c.value == "403" for c in controls)


def test_resource_and_prompt_messages_are_readable() -> None:
    resource: dict[str, object] = {
        "contents": [{"uri": "file:///readme", "mimeType": "text/markdown",
                      "text": "# Hello\nThis is a document."}],
    }
    controls = _readable_controls(resource)
    assert any(isinstance(c, ft.Markdown) and "# Hello" in c.value for c in controls)
    assert any(isinstance(c, ft.Text) and "file:///readme" in str(c.value) for c in controls)
    prompt: dict[str, object] = {
        "messages": [{"role": "assistant", "content": [
            {"type": "text", "text": "One."}, {"type": "text", "text": "Two."},
        ]}],
    }
    controls = _readable_controls(prompt)
    assert any(isinstance(c, ft.Text) and c.value == "Message 1 · Assistant" for c in controls)
    assert sum(isinstance(c, ft.Markdown) and c.value in ("One.", "Two.") for c in controls) == 2


def test_binary_and_oversized_values_do_not_create_huge_text_widgets() -> None:
    wire: dict[str, object] = {
        "content": [{"type": "audio", "data": "a" * 60000},
                    {"type": "image", "mimeType": "image/png", "data": "not a png"},
                    {"type": "text", "text": "x" * 41000}],
    }
    controls = content_views(wire)
    assert any(isinstance(c, ft.Text) and "binary" in str(c.value) for c in controls)
    assert any(isinstance(c, ft.Text) and "invalid" in str(c.value) for c in controls)
    markdown = [c for c in controls if isinstance(c, ft.Markdown)]
    assert len(markdown) == 1 and len(markdown[0].value) < 41000
    assert isinstance(controls[-1], ft.ExpansionTile)


def test_large_result_has_clear_limit_and_keeps_raw_data_available() -> None:
    wire: dict[str, object] = {"structuredContent": {"items": list(range(90))}}
    controls = _readable_controls(wire)
    assert any(
        isinstance(c, ft.Text) and "10 more items" in str(c.value) for c in controls
    )
    assert any(
        isinstance(c, ft.TextField) and "89" in c.value
        for c in controls
    )
