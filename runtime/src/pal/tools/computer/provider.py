"""Tools for operating a bot's desktop: see it, point, type, manage windows."""

from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool, tool
from PIL import Image

from pal.displays import DisplayManager

from ..base import ToolContext, ToolProvider, ToolResult, error_result, text_result
from . import ocr
from .desktop import Desktop, DesktopError

#: Screenshots are scaled to fit this box; coordinates map back to the screen.
MAX_SCREENSHOT = (1280, 800)

_POINT = {"type": "integer", "minimum": 0}


def _image_result(png: bytes, caption: str) -> ToolResult:
    return {
        "content": [
            {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": "image/png"},
            {"type": "text", "text": caption},
        ]
    }


class ComputerTools(ToolProvider):
    name = "computer"
    description = (
        "operate your desktop: screenshot, click, type_text, press_keys, scroll, drag, "
        "find_text, list_windows, window, open_app, clipboard, wait"
    )
    requires_display = True

    def __init__(self, displays: DisplayManager, scratch: Path) -> None:
        self.displays = displays
        self.scratch = scratch
        #: Screen pixels per screenshot pixel, per bot, from the last screenshot.
        self._scale: dict[str, float] = {}

    def desktop(self, bot_id: str) -> Desktop:
        return Desktop(self.displays.get(bot_id).name, owner=bot_id, scratch=self.scratch)

    def tools(self, context: ToolContext) -> list[SdkMcpTool[Any]]:
        bot_id = context.bot_id
        provider = self

        def to_screen(x: int, y: int) -> tuple[int, int]:
            scale = provider._scale.get(bot_id, 1.0)
            return round(x * scale), round(y * scale)

        def to_image(x: int, y: int) -> tuple[int, int]:
            scale = provider._scale.get(bot_id, 1.0)
            return round(x / scale), round(y / scale)

        async def guarded(action) -> ToolResult:
            try:
                return await action()
            except DesktopError as exc:
                return error_result(str(exc))

        @tool(
            "screenshot",
            "See your screen. Coordinates you pass to the other computer tools are pixels in "
            "this image (top-left is 0,0).",
            {},
        )
        async def screenshot(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                png, size, scale = await provider.capture(bot_id)
                note = (
                    f" (screen is {round(size[0] * scale)}x{round(size[1] * scale)})"
                    if scale != 1
                    else ""
                )
                return _image_result(png, f"Screenshot {size[0]}x{size[1]}{note}.")

            return await guarded(run)

        @tool(
            "click",
            "Click at a point. Use count=2 to double-click and button='right' for a context menu.",
            {
                "type": "object",
                "properties": {
                    "x": _POINT,
                    "y": _POINT,
                    "button": {"type": "string", "enum": ["left", "right", "middle"]},
                    "count": {"type": "integer", "minimum": 1, "maximum": 3},
                },
                "required": ["x", "y"],
            },
        )
        async def click(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                x, y = to_screen(args["x"], args["y"])
                count = int(args.get("count", 1))
                button = args.get("button", "left")
                await provider.desktop(bot_id).click(x, y, button=button, count=count)
                what = {1: "Clicked", 2: "Double-clicked", 3: "Triple-clicked"}[count]
                return text_result(f"{what} {button} at ({args['x']}, {args['y']}).")

            return await guarded(run)

        @tool("move_mouse", "Move the pointer, e.g. to hover over something.", {"x": int, "y": int})
        async def move_mouse(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                await provider.desktop(bot_id).move(*to_screen(args["x"], args["y"]))
                return text_result(f"Pointer at ({args['x']}, {args['y']}).")

            return await guarded(run)

        @tool(
            "drag",
            "Press the left button at one point, move to another, and release.",
            {"from_x": int, "from_y": int, "to_x": int, "to_y": int},
        )
        async def drag(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                start = to_screen(args["from_x"], args["from_y"])
                end = to_screen(args["to_x"], args["to_y"])
                await provider.desktop(bot_id).drag(start, end)
                return text_result("Dragged.")

            return await guarded(run)

        @tool(
            "scroll",
            "Scroll at a point.",
            {
                "type": "object",
                "properties": {
                    "x": _POINT,
                    "y": _POINT,
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                    "amount": {"type": "integer", "minimum": 1, "maximum": 30},
                },
                "required": ["x", "y", "direction"],
            },
        )
        async def scroll(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                x, y = to_screen(args["x"], args["y"])
                amount = int(args.get("amount", 5))
                await provider.desktop(bot_id).scroll(x, y, args["direction"], amount)
                return text_result(f"Scrolled {args['direction']} {amount}.")

            return await guarded(run)

        @tool(
            "type_text",
            "Type text into whatever has keyboard focus. Newlines press Return.",
            {"text": str},
        )
        async def type_text(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                await provider.desktop(bot_id).type_text(args["text"])
                return text_result(f"Typed {len(args['text'])} characters.")

            return await guarded(run)

        @tool(
            "press_keys",
            "Press keys or shortcuts in order, e.g. ['ctrl+l'], ['Return'], ['alt+F4'], "
            "['ctrl+shift+t']. Use ctrl (not cmd) for shortcuts on this Linux computer.",
            {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "minItems": 1}
                },
                "required": ["keys"],
            },
        )
        async def press_keys(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                pressed = await provider.desktop(bot_id).press(list(args["keys"]))
                return text_result(f"Pressed {', '.join(pressed)}.")

            return await guarded(run)

        @tool(
            "find_text",
            "Find text on screen with OCR and get its coordinates, so you can click it without "
            "guessing. Without `text`, lists every line of text on screen with its position.",
            {"type": "object", "properties": {"text": {"type": "string"}}},
        )
        async def find_text(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                lines = await provider.read_screen(bot_id)
                query = (args.get("text") or "").strip()
                if not query:
                    rows = [
                        f"({line.box.center[0]}, {line.box.center[1]}) {line.text}"
                        for line in lines
                    ]
                    return text_result("\n".join(rows[:300]) or "No text found on screen.")
                matches = ocr.find(lines, query)
                if not matches:
                    return text_result(f"“{query}” isn't visible on screen.")
                rows = [
                    f"({box.center[0]}, {box.center[1]}) in “{line.text}”"
                    for line, box in matches[:20]
                ]
                return text_result(f"Found “{query}” at:\n" + "\n".join(rows))

            return await guarded(run)

        @tool("list_windows", "List open windows with their ids, apps, titles, and positions.", {})
        async def list_windows(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                windows = await provider.desktop(bot_id).windows()
                if not windows:
                    return text_result("No windows are open.")
                rows = []
                for w in windows:
                    x, y = to_image(w.x, w.y)
                    width, height = to_image(w.width, w.height)
                    rows.append(f"{w.id}  {w.app}: {w.title}  at ({x}, {y}) {width}x{height}")
                return text_result("\n".join(rows))

            return await guarded(run)

        @tool(
            "window",
            "Focus, close, maximize, minimize, or move/resize a window. `target` is a window id "
            "from list_windows, or part of its title.",
            {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["focus", "close", "maximize", "minimize", "move"],
                    },
                    "target": {"type": "string"},
                    "x": _POINT,
                    "y": _POINT,
                    "width": {"type": "integer", "minimum": 50},
                    "height": {"type": "integer", "minimum": 50},
                },
                "required": ["action", "target"],
            },
        )
        async def window(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                desktop = provider.desktop(bot_id)
                target = await desktop.find_window(args["target"])
                action = args["action"]
                if action == "focus":
                    await desktop.focus_window(target)
                elif action == "close":
                    await desktop.close_window(target)
                elif action == "maximize":
                    await desktop.maximize_window(target)
                elif action == "minimize":
                    await desktop.minimize_window(target)
                else:
                    missing = [k for k in ("x", "y", "width", "height") if k not in args]
                    if missing:
                        return error_result(f"move needs {', '.join(missing)}")
                    x, y = to_screen(args["x"], args["y"])
                    width, height = to_screen(args["width"], args["height"])
                    await desktop.move_window(target, x, y, width, height)
                done = {
                    "focus": "Focused",
                    "close": "Closed",
                    "maximize": "Maximized",
                    "minimize": "Minimized",
                    "move": "Moved",
                }[action]
                return text_result(f"{done} “{target.title or target.id}”.")

            return await guarded(run)

        @tool(
            "open_app",
            "Start a graphical program on your display, e.g. 'xfce4-terminal', "
            "'thunar ~/workspaces', 'mousepad notes.txt'. For websites use the browser tools "
            "instead: they share the team's logins. It keeps running after your turn ends.",
            {"command": str},
        )
        async def open_app(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                argv = await provider.desktop(bot_id).open(args["command"])
                await asyncio.sleep(1.5)  # give the window a moment to appear
                return text_result(f"Started {argv[0]}. Take a screenshot to see it.")

            return await guarded(run)

        @tool(
            "clipboard",
            "Read or replace the clipboard of your desktop.",
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["read", "write"]},
                    "text": {"type": "string"},
                },
                "required": ["action"],
            },
        )
        async def clipboard(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                desktop = provider.desktop(bot_id)
                if args["action"] == "write":
                    await desktop.clipboard_write(args.get("text", ""))
                    return text_result("Clipboard set.")
                content = await desktop.clipboard_read()
                return text_result(content if content else "(the clipboard is empty)")

            return await guarded(run)

        @tool(
            "wait",
            "Wait for something on screen to finish (loading, animations), up to 30 seconds.",
            {
                "type": "object",
                "properties": {"seconds": {"type": "number", "minimum": 0.1, "maximum": 30}},
            },
        )
        async def wait(args: dict[str, Any]) -> ToolResult:
            seconds = float(args.get("seconds", 2))
            await asyncio.sleep(min(max(seconds, 0.1), 30))
            return text_result(f"Waited {seconds:g}s.")

        return [
            screenshot, click, move_mouse, drag, scroll, type_text, press_keys,
            find_text, list_windows, window, open_app, clipboard, wait,
        ]  # fmt: skip

    # -- screen capture ------------------------------------------------------

    async def capture(self, bot_id: str) -> tuple[bytes, tuple[int, int], float]:
        """A PNG screenshot scaled to fit MAX_SCREENSHOT, its size, and the scale."""

        path = await self.desktop(bot_id).screenshot()
        png, size, scale = await asyncio.to_thread(_fit, path)
        self._scale[bot_id] = scale
        return png, size, scale

    async def read_screen(self, bot_id: str) -> list[ocr.Line]:
        """Text on screen, with boxes in screenshot coordinates."""

        desktop = self.desktop(bot_id)
        path = await desktop.screenshot()
        lines = ocr.parse_tsv(await desktop.recognize_text(path))
        if bot_id not in self._scale:
            _, _, self._scale[bot_id] = await asyncio.to_thread(_fit, path)
        scale = self._scale[bot_id]
        if scale == 1:
            return lines
        return [
            ocr.Line(
                line.text,
                line.box.scaled(scale),
                tuple(ocr.Word(w.text, w.box.scaled(scale), w.line) for w in line.words),
            )
            for line in lines
        ]


def _fit(path: Path) -> tuple[bytes, tuple[int, int], float]:
    with Image.open(path) as image:
        width, height = image.size
        scale = max(width / MAX_SCREENSHOT[0], height / MAX_SCREENSHOT[1], 1.0)
        if scale > 1:
            image = image.resize((round(width / scale), round(height / scale)), Image.LANCZOS)
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), image.size, scale
