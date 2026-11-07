from __future__ import annotations

from pathlib import Path

from pal.config import DisplaySettings
from pal.displays import Display, SystemdDisplayBackend


def test_systemd_environment_file(tmp_path: Path) -> None:
    backend = SystemdDisplayBackend(DisplaySettings(geometry="1280x800"), tmp_path)
    display = Display("atlas", 10, 15910, 5910)
    assert backend.unit(display) == "pal-display@atlas.service"
    text = backend.write_environment(display).read_text()
    assert "PAL_DISPLAY_NUMBER=10\n" in text
    assert "PAL_VNC_PORT=15910\n" in text
    assert "PAL_DISPLAY_GEOMETRY=1280x800\n" in text


async def test_probe_parses_unit_properties(tmp_path: Path, monkeypatch) -> None:
    backend = SystemdDisplayBackend(DisplaySettings(), tmp_path)
    display = Display("atlas", 10, 15910, 5910)
    outputs = {
        "ActiveState=active\nFreezerState=frozen\n": "sleeping",
        "ActiveState=active\nFreezerState=running\n": "running",
        "ActiveState=inactive\nFreezerState=running\n": "stopped",
        "ActiveState=failed\n": "failed",
    }
    for output, expected in outputs.items():

        async def fake(*args, check=True, _output=output):
            return _output

        monkeypatch.setattr(backend, "_systemctl", fake)
        assert await backend.probe(display) == expected
