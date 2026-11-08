from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from pal.config import DisplaySettings
from pal.displays import DisplayManager, InMemoryDisplayBackend
from pal.tools.computer import ComputerTools, DesktopError, normalize_keys, ocr, parse_windows
from pal.tools.computer import provider as provider_module
from pal.tools.computer.desktop import Desktop
from tests.tools.helpers import handlers, text

HEADER = "level page_num block_num par_num line_num word_num left top width height conf text"
TSV = (
    HEADER.replace(" ", "\t")
    + """
5\t1\t1\t1\t1\t1\t100\t50\t40\t12\t96\tSave
5\t1\t1\t1\t1\t2\t145\t50\t20\t12\t95\tas…
5\t1\t2\t1\t1\t1\t400\t300\t60\t14\t91\tCancel
5\t1\t2\t1\t1\t2\t470\t300\t10\t14\t12\tzz
4\t1\t2\t1\t1\t0\t400\t300\t80\t14\t-1\t
"""
)


@pytest.mark.parametrize(
    ("combo", "expected"),
    [
        ("ctrl+s", "ctrl+s"),
        ("Cmd+Enter", "ctrl+Return"),
        ("alt+f4", "alt+F4"),
        ("PageDown", "Page_Down"),
        ("ctrl+shift+t", "ctrl+shift+t"),
        ("Escape", "Escape"),
    ],
)
def test_key_normalization(combo: str, expected: str) -> None:
    assert normalize_keys(combo) == expected


def test_invalid_key_combination() -> None:
    with pytest.raises(DesktopError):
        normalize_keys("ctrl++")


def test_window_list_parsing() -> None:
    output = (
        "0x01400003  0 4242 10 20 800 600  xfce4-terminal.Xfce4-terminal pal Terminal - pal@pal\n"
        "0x00e00011 -1 1111 0 0 1280 800  xfdesktop.Xfdesktop pal Desktop\n"
        "garbage line\n"
    )
    (window,) = parse_windows(output)
    assert (window.id, window.pid, window.width, window.app) == (
        "0x01400003",
        4242,
        800,
        "Xfce4-terminal",
    )
    assert window.title == "Terminal - pal@pal"


def test_ocr_lines_and_search() -> None:
    lines = ocr.parse_tsv(TSV)
    assert [line.text for line in lines] == ["Save as…", "Cancel"]  # low-confidence word dropped
    ((line, box),) = ocr.find(lines, "save as")
    assert line.text == "Save as…"
    assert box.center == (132, 56)
    assert ocr.find(lines, "cancel")[0][1].center == (430, 307)
    assert ocr.find(lines, "missing") == []
    assert ocr.find(lines, "Canc")  # partial last word, as you'd type it


def word(text: str, left: int, top: int, width: int, height: int, confidence: float = 95):
    return ocr.Word(text, ocr.Box(left, top, width, height), confidence)


def test_lines_are_grouped_by_position() -> None:
    # Real word boxes from an editor (2x screen), which Tesseract put in separate
    # blocks, and a menu bar whose items are farther apart than words are.
    words = [
        word("row", 21, 184, 49, 16), word("number", 91, 178, 103, 22), word("0", 216, 180, 14, 20),
        word("row", 21, 220, 49, 16), word("number", 91, 214, 103, 22), word("1", 218, 216, 12, 20),
        word("Edit", 103, 130, 41, 20), word("Search", 180, 131, 78, 19),
    ]  # fmt: skip
    lines = [line.text for line in ocr.group_lines(words)]
    assert lines == ["Edit", "Search", "row number 0", "row number 1"]
    ((_, box),) = ocr.find(ocr.group_lines(words), "row number 1")
    assert box == ocr.Box(21, 214, 209, 22)


def test_readings_are_merged_keeping_the_surer_word() -> None:
    sparse = [word("number", 91, 178, 103, 22, 96), word("O", 216, 180, 14, 20, 50)]
    automatic = [word("0", 217, 181, 13, 19, 93), word("row", 21, 184, 49, 16, 92)]
    merged = ocr.merge(sparse, automatic)
    assert sorted(w.text for w in merged) == ["0", "number", "row"]


class FakeDesktop(Desktop):
    calls: list[tuple] = []
    opened: list[str] = []
    screen = (2560, 1600)
    tree: dict = {"windows": []}

    async def run(self, *args, stdin=None, time_limit=20):
        FakeDesktop.calls.append(args)
        if args[0] == "scrot":
            Image.new("RGB", FakeDesktop.screen, "white").save(args[-1])
        if args[0] == "tesseract":
            return TSV
        if args[:2] == ("xdotool", "getdisplaygeometry"):
            return f"{FakeDesktop.screen[0]} {FakeDesktop.screen[1]}\n"
        if args[0] == "pal-screen":
            return json.dumps(FakeDesktop.tree)
        if args[0] == "pal-open":
            FakeDesktop.opened.append(
                "0x01600001  0 2 50 50 600 400  mousepad.Mousepad pal Untitled 1 - Mousepad\n"
            )
        if args[0] == "wmctrl" and args[1] == "-lpGx":
            listing = (
                "0x01400003  0 1 100 100 400 300  mousepad.Mousepad pal notes.txt - Mousepad\n"
            )
            return listing + "".join(FakeDesktop.opened)
        return ""


