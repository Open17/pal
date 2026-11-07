from __future__ import annotations

from pathlib import Path

from pal.config import DisplaySettings
from pal.displays import Display, SystemdDisplayBackend


def test_systemd_environment_file(tmp_path: Path) -> None:
    backend = SystemdDisplayBackend(DisplaySettings(geometry="1280x800"), tmp_path)
    display = Display("atlas", 10, 15910, 5910)
    assert backend.unit(display) == "pal-display@atlas.service"
    assert backend.slice(display) == "pal-display-atlas.slice"
    text = backend.write_environment(display).read_text()
    assert "PAL_DISPLAY_NUMBER=10\n" in text
    assert "PAL_VNC_PORT=15910\n" in text
    assert "PAL_DISPLAY_GEOMETRY=1280x800\n" in text


async def test_probe_parses_unit_properties(tmp_path: Path, monkeypatch) -> None:
    backend = SystemdDisplayBackend(DisplaySettings(), tmp_path)
    display = Display("atlas", 10, 15910, 5910)
    # The service's block, a blank line, then the slice's block.
    outputs = {
        "ActiveState=active\nFreezerState=frozen-by-parent\n\nActiveState=active\n"
        "FreezerState=frozen\n": "sleeping",
        "ActiveState=active\nFreezerState=running\n\nActiveState=active\n"
        "FreezerState=running\n": "running",
        "ActiveState=inactive\nFreezerState=running\n\nActiveState=inactive\n"
        "FreezerState=running\n": "stopped",
        "ActiveState=failed\nFreezerState=running\n\n": "failed",
    }
    for output, expected in outputs.items():

        async def fake(*args, check=True, _output=output):
            return _output

        monkeypatch.setattr(backend, "_systemctl", fake)
        assert await backend.probe(display) == expected


async def test_sleep_and_stop_act_on_the_whole_slice(tmp_path: Path, monkeypatch) -> None:
    backend = SystemdDisplayBackend(DisplaySettings(), tmp_path)
    display = Display("atlas", 10, 15910, 5910)
    calls: list[tuple[str, ...]] = []

    async def fake(*args, check=True):
        calls.append(args)
        return ""

    monkeypatch.setattr(backend, "_systemctl", fake)
    await backend.start(display)
    await backend.freeze(display)
    await backend.thaw(display)
    await backend.stop(display)
    assert calls == [
        ("start", "pal-display@atlas.service"),
        ("freeze", "pal-display-atlas.slice"),
        ("thaw", "pal-display-atlas.slice"),
        ("stop", "pal-display-atlas.slice"),
    ]
