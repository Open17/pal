"""Load ``pal.toml`` and ``bots/*.toml`` into a :class:`PalConfig`."""

from __future__ import annotations

import os
import tomllib
from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

from .models import (
    DISPLAY_BACKENDS,
    PERMISSION_MODES,
    AgentSettings,
    ApiSettings,
    BotDefinition,
    ConfigError,
    DisplaySettings,
    MessagingSettings,
    ModelSettings,
    PalConfig,
    PathSettings,
    validate_bot_id,
    validate_effort,
)

CONFIG_DIR_ENV = "PAL_CONFIG_DIR"
CONFIG_FILE_NAME = "pal.toml"
BOTS_DIR_NAME = "bots"

DEFAULT_CONFIG_DIR = "~/.config/pal"
DEFAULT_WORKSPACES_DIR = "~/workspaces"
DEFAULT_DATA_DIR = "~/.local/share/pal"

_T = TypeVar("_T")


def default_config_dir() -> Path:
    return expand_path(os.environ.get(CONFIG_DIR_ENV, DEFAULT_CONFIG_DIR))


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def load_config(config_dir: str | Path | None = None) -> PalConfig:
    """Load configuration from ``config_dir`` (defaults to ``$PAL_CONFIG_DIR``)."""

    root = expand_path(config_dir) if config_dir is not None else default_config_dir()
    config_file = root / CONFIG_FILE_NAME
    raw = _read_toml(config_file) if config_file.exists() else {}

    paths = _load_paths(raw.get("paths", {}), root)
    model = _load_model(raw.get("model", {}))
    agent = _load_section(AgentSettings, raw.get("agent", {}), "agent")
    if agent.permission_mode not in PERMISSION_MODES:
        raise ConfigError(f"[agent] permission_mode must be one of {', '.join(PERMISSION_MODES)}")
    displays = _load_section(DisplaySettings, raw.get("displays", {}), "displays")
    if displays.backend not in DISPLAY_BACKENDS:
        raise ConfigError(f"[displays] backend must be one of {', '.join(DISPLAY_BACKENDS)}")
    if displays.idle_timeout_seconds <= 0:
        raise ConfigError("[displays] idle_timeout_seconds must be positive")
    api = _load_section(ApiSettings, raw.get("api", {}), "api")
    messaging = _load_section(MessagingSettings, raw.get("messaging", {}), "messaging")
    bots = load_bots(root / BOTS_DIR_NAME)

    return PalConfig(
        paths=paths,
        model=model,
        agent=agent,
        displays=displays,
        api=api,
        messaging=messaging,
        bots=bots,
    )


def load_bots(bots_dir: Path) -> tuple[BotDefinition, ...]:
    """Load every ``*.toml`` bot definition in ``bots_dir``, sorted by id."""

    if not bots_dir.is_dir():
        return ()
    bots: dict[str, BotDefinition] = {}
    for path in sorted(bots_dir.glob("*.toml")):
        bot = _load_bot(path)
        if bot.id in bots:
            raise ConfigError(f"{path}: duplicate bot id {bot.id!r}")
        bots[bot.id] = bot
    return tuple(bots[key] for key in sorted(bots))


def _load_bot(path: Path) -> BotDefinition:
    raw = _read_toml(path)
    where = str(path)
    bot_id = raw.get("id", path.stem)
    if bot_id != path.stem:
        raise ConfigError(f"{where}: id {bot_id!r} must match the file name {path.stem!r}")
    validate_bot_id(bot_id, where=where)
    effort = raw.get("effort")
    if effort is not None:
        validate_effort(effort, where=where)
    unknown = set(raw) - {f.name for f in fields(BotDefinition)}
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
    return BotDefinition(
        id=bot_id,
        name=str(raw.get("name", bot_id.title())),
        role=str(raw.get("role", "")),
        persona=str(raw.get("persona", "")).strip(),
        model=raw.get("model"),
        effort=effort,
        color=raw.get("color"),
    )


def _load_paths(raw: dict[str, Any], config_root: Path) -> PathSettings:
    return PathSettings(
        workspaces=expand_path(raw.get("workspaces", DEFAULT_WORKSPACES_DIR)),
        data=expand_path(raw.get("data", DEFAULT_DATA_DIR)),
        config=config_root,
    )


def _load_model(raw: dict[str, Any]) -> ModelSettings:
    defaults = ModelSettings()
    effort = raw.get("effort", defaults.effort)
    validate_effort(effort, where="[model]")
    return ModelSettings(model=str(raw.get("default", defaults.model)), effort=effort)


def _load_section(cls: type[_T], raw: dict[str, Any], name: str) -> _T:
    allowed = {f.name: f for f in fields(cls)}  # type: ignore[arg-type]
    unknown = set(raw) - set(allowed)
    if unknown:
        raise ConfigError(f"[{name}] unknown keys {sorted(unknown)}")
    return cls(**raw)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
