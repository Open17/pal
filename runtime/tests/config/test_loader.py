from __future__ import annotations

from pathlib import Path

import pytest

from pal.config import DEFAULT_EFFORT, DEFAULT_MODEL, ConfigError, ModelSettings, load_config
from tests.conftest import REPO_CONFIG_DIR


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_empty_directory_uses_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.model == ModelSettings(DEFAULT_MODEL, DEFAULT_EFFORT)
    assert config.model.model == "claude-sonnet-5-5"
    assert config.model.effort == "high"
    assert config.displays.idle_timeout_seconds == 480
    assert config.bots == ()
    assert config.paths.config == tmp_path.resolve()


def test_repository_config_is_valid() -> None:
    config = load_config(REPO_CONFIG_DIR)
    assert config.bot_ids == ("atlas", "forge", "scout")
    assert all(bot.persona for bot in config.bots)


def test_bot_overrides_model_and_effort(tmp_path: Path) -> None:
    write(
        tmp_path / "bots" / "nova.toml",
        'name = "Nova"\nmodel = "claude-opus-5-5"\neffort = "max"\n',
    )
    config = load_config(tmp_path)
    settings = config.bot("nova").model_settings(config.model)
    assert settings == ModelSettings("claude-opus-5-5", "max")


def test_bot_inherits_defaults(tmp_path: Path) -> None:
    write(tmp_path / "pal.toml", '[model]\ndefault = "claude-haiku-5-5"\neffort = "low"\n')
    write(tmp_path / "bots" / "nova.toml", 'name = "Nova"\n')
    config = load_config(tmp_path)
    assert config.bot("nova").model_settings(config.model) == ModelSettings(
        "claude-haiku-5-5", "low"
    )


@pytest.mark.parametrize(
    ("file_name", "body", "message"),
    [
        ("nova.toml", 'effort = "extreme"\n', "effort must be one of"),
        ("nova.toml", 'id = "other"\n', "must match the file name"),
        ("Nova.toml", "", "must start with a letter"),
        ("operator.toml", "", "reserved"),
        ("nova.toml", 'nickname = "n"\n', "unknown keys"),
        ("nova.toml", "name = \n", "invalid TOML"),
    ],
)
def test_invalid_bots_are_rejected(tmp_path: Path, file_name: str, body: str, message: str) -> None:
    write(tmp_path / "bots" / file_name, body)
    with pytest.raises(ConfigError, match=message):
        load_config(tmp_path)


def test_unknown_section_keys_are_rejected(tmp_path: Path) -> None:
    write(tmp_path / "pal.toml", "[displays]\nidle = 5\n")
    with pytest.raises(ConfigError, match=r"\[displays\] unknown keys"):
        load_config(tmp_path)


def test_paths_expand_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path / "cfg" / "pal.toml", '[paths]\nworkspaces = "~/ws"\n')
    config = load_config(tmp_path / "cfg")
    assert config.paths.workspaces == (tmp_path / "ws").resolve()
    assert config.paths.bot_workspace("atlas") == (tmp_path / "ws" / "atlas").resolve()
