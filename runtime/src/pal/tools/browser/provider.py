"""Tools for browsing the web in the bot's own browser."""

from __future__ import annotations

import base64
import io
import re
from typing import Any

from claude_agent_sdk import SdkMcpTool, tool
from PIL import Image
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

from ..base import ToolContext, ToolProvider, ToolResult, error_result, text_result
from .session import BrowserError, Browsers, normalize_url

MAX_SNAPSHOT = 15000
MAX_TEXT = 20000
ACTION_TIMEOUT_MS = 15000

_TARGET = {
    "role": {
        "type": "string",
        "description": "Accessible role from browser_snapshot, e.g. button, link, textbox.",
    },
    "name": {"type": "string", "description": "Accessible name, used with role."},
    "label": {"type": "string", "description": "Text of the field's label."},
    "placeholder": {"type": "string"},
    "text": {"type": "string", "description": "Visible text of the element."},
    "selector": {"type": "string", "description": "CSS selector, as a last resort."},
    "nth": {"type": "integer", "minimum": 0, "description": "Which match, when several match."},
}


def locate(page: Page, args: dict[str, Any]) -> Locator:
    """Turn a target description into a Playwright locator."""

    if args.get("selector"):
        locator = page.locator(args["selector"])
    elif args.get("role"):
        locator = page.get_by_role(args["role"], name=args.get("name") or None)
    elif args.get("label"):
        locator = page.get_by_label(args["label"])
    elif args.get("placeholder"):
        locator = page.get_by_placeholder(args["placeholder"])
    elif args.get("text"):
        locator = page.get_by_text(args["text"])
    else:
        raise BrowserError(
            "say what to act on: role (+ name), label, placeholder, text, or selector"
        )
    return locator.nth(int(args.get("nth", 0)))


def describe_target(args: dict[str, Any]) -> str:
    if args.get("role"):
        return f"{args['role']} “{args.get('name', '')}”".strip()
    for key in ("label", "placeholder", "text", "selector"):
        if args.get(key):
            return f"{key} “{args[key]}”"
    return "element"


def _short_error(exc: Exception) -> str:
    message = str(exc).split("\n")[0]
    return re.sub(r"\s+", " ", message)[:400]


async def _where(page: Page) -> str:
    try:
        title = await page.title()
    except PlaywrightError:
        title = ""
    return f"Now on: {title or '(untitled)'} — {page.url}"


def _fit_png(png: bytes, max_width: int = 1280) -> bytes:
    with Image.open(io.BytesIO(png)) as image:
        if image.width <= max_width:
            return png
        height = round(image.height * max_width / image.width)
        buffer = io.BytesIO()
        image.resize((max_width, height), Image.LANCZOS).save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


