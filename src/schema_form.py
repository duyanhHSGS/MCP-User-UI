"""Small JSON Schema form adapter for explicitly human-triggered MCP calls."""

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import flet as ft


_SUPPORTED_KINDS = {"string", "integer", "number", "boolean", "array", "object"}


@dataclass(slots=True)
class UnionField:
    """One on-screen field with an explicit choice of mutually exclusive types."""

    view: ft.Column
    selector: ft.Dropdown
    inputs: list[ft.TextField | ft.Checkbox | ft.Dropdown]
    branches: list[dict[str, object]]


FieldControl = ft.TextField | ft.Checkbox | ft.Dropdown | UnionField


def union_branches(definition: Mapping[str, object]) -> list[dict[str, object]] | None:
    """Offer a selector only when every branch has an unambiguous distinct type.

    Overlapping alternatives, references and nested compositions stay in Advanced
    JSON rather than guessing how to edit or validate them.
    """
    if definition.get("type") is not None:
        return None
    kinds = [name for name in ("anyOf", "oneOf") if name in definition]
    if len(kinds) != 1:
        return None
    options = definition[kinds[0]]
    if not isinstance(options, list) or not 2 <= len(options) <= 6:
        return None
    branches: list[dict[str, object]] = []
    for candidate in options:
        if not isinstance(candidate, dict):
            return None
        kind = candidate.get("type")
        if (
            not isinstance(kind, str)
            or kind not in _SUPPORTED_KINDS
            or any(key in candidate for key in ("anyOf", "oneOf", "allOf", "$ref", "not"))
        ):
            return None
        branches.append(dict(candidate))
    types = {branch["type"] for branch in branches}
    if len(types) != len(branches) or {"number", "integer"} <= types:
        return None
    return branches


def _is_string_list(definition: Mapping[str, object]) -> bool:
    items = definition.get("items")
    return (
        definition.get("type") == "array"
        and isinstance(items, dict)
        and items.get("type") == "string"
    )


def _choice_label(definition: Mapping[str, object]) -> str:
    kind = definition["type"]
    labels = {
        "string": "Text",
        "integer": "Whole number",
        "number": "Number",
        "boolean": "Yes / No",
        "array": "List of text (one per line)" if _is_string_list(definition) else "List (JSON)",
        "object": "Object (JSON)",
    }
    return labels[str(kind)]


def _set_union_type_handler(
    selector: ft.Dropdown,
    editors: list[ft.TextField | ft.Checkbox | ft.Dropdown],
    on_change: Callable[[], None] | None,
) -> None:
    """Bind each selector to its own editors (no late-binding loop captures)."""
    def change_type() -> None:
        for index, editor in enumerate(editors):
            editor.visible = selector.value == str(index)
        if on_change is not None:
            on_change()

    selector.on_select = change_type


def normalized_field(definition: Mapping[str, object]) -> dict[str, object] | None:
    """Represent a primitive field, including a standard nullable anyOf field."""
    kind = definition.get("type")
    if isinstance(kind, str) and kind in _SUPPORTED_KINDS:
        return dict(definition)
    variants = definition.get("anyOf")
    if not isinstance(variants, list) or len(variants) != 2:
        return None
    branches = [part for part in variants if isinstance(part, dict)]
    if len(branches) != 2:
        return None
    nulls = [part for part in branches if part.get("type") == "null"]
    values = [part for part in branches if isinstance(part.get("type"), str) and part["type"] in _SUPPORTED_KINDS]
    if len(nulls) != 1 or len(values) != 1:
        return None
    result = dict(definition)
    del result["anyOf"]
    result.update(values[0])
    return result


def supported_fields(schema: Mapping[str, object]) -> list[tuple[str, dict[str, object]]]:
    """Find fields the GUI can show without losing any required input."""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return []
    fields: list[tuple[str, dict[str, object]]] = []
    for name, value in properties.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        field = normalized_field(value)
        if field is not None:
            fields.append((name, field))
        elif union_branches(value) is not None:
            fields.append((name, dict(value)))
    return fields


def requires_advanced_json(schema: Mapping[str, object]) -> bool:
    """Never silently omit required fields the simple form cannot represent."""
    required = schema.get("required", [])
    if not isinstance(required, list):
        return True
    supported = {name for name, _ in supported_fields(schema)}
    return any(not isinstance(name, str) or name not in supported for name in required)


