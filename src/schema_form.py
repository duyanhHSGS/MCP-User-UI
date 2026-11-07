"""Small JSON Schema form adapter for explicitly human-triggered MCP calls."""

import json
from collections.abc import Mapping

import flet as ft


_SUPPORTED_KINDS = {"string", "integer", "number", "boolean", "array", "object"}


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
    """Return simple properties; complex schemas stay available in advanced JSON."""
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
    field = normalized_field(definition)
    if definition.get("anyOf") is not None and field is not None:
        if value is None:
            return
        validate_json_value(value, field, path)
        return
    kind = definition.get("type")
    if kind == "array":
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
            import re

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
    schema: Mapping[str, object], controls: Mapping[str, ft.TextField | ft.Checkbox | ft.Dropdown]
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
            if not __import__("math").isfinite(value):
                raise ValueError(f"{name}: number must be finite.")
        else:
            continue
        validate_json_value(value, definition, name)
        result[name] = value
    return result


def create_fields(
    schema: Mapping[str, object]
) -> tuple[list[ft.Control], dict[str, ft.TextField | ft.Checkbox | ft.Dropdown]]:
    """Build visible Material controls with required and default hints."""
    required = schema.get("required", [])
    names = required if isinstance(required, list) else []
    controls: dict[str, ft.TextField | ft.Checkbox | ft.Dropdown] = {}
    views: list[ft.Control] = []
    for name, definition in supported_fields(schema):
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


def to_json_text(values: Mapping[str, object]) -> str:
    return json.dumps(values, ensure_ascii=False, indent=2)
