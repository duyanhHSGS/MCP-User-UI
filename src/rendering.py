"""Human-first MCP results: readable text and structured fields, with JSON on demand."""

import base64
import binascii
import io
import json
import re

import flet as ft
from PIL import Image

MAX_DISPLAY = 40_000
MAX_IMAGE_BYTES = 10_000_000
MAX_VISIBLE_ITEMS = 80
MAX_NESTING = 6


def preview(value: object, maximum: int = MAX_DISPLAY) -> str:
    """Bound debugging data without changing the underlying complete response."""
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text[:maximum] + ("\n... [Display truncated]" if len(text) > maximum else "")


def _valid_png(raw: object) -> bytes | None:
    if not isinstance(raw, str) or len(raw) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        return None
    try:
        image = base64.b64decode(raw, validate=True)
        if len(image) > MAX_IMAGE_BYTES or not image.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        with Image.open(io.BytesIO(image)) as picture:
            if picture.format != "PNG" or picture.width > 8192 or picture.height > 8192:
                return None
            if picture.width * picture.height > 20_000_000:
                return None
            picture.verify()
        return image
    except (binascii.Error, OSError, ValueError):
        return None


def _label(name: str) -> str:
    """Turn protocol keys into human-sized labels without changing their values."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = spaced.replace("_", " ").replace("-", " ").strip()
    return spaced[:1].upper() + spaced[1:] if spaced else "Value"


def _shorten(text: str) -> str:
    if len(text) <= MAX_DISPLAY:
        return text
    return text[:MAX_DISPLAY] + "\n\n… Preview shortened; full response available below."


def _maybe_json(text: str) -> object:
    """Parse an entire JSON object/list encoded inside a text block, never prose."""
    stripped = text.strip()
    if not (
        stripped.startswith("{") and stripped.endswith("}")
        or stripped.startswith("[") and stripped.endswith("]")
    ):
        return text
    try:
        parsed: object = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    return parsed if isinstance(parsed, (dict, list)) else text


def _answer_text(value: str) -> ft.Control:
    """Markdown renders documentation, code and lists as reading content."""
    return ft.Markdown(
        value=_shorten(value),
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
    )


def _vertical(controls: list[ft.Control], *, spacing: int = 6) -> ft.Column:
    return ft.Column(
        controls,
        spacing=spacing,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )


def _display_value(name: str, value: object, depth: int = 0) -> ft.Control:
    """Render bounded nested data without asking the user to read JSON syntax."""
    label = ft.Text(_label(name), weight=ft.FontWeight.W_600, selectable=True)
    if isinstance(value, str):
        parsed = _maybe_json(value)
        if parsed is not value:
            return _display_value(name, parsed, depth)
        return _vertical([label, _answer_text(value)])
    if isinstance(value, (bool, int, float)) or value is None:
        readable = (
            "Yes" if value is True else "No" if value is False
            else "Not provided" if value is None else str(value)
        )
        return _vertical([label, ft.Text(readable, selectable=True)], spacing=2)
    if depth >= MAX_NESTING:
        return _vertical([
            label,
            ft.Text("Deeply nested details are available in Raw MCP response.",
                    selectable=True),
        ])
    if isinstance(value, dict):
        children: list[ft.Control] = [
            _display_value(str(key), entry, depth + 1)
            for key, entry in list(value.items())[:MAX_VISIBLE_ITEMS]
        ]
        if not children:
            children = [ft.Text("No fields", italic=True)]
        if len(value) > MAX_VISIBLE_ITEMS:
            children.append(ft.Text(
                f"{len(value) - MAX_VISIBLE_ITEMS} additional fields are available in Raw MCP response.",
                selectable=True,
            ))
        return _vertical([
            label,
            ft.Container(
                content=_vertical(children, spacing=12),
                padding=ft.Padding(left=12, top=4, right=0, bottom=4),
            ),
        ])
    if isinstance(value, list):
        if not value:
            return _vertical([label, ft.Text("Empty list", italic=True)])
        entries: list[ft.Control] = []
        for index, item in enumerate(value[:MAX_VISIBLE_ITEMS], start=1):
            if isinstance(item, (str, int, float, bool)) or item is None:
                readable = (
                    "Yes" if item is True else "No" if item is False
                    else "Not provided" if item is None else str(item)
                )
                entries.append(ft.Text(f"• {_shorten(readable)}", selectable=True))
            else:
                entries.append(_display_value(f"Entry {index}", item, depth + 1))
        if len(value) > MAX_VISIBLE_ITEMS:
            entries.append(ft.Text(
                f"{len(value) - MAX_VISIBLE_ITEMS} more items in Raw MCP response.",
                selectable=True,
            ))
        return _vertical([label, ft.Container(
            content=_vertical(entries, spacing=10),
            padding=ft.Padding(left=12, top=4, right=0, bottom=4),
        )])
    return _vertical([label, ft.Text(str(value), selectable=True)])


def _response_part(
    part: dict[str, object], number: int, *, is_error: bool = False,
) -> list[ft.Control]:
    """Present MCP text, embedded resources, and images in human-readable form."""
    kind = part.get("type")
    if kind == "image":
        if part.get("mimeType") != "image/png":
            return [ft.Text(
                f"Image {number} ({part.get('mimeType') or 'unknown format'}): "
                "preview unavailable. See the raw response.",
                color=ft.Colors.ERROR,
            )]
        raw = _valid_png(part.get("data"))
        if raw is None:
            return [ft.Text(f"Image {number}: invalid or oversized PNG.",
                            color=ft.Colors.ERROR)]
        return [
            ft.Text(f"Image {number}", weight=ft.FontWeight.BOLD),
            ft.Container(
                height=390,
                content=ft.InteractiveViewer(
                    content=ft.Image(src=raw, fit=ft.BoxFit.CONTAIN, height=380),
                    min_scale=0.5, max_scale=6,
                ),
            ),
        ]
    if kind in {"audio", "image"} or "blob" in part:
        return [ft.Text(
            f"Attachment {number}: binary data is not displayed as text. "
            "See the raw response for metadata.",
            selectable=True,
        )]
    text = part.get("text")
    if isinstance(text, str):
        label = "Error details" if is_error else "Answer"
        title = label if number == 1 else f"{label} {number}"
        source = part.get("uri")
        heading: list[ft.Control] = []
        if isinstance(source, str):
            heading.append(ft.Text(f"Source: {source}", selectable=True))
        parsed = _maybe_json(text)
        if isinstance(parsed, str):
            return [ft.Text(title, weight=ft.FontWeight.BOLD), *heading, _answer_text(text)]
        return [*heading, _display_value(title, parsed)]
    resource = part.get("resource")
    if isinstance(resource, dict):
        safe_resource = {k: v for k, v in resource.items() if k != "blob"}
        controls = [_display_value(f"Resource {number}", safe_resource)]
        if "blob" in resource:
            controls.append(ft.Text("Binary resource content is available in the raw response."))
        return controls
    # read_resource delivers {"uri": "...", "mimeType": "...", "text": "..."}.
    if isinstance(part.get("uri"), str):
        safe_part = {k: v for k, v in part.items() if k != "blob"}
        controls = [_display_value(f"Resource {number}", safe_part)]
        if "blob" in part:
            controls.append(ft.Text("Binary resource content is available in the raw response."))
        return controls
    safe_part = {k: v for k, v in part.items() if k not in {"data", "blob"}}
    if not safe_part:
        return [ft.Text(f"Part {number}: see Raw MCP response for details.")]
    return [_display_value(f"Part {number}", safe_part)]


def _parts_from_message(message: dict[str, object], index: int) -> list[ft.Control]:
    role = message.get("role")
    role_name = _label(role) if isinstance(role, str) else "Unknown"
    views: list[ft.Control] = [
        ft.Text(f"Message {index} · {role_name}", weight=ft.FontWeight.BOLD),
    ]
    content = message.get("content")
    if isinstance(content, dict):
        views.extend(_response_part(content, 1))
    elif isinstance(content, list):
        for number, part in enumerate(content, start=1):
            if isinstance(part, dict):
                views.extend(_response_part(part, number))
    elif isinstance(content, str):
        views.append(_answer_text(content))
    else:
        views.append(ft.Text("Message has no readable text."))
    return views


def content_views(payload: dict[str, object]) -> list[ft.Control]:
    """Show the answer before metadata; reserve raw JSON for deliberate inspection."""
    views: list[ft.Control] = []
    if payload.get("isError") is True:
        views.append(ft.Text(
            "The server reported an error",
            color=ft.Colors.ERROR,
            weight=ft.FontWeight.BOLD,
            selectable=True,
        ))

    parts = payload.get("content", payload.get("contents", []))
    parsed_answers: list[object] = []
    if isinstance(parts, list):
        for index, part in enumerate(parts, start=1):
            if isinstance(part, dict):
                answer = part.get("text")
                if isinstance(answer, str):
                    parsed_answers.append(_maybe_json(answer))
                views.extend(_response_part(
                    part, index, is_error=payload.get("isError") is True,
                ))

    messages = payload.get("messages")
    if isinstance(messages, list):
        for index, message in enumerate(messages, start=1):
            if isinstance(message, dict):
                views.extend(_parts_from_message(message, index))

    data = payload.get("structuredContent")
    # MCP servers sometimes include the exact same result as both structuredContent
    # and a JSON-encoded text block. Do not show a giant duplicated answer.
    if data is not None and not any(data == answer for answer in parsed_answers):
        if isinstance(data, dict) and any(
            key in data for key in ("stdout", "stderr", "exit_code", "returncode")
        ):
            views.append(ft.Text("Process output", weight=ft.FontWeight.BOLD))
            code = data.get("exit_code", data.get("returncode"))
            if code is not None:
                views.append(ft.Text(f"Exit code: {code}", selectable=True))
            for key in ("stdout", "stderr"):
                stream = data.get(key)
                if stream is not None:
                    views.append(ft.TextField(
                        label=key.upper(),
                        value=_shorten(str(stream)),
                        read_only=True, multiline=True, min_lines=2, max_lines=10,
                    ))
            for key, value in data.items():
                if key not in {"stdout", "stderr", "exit_code", "returncode"}:
                    views.append(_display_value(str(key), value))
        elif isinstance(data, dict):
            views.append(ft.Text("More information", weight=ft.FontWeight.BOLD))
            for key, value in data.items():
                views.append(_display_value(str(key), value))
        else:
            views.append(_display_value("Details", data))

    if not views:
        views.append(ft.Text("No readable content returned by this server.", selectable=True))
    views.append(ft.ExpansionTile(
        title="Raw MCP response (JSON) · advanced",
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
        controls=[ft.TextField(
            value=preview(payload), multiline=True, read_only=True,
            min_lines=3, max_lines=14,
        )],
    ))
    return views
