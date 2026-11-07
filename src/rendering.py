"""Safe, readable MCP result previews for Flet without binary/base64 dumps."""

import base64
import binascii
import io
import json

import flet as ft
from PIL import Image, UnidentifiedImageError

MAX_DISPLAY = 40_000
MAX_IMAGE_BYTES = 10_000_000


def preview(value: object, maximum: int = MAX_DISPLAY) -> str:
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
    except (binascii.Error, OSError, ValueError, UnidentifiedImageError):
        return None


def content_views(payload: dict[str, object]) -> list[ft.Control]:
    """Show text, structured content, returned images, and raw JSON on demand."""
    views: list[ft.Control] = []
    if payload.get("isError") is True:
        views.append(ft.Text("Remote tool reported an error.", color=ft.Colors.ERROR, weight=ft.FontWeight.BOLD))
    data = payload.get("structuredContent")
    if isinstance(data, dict) and any(key in data for key in ("stdout", "stderr", "exit_code", "returncode")):
        views.append(ft.Text("Remote process output", weight=ft.FontWeight.BOLD))
        code = data.get("exit_code", data.get("returncode", "not reported"))
        views.append(ft.Text(f"Exit code: {code}", selectable=True))
        for key in ("stdout", "stderr"):
            stream = data.get(key)
            if stream is not None:
                views.append(ft.TextField(label=key.upper(), value=str(stream)[:MAX_DISPLAY],
                                          read_only=True, multiline=True, min_lines=2, max_lines=10))
    elif data is not None:
        views.append(ft.Text("Structured result", weight=ft.FontWeight.BOLD))
        views.append(ft.TextField(value=preview(data), read_only=True, multiline=True, min_lines=3, max_lines=12))
    messages = payload.get("messages")
    if isinstance(messages, list):
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            text = content.get("text") if isinstance(content, dict) else None
            views.append(ft.Text(f"Message {index + 1} · {message.get('role', 'unknown')}",
                                 weight=ft.FontWeight.BOLD))
            views.append(ft.TextField(value=text if isinstance(text, str) else preview(content),
                                      read_only=True, multiline=True, min_lines=2, max_lines=10))
    parts = payload.get("content", payload.get("contents", []))
    if isinstance(parts, list):
        for index, raw_part in enumerate(parts):
            if not isinstance(raw_part, dict):
                continue
            kind = raw_part.get("type")
            if kind == "image" and raw_part.get("mimeType") == "image/png":
                data_png = _valid_png(raw_part.get("data"))
                if data_png is None:
                    views.append(ft.Text(f"Image {index + 1}: invalid or oversized PNG.", color=ft.Colors.ERROR))
                else:
                    views.append(ft.Text(f"Image {index + 1} (PNG)", weight=ft.FontWeight.BOLD))
                    views.append(ft.Container(
                        height=390,
                        content=ft.InteractiveViewer(
                            content=ft.Image(src=data_png, fit=ft.BoxFit.CONTAIN, height=380),
                            min_scale=0.5, max_scale=6,
                        ),
                    ))
            elif kind in ("text", "resource", None) or "text" in raw_part:
                text = raw_part.get("text")
                if text is None:
                    text = raw_part.get("resource", raw_part)
                content = text if isinstance(text, str) else preview(text)
                views.append(ft.Text(f"Content {index + 1}", weight=ft.FontWeight.BOLD))
                views.append(ft.TextField(
                    value=content[:MAX_DISPLAY] + ("\n... [Truncated preview]" if len(content) > MAX_DISPLAY else ""),
                    read_only=True, multiline=True, min_lines=2, max_lines=12,
                ))
            else:
                views.append(ft.Text(f"Content {index + 1}: {kind or 'unknown'} (raw JSON available)"))
    if not views:
        views.append(ft.Text("No readable content; see raw response."))
    views.append(ft.ExpansionTile(
        title="Raw MCP response (JSON)",
        controls=[ft.TextField(value=preview(payload), multiline=True, read_only=True, min_lines=3, max_lines=14)],
    ))
    return views