@pytest.fixture
def computer(tmp_path: Path, monkeypatch) -> ComputerTools:
    FakeDesktop.calls = []
    FakeDesktop.screen = (2560, 1600)
    FakeDesktop.tree = {"windows": []}
    FakeDesktop.opened = []
    monkeypatch.setattr(provider_module, "OPEN_SETTLE", 0)
    displays = DisplayManager(
        DisplaySettings(backend="simulated"), InMemoryDisplayBackend(), tmp_path / "d.json"
    )
    displays.register(["atlas"])
    provider = ComputerTools(displays, tmp_path / "screens")
    monkeypatch.setattr(
        provider, "desktop", lambda bot: FakeDesktop(":10", owner=bot, scratch=tmp_path / "screens")
    )
    return provider


async def test_screenshot_is_scaled_and_clicks_map_back(computer: ComputerTools) -> None:
    tools = handlers(computer)
    shot = await tools["screenshot"]({})
    image, caption = shot["content"]
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    assert caption["text"] == "Screenshot 1280x800 (screen is 2560x1600)."

    await tools["click"]({"x": 100, "y": 50, "count": 2})
    assert FakeDesktop.calls[-1][:5] == ("xdotool", "mousemove", "--sync", "200", "100")
    assert FakeDesktop.calls[-1][-3:] == ("--delay", "80", "1")


async def test_find_text_uses_screenshot_coordinates(computer: ComputerTools) -> None:
    tools = handlers(computer)
    await tools["screenshot"]({})
    found = text(await tools["find_text"]({"text": "cancel"}))
    assert found == "Found “cancel” at:\n(215, 153) in “Cancel”"
    everything = text(await tools["find_text"]({}))
    assert "Save as…" in everything and "Cancel" in everything


async def test_windows_and_keys(computer: ComputerTools) -> None:
    tools = handlers(computer)
    listed = text(await tools["list_windows"]({}))
    assert "0x01400003  Mousepad: notes.txt - Mousepad" in listed
    result = await tools["window"]({"action": "focus", "target": "notes"})
    assert text(result) == "Focused “notes.txt - Mousepad”."
    assert FakeDesktop.calls[-1] == ("wmctrl", "-i", "-a", "0x01400003")
    missing = await tools["window"]({"action": "close", "target": "nothing"})
    assert missing["is_error"] is True
    pressed = await tools["press_keys"]({"keys": ["cmd+l", "Return"]})
    assert text(pressed) == "Pressed ctrl+l, Return."


async def test_open_app_uses_pal_open(computer: ComputerTools) -> None:
    result = await handlers(computer)["open_app"]({"command": "mousepad 'my notes.txt'"})
    assert text(result) == "Started mousepad: its window “Untitled 1 - Mousepad” is open."
    assert ("pal-open", "mousepad", "my notes.txt") in FakeDesktop.calls


def test_provider_requires_display(computer: ComputerTools) -> None:
    assert computer.requires_display is True
    assert (
        len(computer.tools(__import__("pal.tools", fromlist=["ToolContext"]).ToolContext("atlas")))
        == 14
    )


async def test_tools_wake_the_display_first(computer: ComputerTools) -> None:
    assert computer.displays.get("atlas").state == "stopped"
    await handlers(computer)["list_windows"]({})
    assert computer.displays.get("atlas").state == "running"


async def test_small_screens_are_enlarged_for_text_recognition(computer: ComputerTools) -> None:
    # On a 1280x800 screen the recognizer reads a 2x copy, so its boxes are halved.
    FakeDesktop.screen = (1280, 800)
    found = text(await handlers(computer)["find_text"]({"text": "cancel"}))
    assert found == "Found “cancel” at:\n(215, 153) in “Cancel”"
    ocr_call = next(call for call in FakeDesktop.calls if call[0] == "tesseract")
    assert ocr_call[1].endswith("screen-atlas-ocr.png")


async def test_open_app_says_when_no_window_appears(computer: ComputerTools, monkeypatch) -> None:
    monkeypatch.setattr(provider_module, "OPEN_WAIT", 0)
    # A program that reuses an existing window adds nothing to the window list.
    original = FakeDesktop.run

    async def no_new_window(self, *args, **kwargs):
        if args[0] == "pal-open":
            FakeDesktop.calls.append(args)
            return ""
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(FakeDesktop, "run", no_new_window)
    result = await handlers(computer)["open_app"]({"command": "mousepad"})
    assert "no new window appeared" in text(result)


