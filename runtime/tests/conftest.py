from __future__ import annotations

from pathlib import Path

import pytest

from pal.config import PalConfig, PathSettings

REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def paths(tmp_path: Path) -> PathSettings:
    return PathSettings(
        workspaces=tmp_path / "workspaces",
        data=tmp_path / "data",
        config=tmp_path / "config",
    )


@pytest.fixture
def config(paths: PathSettings) -> PalConfig:
    return PalConfig(paths=paths)
