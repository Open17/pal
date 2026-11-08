"""Tools for operating a bot's desktop: see it, point, type, manage windows."""

from __future__ import annotations

import asyncio
import base64
import io
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool, tool
from PIL import Image

from pal.displays import DisplayBackendError, DisplayManager

from ..base import ToolContext, ToolProvider, ToolResult, error_result, text_result
from . import ocr, screen
from .desktop import Desktop, DesktopError, Window

#: Screenshots are scaled to fit this box; coordinates map back to the screen.
MAX_SCREENSHOT = (1280, 800)
#: How long open_app waits for the program's window, and for the windows to
#: stop changing (splash screens, stand-in windows) before it reports back.
OPEN_WAIT = 15.0
OPEN_SETTLE = 0.75
#: Screens narrower than this are enlarged before text recognition.
OCR_ENLARGE_BELOW = 2000
#: Tesseract page segmentation modes: sparse text, automatic, single column.
OCR_LAYOUTS = (11, 3, 4)

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
            # Wake the display here too, so the tools never act on a display
            # that is not running, whoever calls them.
            try:
                await provider.displays.ensure_awake(bot_id)
            except DisplayBackendError as exc:
                return error_result(f"your display could not be started: {exc}")
            try:
                return await action()
            except DesktopError as exc:
                return error_result(str(exc))

        @tool(
            "read_screen",
            "See what is on your screen, as text: the open windows, and the buttons, menus, "
            "fields and text of the active window, each with the point to click. Exact, and "
            "far cheaper than a screenshot, so look with this first; take a screenshot when "
            "you need to see pictures, colors, or layout. `window` (part of a title) "
            "describes that window instead; `all` describes every window.",
            {
                "type": "object",
                "properties": {
                    "window": {"type": "string"},
                    "all": {"type": "boolean"},
                },
            },
        )
        async def read_screen(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                return text_result(
                    await provider.describe_screen(
                        bot_id, window=args.get("window"), all_windows=bool(args.get("all"))
                    )
                )

            return await guarded(run)

        @tool(
            "screenshot",
            "See your screen as an image. Coordinates you pass to the other computer tools "
            "are pixels in this image (top-left is 0,0). read_screen is cheaper when you "
            "only need to know what's there.",
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
                lines = await provider.recognize_screen(bot_id)
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
                desktop = provider.desktop(bot_id)
                before = {w.id for w in await desktop.windows()}
                argv = await desktop.open(args["command"])
                window = await _new_window(desktop, before)
                if window is None:
                    return text_result(
                        f"Started {argv[0]}, but no new window appeared within "
                        f"{OPEN_WAIT:g}s. It may still be loading, or it reused a window "
                        "that was already open. Take a screenshot to check."
                    )
                return text_result(f"Started {argv[0]}: its window “{window.title}” is open.")

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
            read_screen, screenshot, click, move_mouse, drag, scroll, type_text, press_keys,
            find_text, list_windows, window, open_app, clipboard, wait,
        ]  # fmt: skip

    # -- screen capture ------------------------------------------------------

    async def capture(self, bot_id: str) -> tuple[bytes, tuple[int, int], float]:
        """A PNG screenshot scaled to fit MAX_SCREENSHOT, its size, and the scale."""

        path = await self.desktop(bot_id).screenshot()
        png, size, scale = await asyncio.to_thread(_fit, path)
        self._scale[bot_id] = scale
        return png, size, scale

    async def describe_screen(
        self, bot_id: str, *, window: str | None = None, all_windows: bool = False
    ) -> str:
        """The screen as text, from the accessibility tree (see ``screen``)."""

        desktop = self.desktop(bot_id)
        size = await desktop.screen_size()
        # Same scale a screenshot would have, so the points match its pixels.
        scale = max(size[0] / MAX_SCREENSHOT[0], size[1] / MAX_SCREENSHOT[1], 1.0)
        self._scale[bot_id] = scale
        data = await desktop.accessibility(screen=size, all_windows=bool(window) or all_windows)
        if window:
            needle = window.lower()
            for entry in data.get("windows", []):
                if needle not in entry["title"].lower() and needle != entry["app"].lower():
                    entry["nodes"] = None
            if all(entry["nodes"] is None for entry in data.get("windows", [])):
                raise DesktopError(f"no window matches {window!r}")

        def to_image(x: int, y: int) -> tuple[int, int]:
            return round(x / scale), round(y / scale)

        lines: list[ocr.Line] | None = None

        async def pixels(box: list[int]) -> list[ocr.Line]:
            nonlocal lines
            if lines is None:
                lines = await self.recognize_screen(bot_id)
            x, y, w, h = (round(v / scale) for v in box)
            return [
                line
                for line in lines
                if x <= line.box.center[0] <= x + w and y <= line.box.center[1] <= y + h
            ]

        # Text read from pixels is only needed for windows the tree says little about.
        sparse_boxes = [
            entry["box"]
            for entry in data.get("windows", [])
            if entry.get("nodes") is not None
            and entry.get("box")
            and sum(1 for n in entry["nodes"] if n["name"] or n["text"].strip()) < screen.SPARSE
        ]
        found = {tuple(box): await pixels(box) for box in sparse_boxes}
        return screen.describe(
            data,
            to_image,
            screen=size,
            pixel_text=lambda box: found.get(tuple(box), []),
        )

    async def recognize_screen(self, bot_id: str) -> list[ocr.Line]:
        """Text on screen, with boxes in screenshot coordinates."""

        desktop = self.desktop(bot_id)
        path = await desktop.screenshot()
        prepared, enlarged = await asyncio.to_thread(_prepare_for_ocr, path)
        # Each layout mode misses text the others read: sparse mode finds
        # scattered interface text, automatic and single-column layout read runs
        # of text and lone characters. Run in parallel, all three take about as
        # long as one.
        readings = await asyncio.gather(
            *(desktop.recognize_text(prepared, layout=layout) for layout in OCR_LAYOUTS)
        )
        lines = ocr.group_lines(ocr.merge(*(ocr.parse_words(tsv) for tsv in readings)))
        if bot_id not in self._scale:
            _, _, self._scale[bot_id] = await asyncio.to_thread(_fit, path)
        factor = self._scale[bot_id] * enlarged
        if factor == 1:
            return lines
        return [
            ocr.Line(
                line.text,
                line.box.scaled(factor),
                tuple(ocr.Word(w.text, w.box.scaled(factor), w.confidence) for w in line.words),
            )
            for line in lines
        ]


async def _new_window(desktop: Desktop, before: set[str]) -> Window | None:
    """The program's new window, once the windows have settled.

    Some programs show a splash or stand-in window first, so this waits until
    no window has come or gone for OPEN_SETTLE seconds (up to OPEN_WAIT) and
    returns the newest window that was not in ``before``.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + OPEN_WAIT
    seen: list[str] | None = None
    steady_since = loop.time()
    while True:
        windows = await desktop.windows()
        fresh = [w for w in windows if w.id not in before]
        now = loop.time()
        ids = [w.id for w in windows]
        if ids != seen:
            seen, steady_since = ids, now
        if fresh and now - steady_since >= OPEN_SETTLE:
            return fresh[-1]
        if now >= deadline:
            return fresh[-1] if fresh else None
        await asyncio.sleep(0.25)


def _prepare_for_ocr(path: Path) -> tuple[Path, int]:
    """A grayscale copy for text recognition, enlarged when the screen's text is small.

    Text recognition misses most interface text at ordinary screen sizes; at
    twice the size it reads menus, titles and window contents reliably.
    """

    with Image.open(path) as image:
        enlarge = 2 if image.width < OCR_ENLARGE_BELOW else 1
        gray = image.convert("L")
        if enlarge > 1:
            gray = gray.resize((image.width * enlarge, image.height * enlarge), Image.LANCZOS)
        prepared = path.with_name(f"{path.stem}-ocr.png")
        gray.save(prepared)
        return prepared, enlarge


def _fit(path: Path) -> tuple[bytes, tuple[int, int], float]:
    with Image.open(path) as image:
        width, height = image.size
        scale = max(width / MAX_SCREENSHOT[0], height / MAX_SCREENSHOT[1], 1.0)
        if scale > 1:
            image = image.resize((round(width / scale), round(height / scale)), Image.LANCZOS)
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), image.size, scale