def validate_json_value(value: object, definition: Mapping[str, object], path: str) -> None:
    """Validate supported nested JSON Schema constraints before a remote call."""
    for composition in ("anyOf", "oneOf"):
        options = definition.get(composition)
        if options is None:
            continue
        if not isinstance(options, list) or not options or not all(
            isinstance(item, dict) for item in options
        ):
            raise ValueError(f"{path}: invalid {composition} schema.")
        matches = 0
        for option in options:
            try:
                validate_json_value(value, option, path)
            except ValueError:
                continue
            matches += 1
        if (composition == "anyOf" and matches == 0) or (
            composition == "oneOf" and matches != 1
        ):
            raise ValueError(f"{path}: value must match {'at least' if composition == 'anyOf' else 'exactly'} one allowed type.")
    kind = definition.get("type")
    if kind == "null":
        if value is not None:
            raise ValueError(f"{path}: expected null.")
    elif kind == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected a JSON array.")
        for bound, label in (("minItems", "at least"), ("maxItems", "at most")):
            limit = definition.get(bound)
            if isinstance(limit, int) and not isinstance(limit, bool):
                if (bound == "minItems" and len(value) < limit) or (
                    bound == "maxItems" and len(value) > limit
                ):
                    raise ValueError(f"{path}: expected {label} {limit} items.")
        items = definition.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                validate_json_value(item, items, f"{path}[{index}]")
    elif kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path}: expected a JSON object.")
        required = definition.get("required")
        if isinstance(required, list):
            for name in required:
                if isinstance(name, str) and name not in value:
                    raise ValueError(f"{path}.{name}: required value is missing.")
        properties = definition.get("properties")
        known = properties if isinstance(properties, dict) else {}
        additional = definition.get("additionalProperties", True)
        for name, child_value in value.items():
            if not isinstance(name, str):
                raise ValueError(f"{path}: object keys must be strings.")
            child = known.get(name)
            if isinstance(child, dict):
                validate_json_value(child_value, child, f"{path}.{name}")
            elif additional is False:
                raise ValueError(f"{path}.{name}: unknown property is not permitted.")
            elif isinstance(additional, dict):
                validate_json_value(child_value, additional, f"{path}.{name}")
    elif kind == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path}: expected a string.")
        for bound, label in (("minLength", "at least"), ("maxLength", "at most")):
            limit = definition.get(bound)
            if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
                if (bound == "minLength" and len(value) < limit) or (
                    bound == "maxLength" and len(value) > limit
                ):
                    raise ValueError(f"{path}: expected {label} {limit} characters.")
    elif kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError(f"{path}: expected an integer.")
    elif kind == "number" and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise ValueError(f"{path}: expected a number.")
    elif kind == "boolean" and not isinstance(value, bool):
        raise ValueError(f"{path}: expected a boolean.")
    if kind == "string" and isinstance(value, str):
        pattern = definition.get("pattern")
        if isinstance(pattern, str):
            try:
                matches = re.search(pattern, value) is not None
            except re.error as exc:
                raise ValueError(f"{path}: invalid schema pattern ({exc}).") from exc
            if not matches:
                raise ValueError(f"{path}: value does not match pattern {pattern!r}.")
    allowed = definition.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        raise ValueError(f"{path}: value is not one of the permitted choices.")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for bound, label in (("minimum", "below"), ("maximum", "above")):
            limit = definition.get(bound)
            if isinstance(limit, (int, float)) and not isinstance(limit, bool):
                if (bound == "minimum" and value < limit) or (
                    bound == "maximum" and value > limit
                ):
                    raise ValueError(f"{path}: value {label} {bound} {limit}.")

def validate_tool_arguments(
    schema: Mapping[str, object], arguments: Mapping[str, object]
) -> None:
    """Validate manually entered advanced JSON against supported schema constraints."""
    validate_json_value(dict(arguments), schema, "arguments")


def form_arguments(
    schema: Mapping[str, object], controls: Mapping[str, FieldControl]
) -> dict[str, object]:
    """Validate typed fields without silently coercing invalid input."""
    required = schema.get("required", [])
    required_names = required if isinstance(required, list) else []
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("Tool schema properties must be an object.")
    result: dict[str, object] = {}
    for name, control in controls.items():
        definition = properties[name]
        if not isinstance(definition, dict):
            continue
        if isinstance(control, UnionField):
            selected = control.selector.value
            if selected is None or not selected.isdecimal():
                raise ValueError(f"{name}: choose a field type.")
            index = int(selected)
            if index >= len(control.branches):
                raise ValueError(f"{name}: choose a valid field type.")
            branch = control.branches[index]
            editor = control.inputs[index]
            if _is_string_list(branch):
                if not isinstance(editor, ft.TextField):
                    raise ValueError(f"{name}: invalid list editor.")
                value: object = [
                    line.strip() for line in (editor.value or "").splitlines()
                    if line.strip()
                ]
            else:
                branch_args = form_arguments(
                    {"properties": {name: branch},
                     "required": [name] if name in required_names else []},
                    {name: editor},
                )
                if name not in branch_args:
                    continue
                value = branch_args[name]
            # Report the selected branch's precise constraint errors first.
            validate_json_value(value, branch, name)
            validate_json_value(value, definition, name)
            result[name] = value
            continue
        field = normalized_field(definition)
        if field is None:
            continue
        kind = field.get("type")
        if isinstance(control, ft.Checkbox):
            if control.value is None:
                if name in required_names:
                    result[name] = None
                continue
            result[name] = control.value
            continue
        raw = (control.value or "").strip()
        if not raw:
            if name in required_names:
                raise ValueError(f"{name}: required value is missing.")
            continue
        if kind in ("array", "object"):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name}: enter valid JSON ({exc.msg}).") from exc
            if kind == "array" and not isinstance(value, list):
                raise ValueError(f"{name}: expected a JSON array.")
            if kind == "object" and not isinstance(value, dict):
                raise ValueError(f"{name}: expected a JSON object.")
        elif kind == "string":
            value = raw
        elif kind == "integer":
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{name}: enter an integer.") from exc
        elif kind == "number":
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError(f"{name}: enter a number.") from exc
            if not math.isfinite(value):
                raise ValueError(f"{name}: number must be finite.")
        else:
            continue
        validate_json_value(value, definition, name)
        result[name] = value
    return result