class BrowserTools(ToolProvider):
    name = "browser"
    description = (
        "your own web browser, signed in wherever your teammates are: browser_open, "
        "browser_snapshot, browser_click, browser_type, browser_press, browser_read, "
        "browser_screenshot, browser_tabs, browser_navigate, browser_scroll, browser_wait, "
        "browser_eval"
    )
    # The browser runs on the bot's own display.
    requires_display = True

    def __init__(self, browsers: Browsers) -> None:
        self.browsers = browsers

    def tools(self, context: ToolContext) -> list[SdkMcpTool[Any]]:
        bot_id, browsers = context.bot_id, self.browsers

        async def guarded(action) -> ToolResult:
            try:
                return await action()
            except BrowserError as exc:
                return error_result(str(exc))
            except PlaywrightError as exc:
                return error_result(_short_error(exc))

        @tool(
            "browser_open",
            "Open a web page in your browser (Chromium, on your display). Logins carry "
            "over between everyone's browsers, so you are signed in wherever your "
            "teammates or the user are.",
            {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "new_tab": {"type": "boolean", "description": "Keep the current tab open."},
                },
                "required": ["url"],
            },
        )
        async def browser_open(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                url = normalize_url(args["url"])
                page = (
                    await browsers.new_tab(bot_id)
                    if args.get("new_tab")
                    else await browsers.page(bot_id)
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                return text_result(await _where(page))

            return await guarded(run)

        @tool(
            "browser_snapshot",
            "The page's structure as an accessibility tree (roles, names, text). Use the "
            "role and name from it to click and type. Cheaper and more precise than a "
            "screenshot for most pages.",
            {},
        )
        async def browser_snapshot(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                tree = await page.locator("body").aria_snapshot(timeout=ACTION_TIMEOUT_MS)
                if len(tree) > MAX_SNAPSHOT:
                    tree = tree[:MAX_SNAPSHOT] + "\n… (truncated; scroll or use browser_read)"
                return text_result(f"{await _where(page)}\n\n{tree}")

            return await guarded(run)

        @tool(
            "browser_click",
            "Click an element, found by role + name (preferred), label, placeholder, text, "
            "or CSS selector.",
            {"type": "object", "properties": _TARGET},
        )
        async def browser_click(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                await locate(page, args).click(timeout=ACTION_TIMEOUT_MS)
                await page.wait_for_load_state("domcontentloaded", timeout=ACTION_TIMEOUT_MS)
                return text_result(f"Clicked {describe_target(args)}. {await _where(page)}")

            return await guarded(run)

        @tool(
            "browser_type",
            "Fill a field with text (replacing what's there), found like browser_click. Set "
            "submit to press Enter afterwards.",
            {
                "type": "object",
                "properties": {
                    **_TARGET,
                    "value": {"type": "string", "description": "The text to enter."},
                    "submit": {"type": "boolean"},
                },
                "required": ["value"],
            },
        )
        async def browser_type(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                field = locate(page, args)
                await field.fill(args["value"], timeout=ACTION_TIMEOUT_MS)
                if args.get("submit"):
                    await field.press("Enter", timeout=ACTION_TIMEOUT_MS)
                    await page.wait_for_load_state("domcontentloaded", timeout=ACTION_TIMEOUT_MS)
                done = "Entered and submitted" if args.get("submit") else "Entered"
                return text_result(f"{done} text in {describe_target(args)}. {await _where(page)}")

            return await guarded(run)

        @tool(
            "browser_press",
            "Press keys in the page, e.g. ['Enter'], ['Control+a'], ['Escape'], ['Tab'].",
            {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "minItems": 1}
                },
                "required": ["keys"],
            },
        )
        async def browser_press(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                for key in args["keys"]:
                    await page.keyboard.press(key)
                return text_result(f"Pressed {', '.join(args['keys'])}. {await _where(page)}")

            return await guarded(run)

        @tool(
            "browser_read",
            "The visible text of the page (or of one element), for reading articles, results, "
            "and documents.",
            {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "Only this part of the page."},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 100000},
                },
            },
        )
        async def browser_read(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                text = await page.locator(args.get("selector") or "body").first.inner_text(
                    timeout=ACTION_TIMEOUT_MS
                )
                limit = int(args.get("max_chars", MAX_TEXT))
                if len(text) > limit:
                    text = text[:limit] + f"\n… ({len(text) - limit} more characters)"
                return text_result(f"{await _where(page)}\n\n{text}")

            return await guarded(run)

        @tool(
            "browser_screenshot",
            "See the page as rendered, when layout or images matter.",
            {"type": "object", "properties": {"full_page": {"type": "boolean"}}},
        )
        async def browser_screenshot(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                await page.bring_to_front()
                png = await page.screenshot(full_page=bool(args.get("full_page")), timeout=30000)
                return {
                    "content": [
                        {
                            "type": "image",
                            "data": base64.b64encode(_fit_png(png)).decode(),
                            "mimeType": "image/png",
                        },
                        {"type": "text", "text": await _where(page)},
                    ]
                }

            return await guarded(run)

        @tool(
            "browser_tabs",
            "List, open, switch to, or close your tabs. Indexes come from 'list'.",
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "new", "switch", "close"]},
                    "index": {"type": "integer", "minimum": 0},
                    "url": {"type": "string"},
                },
                "required": ["action"],
            },
        )
        async def browser_tabs(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                action = args["action"]
                if action == "new":
                    page = await browsers.new_tab(bot_id)
                    if args.get("url"):
                        await page.goto(args["url"], wait_until="domcontentloaded", timeout=45000)
                    return text_result(f"Opened a tab. {await _where(page)}")
                await browsers.page(bot_id)
                tabs = browsers.tabs(bot_id)
                if action == "list":
                    current = await browsers.page(bot_id)
                    rows = []
                    for i, tab in enumerate(tabs):
                        marker = "*" if tab is current else " "
                        rows.append(
                            f"{marker} [{i}] {await tab.title() or '(untitled)'} — {tab.url}"
                        )
                    return text_result("\n".join(rows) or "You have no tabs.")
                index = int(args.get("index", -1))
                if not 0 <= index < len(tabs):
                    return error_result(f"no tab {index}; you have {len(tabs)} (see 'list')")
                if action == "switch":
                    browsers.select(bot_id, tabs[index])
                    return text_result(await _where(tabs[index]))
                await browsers.close_tab(bot_id, tabs[index])
                return text_result(f"Closed tab {index}.")

            return await guarded(run)

        @tool(
            "browser_navigate",
            "Go back, forward, or reload the current tab.",
            {
                "type": "object",
                "properties": {"action": {"type": "string", "enum": ["back", "forward", "reload"]}},
                "required": ["action"],
            },
        )
        async def browser_navigate(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                options = {"wait_until": "domcontentloaded", "timeout": 45000}
                if args["action"] == "back":
                    await page.go_back(**options)
                elif args["action"] == "forward":
                    await page.go_forward(**options)
                else:
                    await page.reload(**options)
                return text_result(await _where(page))

            return await guarded(run)

        @tool(
            "browser_scroll",
            "Scroll the page.",
            {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "top", "bottom"]},
                    "screens": {"type": "number", "minimum": 0.1, "maximum": 20},
                },
                "required": ["direction"],
            },
        )
        async def browser_scroll(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                script = {
                    "top": "() => window.scrollTo(0, 0)",
                    "bottom": "() => window.scrollTo(0, document.body.scrollHeight)",
                    "up": "s => window.scrollBy(0, -s * window.innerHeight)",
                    "down": "s => window.scrollBy(0, s * window.innerHeight)",
                }[args["direction"]]
                await page.evaluate(script, float(args.get("screens", 1)))
                return text_result(f"Scrolled {args['direction']}.")

            return await guarded(run)

        @tool(
            "browser_wait",
            "Wait until some text appears on the page, or for a number of seconds (max 60).",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "seconds": {"type": "number", "minimum": 0.1, "maximum": 60},
                },
            },
        )
        async def browser_wait(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                page = await browsers.page(bot_id)
                seconds = float(args.get("seconds", 10))
                if args.get("text"):
                    await page.get_by_text(args["text"]).first.wait_for(timeout=seconds * 1000)
                    return text_result(f"“{args['text']}” is on the page.")
                await page.wait_for_timeout(min(seconds, 60) * 1000)
                return text_result(f"Waited {seconds:g}s. {await _where(page)}")

            return await guarded(run)

        @tool(
            "browser_eval",
            "Run JavaScript in the page and get the result back as JSON. For extracting data "
            "the other tools can't reach.",
            {"script": str},
        )
        async def browser_eval(args: dict[str, Any]) -> ToolResult:
            async def run() -> ToolResult:
                import json

                page = await browsers.page(bot_id)
                value = await page.evaluate(args["script"])
                text = json.dumps(value, indent=2, default=str)
                if len(text) > MAX_TEXT:
                    text = text[:MAX_TEXT] + "\n… (truncated)"
                return text_result(text)

            return await guarded(run)

        return [
            browser_open, browser_snapshot, browser_click, browser_type, browser_press,
            browser_read, browser_screenshot, browser_tabs, browser_navigate, browser_scroll,
            browser_wait, browser_eval,
        ]  # fmt: skip
