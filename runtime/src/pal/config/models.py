"""Typed configuration for the Pal runtime.

Configuration is immutable once loaded. Values that change while the runtime is
running (such as a bot's model or effort) are kept in runtime state and layered
on top of these defaults.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, get_args

Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS: tuple[str, ...] = get_args(Effort)

PermissionMode = Literal["default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"]
PERMISSION_MODES: tuple[str, ...] = get_args(PermissionMode)

ThinkingDisplay = Literal["summarized", "omitted"]

DisplayBackendName = Literal["systemd", "simulated"]
DISPLAY_BACKENDS: tuple[str, ...] = get_args(DisplayBackendName)

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT: Effort = "high"

BOT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

# Identifiers that have a fixed meaning elsewhere and cannot be used for bots.
OPERATOR_ID = "operator"
USER_ID = "user"
RESERVED_IDS = frozenset({OPERATOR_ID, USER_ID, "shared", "system", "all"})


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


def validate_effort(value: str, *, where: str) -> Effort:
    if value not in EFFORT_LEVELS:
        allowed = ", ".join(EFFORT_LEVELS)
        raise ConfigError(f"{where}: effort must be one of {allowed} (got {value!r})")
    return value  # type: ignore[return-value]


COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_color(value: str, *, where: str) -> str:
    """A bot color is ``#RRGGBB``; returned in upper case."""

    if not COLOR_PATTERN.match(value):
        raise ConfigError(f"{where}: color must look like #5B8DEF (got {value!r})")
    return value.upper()


def validate_bot_id(value: str, *, where: str) -> str:
    if not BOT_ID_PATTERN.match(value):
        raise ConfigError(
            f"{where}: bot id {value!r} must start with a letter and contain only "
            "lowercase letters, digits, and dashes (max 32 characters)"
        )
    if value in RESERVED_IDS:
        raise ConfigError(f"{where}: bot id {value!r} is reserved")
    return value


@dataclass(frozen=True)
class ModelSettings:
    """Which model a bot runs and how hard it thinks."""

    model: str = DEFAULT_MODEL
    effort: Effort = DEFAULT_EFFORT

    def with_overrides(
        self, model: str | None = None, effort: Effort | None = None
    ) -> ModelSettings:
        return replace(self, model=model or self.model, effort=effort or self.effort)


@dataclass(frozen=True)
class PathSettings:
    """Where the runtime keeps workspaces, data, and configuration."""

    #: The team's main folder, shared by every bot and the user.
    workspaces: Path
    data: Path
    config: Path

    @property
    def memory(self) -> Path:
        return self.data / "memory"

    @property
    def conversations(self) -> Path:
        return self.data / "conversations"

    @property
    def state(self) -> Path:
        return self.data / "state"

    @property
    def secrets(self) -> Path:
        return self.config / "secrets"

    @property
    def bots(self) -> Path:
        return self.config / "bots"


@dataclass(frozen=True)
class AgentSettings:
    """How each bot's agent session is configured."""

    permission_mode: PermissionMode = "bypassPermissions"
    max_turns: int | None = None
    thinking_display: ThinkingDisplay | None = "summarized"
    cli_path: str | None = None


@dataclass(frozen=True)
class DisplaySettings:
    """Per-bot X displays served over VNC."""

    backend: DisplayBackendName = "systemd"
    idle_timeout_seconds: int = 8 * 60
    check_interval_seconds: int = 15
    geometry: str = "1280x800"
    depth: int = 24
    operator_display: int = 1
    first_bot_display: int = 10
    # Xvnc for display :N listens on localhost:(internal_base + N); the runtime
    # proxies it on bind_host:(public_base + N) and wakes the display on connect.
    vnc_internal_base_port: int = 15900
    vnc_public_base_port: int = 5900
    vnc_bind_host: str = "127.0.0.1"


@dataclass(frozen=True)
class ApiSettings:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass(frozen=True)
class MessagingSettings:
    """Limits for bot-to-bot conversations."""

    reply_timeout_seconds: int = 600
    max_chain_depth: int = 4


@dataclass(frozen=True)
class BotDefinition:
    """A bot as declared in ``bots/<id>.toml``."""

    id: str
    name: str
    role: str = ""
    persona: str = ""
    model: str | None = None
    effort: Effort | None = None
    color: str | None = None

    def model_settings(self, defaults: ModelSettings) -> ModelSettings:
        return defaults.with_overrides(self.model, self.effort)


@dataclass(frozen=True)
class PalConfig:
    paths: PathSettings
    model: ModelSettings = field(default_factory=ModelSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    displays: DisplaySettings = field(default_factory=DisplaySettings)
    api: ApiSettings = field(default_factory=ApiSettings)
    messaging: MessagingSettings = field(default_factory=MessagingSettings)
    bots: tuple[BotDefinition, ...] = ()

    def bot(self, bot_id: str) -> BotDefinition:
        for bot in self.bots:
            if bot.id == bot_id:
                return bot
        raise KeyError(bot_id)

    @property
    def bot_ids(self) -> tuple[str, ...]:
        return tuple(bot.id for bot in self.bots)