def create_fields(
    schema: Mapping[str, object], *, on_change: Callable[[], None] | None = None,
) -> tuple[list[ft.Control], dict[str, FieldControl]]:
    """Build human-friendly Material controls; preserve complex-schema fallback."""
    required = schema.get("required", [])
    names = required if isinstance(required, list) else []
    controls: dict[str, FieldControl] = {}
    views: list[ft.Control] = []
    for name, definition in supported_fields(schema):
        branches = union_branches(definition)
        if branches is not None:
            # Text first keeps DeepWiki's one-repository path the easy default.
            branches.sort(key=lambda item: item["type"] != "string")
            default = definition.get("default")
            index = 0
            if "default" in definition:
                for branch_index, branch in enumerate(branches):
                    try:
                        validate_json_value(default, branch, name)
                    except ValueError:
                        continue
                    index = branch_index
                    break
            editors: list[ft.TextField | ft.Checkbox | ft.Dropdown] = []
            for branch_index, branch in enumerate(branches):
                branch_copy = dict(branch)
                if branch_index == index and "default" in definition:
                    branch_copy.setdefault("default", default)
                if _is_string_list(branch):
                    initial = branch_copy.get("default")
                    editor = ft.TextField(
                        label=f"{name} — one item per line",
                        value="\n".join(initial) if isinstance(initial, list)
                        and all(isinstance(item, str) for item in initial) else "",
                        hint_text="One value per line",
                        multiline=True, min_lines=2, max_lines=6, dense=True,
                    )
                else:
                    _, nested = create_fields({
                        "properties": {name: branch_copy},
                        "required": [name] if name in names else [],
                    })
                    editor = nested[name]
                    if not isinstance(editor, (ft.TextField, ft.Checkbox, ft.Dropdown)):
                        raise ValueError(f"{name}: nested field type is unsupported.")
                editor.visible = branch_index == index
                editors.append(editor)
            selector = ft.Dropdown(
                label=f"{name} format",
                options=[
                    ft.DropdownOption(key=str(i), text=_choice_label(branch))
                    for i, branch in enumerate(branches)
                ],
                value=str(index),
                dense=True,
                helper_text=str(definition.get("description", ""))[:120],
            )
            view = ft.Column(
                [selector, *editors], spacing=9,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )

            _set_union_type_handler(selector, editors, on_change)
            controls[name] = UnionField(view, selector, editors, branches)
            views.append(view)
            continue

        kind = definition["type"]
        default = definition.get("default")
        label = f"{name} ({kind}){' *' if name in names else ''}"
        control: ft.TextField | ft.Checkbox | ft.Dropdown
        choices = definition.get("enum")
        if kind in ("string", "integer", "number") and isinstance(choices, list) and choices and all(
            isinstance(choice, str) if kind == "string" else (
                isinstance(choice, int) and not isinstance(choice, bool) if kind == "integer"
                else isinstance(choice, (int, float)) and not isinstance(choice, bool)
            )
            for choice in choices
        ):
            control = ft.Dropdown(
                label=label,
                options=[ft.DropdownOption(key=str(choice), text=str(choice)) for choice in choices],
                value=str(default) if default in choices else None,
                helper_text=str(definition.get("description", ""))[:120],
                dense=True,
            )
        elif kind == "boolean":
            properties = schema.get("properties")
            original = properties.get(name) if isinstance(properties, dict) else None
            nullable = isinstance(original, dict) and isinstance(original.get("anyOf"), list)
            control = ft.Checkbox(
                label=label,
                tristate=nullable,
                value=default if isinstance(default, bool) else None if nullable else False,
            )
        elif kind in ("array", "object"):
            control = ft.TextField(
                label=f"{label} — JSON",
                value=json.dumps(default, ensure_ascii=False) if default is not None else "",
                hint_text=str(definition.get("description", f"Enter a JSON {kind}"))[:120],
                multiline=True,
                min_lines=2,
                max_lines=6,
                dense=True,
            )
        else:
            control = ft.TextField(
                label=label,
                value=str(default) if default is not None else "",
                hint_text=str(definition.get("description", ""))[:120],
                dense=True,
            )
        controls[name] = control
        views.append(control)
    return views, controls