async def test_drag_moves_in_steps_with_the_button_held(computer: ComputerTools) -> None:
    await handlers(computer)["screenshot"]({})
    await handlers(computer)["drag"]({"from_x": 10, "from_y": 20, "to_x": 110, "to_y": 220})
    call = FakeDesktop.calls[-1]
    assert call[:7] == ("xdotool", "mousemove", "--sync", "20", "40", "mousedown", "1")
    moves = [call[i + 1 : i + 3] for i, arg in enumerate(call) if arg == "mousemove"][1:]
    assert len(moves) == 15 and moves[-1] == ("220", "440")  # screen is 2x the screenshot
    assert call[-2:] == ("mouseup", "1")


def test_typing_is_paced_for_people_to_follow() -> None:
    from pal.tools.pace import key_delay_ms

    assert key_delay_ms(20) == 45  # short text: a quick typist
    assert key_delay_ms(1000) == 15  # long text speeds up to finish in about 15s
    assert key_delay_ms(100_000) == 8  # but never faster than this


async def test_type_text_types_key_by_key(computer: ComputerTools) -> None:
    await handlers(computer)["type_text"]({"text": "hello"})
    assert FakeDesktop.calls[-1] == ("xdotool", "type", "--delay", "45", "--", "hello")


def node(depth, role, name="", text="", states=(), box=(0, 0, 10, 10)) -> dict:
    return {
        "depth": depth, "role": role, "name": name, "text": text,
        "states": list(states), "box": list(box),
    }  # fmt: skip


async def test_read_screen_describes_the_active_window(computer: ComputerTools) -> None:
    FakeDesktop.tree = {
        "windows": [
            {
                "app": "mousepad", "title": "notes.txt - Mousepad", "role": "frame",
                "active": True, "box": [0, 54, 1280, 900], "truncated": False,
                "nodes": [
                    node(0, "menu bar", box=(10, 112, 1200, 54)),
                    node(1, "menu", "File", box=(10, 112, 74, 54)),
                    node(0, "push button", "Save", states=["disabled"], box=(200, 200, 100, 40)),
                    node(0, "text", text="first line\nsecond line\n",
                         states=["focused", "editable"], box=(12, 172, 1196, 734)),
                ],
            },
            {
                "app": "Thunar", "title": "workspaces - Thunar", "role": "frame",
                "active": False, "box": [1300, 0, 1200, 800], "nodes": None, "truncated": False,
            },
        ]
    }  # fmt: skip
    seen = text(await handlers(computer)["read_screen"]({}))
    assert seen.splitlines()[:4] == [
        "Screen 1280x800. Points are where to click, in screenshot pixels.",
        "Windows:",
        "  “notes.txt - Mousepad” — mousepad at (0, 27) 640x450 (active)",
        "  “workspaces - Thunar” — Thunar at (650, 0) 600x400",
    ]
    assert "  menu “File” @ (24, 70)" in seen  # screen is twice the screenshot's size
    assert "button “Save” (disabled) @ (125, 110)" in seen
    assert "text area (focused, editable) @ (305, 270)" in seen
    assert "  │ first line\n  │ second line" in seen
    assert "Text read from the pixels" not in seen  # the tree said plenty
    assert not any(call[0] == "scrot" for call in FakeDesktop.calls)  # no screenshot taken
    # The points match a screenshot's pixels, so clicks land where they say.
    await handlers(computer)["click"]({"x": 125, "y": 110})
    assert FakeDesktop.calls[-1][:5] == ("xdotool", "mousemove", "--sync", "250", "220")


async def test_read_screen_reads_pixels_where_the_tree_is_empty(computer: ComputerTools) -> None:
    FakeDesktop.tree = {
        "windows": [
            {
                "app": "oldapp", "title": "Old App", "role": "frame", "active": True,
                "box": [0, 0, 2560, 1600], "nodes": [node(0, "filler")], "truncated": False,
            }
        ]
    }  # fmt: skip
    seen = text(await handlers(computer)["read_screen"]({}))
    assert "Text read from the pixels of this window:" in seen
    assert "  “Cancel” @ (215, 153)" in seen


async def test_read_screen_can_describe_another_window(computer: ComputerTools) -> None:
    FakeDesktop.tree = {
        "windows": [
            {"app": "a", "title": "Alpha", "role": "frame", "active": True, "box": [0, 0, 9, 9],
             "nodes": [node(0, "push button", "One")], "truncated": False},
            {"app": "b", "title": "Beta", "role": "frame", "active": False, "box": [0, 0, 9, 9],
             "nodes": [node(0, "push button", "Two")], "truncated": False},
        ]
    }  # fmt: skip
    seen = text(await handlers(computer)["read_screen"]({"window": "beta"}))
    assert "“Two”" in seen and "“One”" not in seen
    reading = next(call for call in FakeDesktop.calls if call[0] == "pal-screen")
    assert reading[-1] == "--all"  # every window's controls, to pick from
    missing = await handlers(computer)["read_screen"]({"window": "gamma"})
    assert missing["is_error"] is True


def test_text_recognition_passes_do_not_fight_over_the_cores(tmp_path: Path) -> None:
    desktop = Desktop(":10", owner="atlas", scratch=tmp_path)
    assert desktop.environment["OMP_THREAD_LIMIT"] == "1"
