"""What is on screen, as text, from the desktop's accessibility tree.

``pal-screen`` (on the computer) reads the accessibility tree: every window,
and the controls and text of the active one, with their positions. This turns
it into a compact outline a bot can read for a fraction of a screenshot's
cost, with a point to click for everything listed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import ocr

#: Outlines longer than this are cut short, with a note saying so.
MAX_CHARS = 9000
#: With fewer named or texted items than this, a window is probably drawn in a
#: way the accessibility tree can't see, and its text is read from pixels.
SPARSE = 2
MAX_DEPTH = 10

ROLE_NAMES = {
    "push button": "button",
    "entry": "text field",
    "text": "text area",
    "document web": "web page",
    "page tab": "tab",
    "page tab list": "tabs",
    "menu bar": "menu bar",
    "toggle button": "toggle",
}

Point = Callable[[int, int], tuple[int, int]]


def center(box: list[int]) -> tuple[int, int]:
    x, y, width, height = box
    return x + width // 2, y + height // 2


def _quote(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"“{text}”"


def describe_node(node: dict[str, Any], to_image: Point) -> list[str]:
    indent = "  " * min(node["depth"], MAX_DEPTH)
    role = ROLE_NAMES.get(node["role"], node["role"])
    parts = [role]
    if node["name"]:
        parts.append(_quote(node["name"]))
    if node["states"]:
        parts.append(f"({', '.join(node['states'])})")
    x, y = to_image(*center(node["box"]))
    parts.append(f"@ ({x}, {y})")
    lines = [indent + " ".join(parts)]
    text = node["text"]
    if text.strip():
        if "\n" in text.strip():
            # Documents and terminals: their text, line by line.
            body = [line.rstrip() for line in text.strip("\n").splitlines()]
            lines += [f"{indent}  │ {line}" for line in body]
        else:
            lines[0] += f": {_quote(text, 300)}"
    if node["role"] == "document web":
        lines[0] += " (read it with browser_snapshot or browser_read)"
    return lines


def describe(
    data: dict[str, Any],
    to_image: Point,
    *,
    screen: tuple[int, int],
    pixel_text: Callable[[list[int]], list[ocr.Line]] | None = None,
) -> str:
    """The outline of a ``pal-screen`` reading.

    ``pixel_text(box)`` returns text recognized from the pixels in a box, for
    windows the accessibility tree says little about.
    """

    windows = data.get("windows", [])
    width, height = to_image(*screen)
    out = [f"Screen {width}x{height}. Points are where to click, in screenshot pixels."]
    if not windows:
        out.append("No windows are open.")
        return "\n".join(out)
    out.append("Windows:")
    for window in windows:
        where = ""
        if window.get("box"):
            x, y, w, h = window["box"]
            (x, y), (w, h) = to_image(x, y), to_image(w, h)
            where = f" at ({x}, {y}) {w}x{h}"
        title = _quote(window["title"]) if window["title"] else "(untitled)"
        active = " (active)" if window["active"] else ""
        out.append(f"  {title} — {window['app']}{where}{active}")
    for window in windows:
        nodes = window.get("nodes")
        if nodes is None:
            continue
        title = _quote(window["title"]) if window["title"] else "untitled window"
        out.append("")
        out.append(f"In {title}:")
        for node in nodes:
            out.extend(describe_node(node, to_image))
        if window.get("truncated"):
            out.append("… (more not listed: use find_text, or a screenshot)")
        named = sum(1 for node in nodes if node["name"] or node["text"].strip())
        if named < SPARSE and pixel_text is not None and window.get("box"):
            lines = pixel_text(window["box"])
            if lines:
                out.append("Text read from the pixels of this window:")
                out.extend(f"  {_quote(line.text)} @ {line.box.center}" for line in lines)
    text = "\n".join(out)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit("\n", 1)[0] + "\n… (cut short; ask about one window)"
    return text
