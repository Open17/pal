"""Runtime state for bots that outlives the process.

Holds each bot's agent session id (so conversations resume after a restart)
and model/effort choices made at runtime, which take precedence over the
configuration files.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pal.config import Effort, ModelSettings, validate_effort
from pal.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ModelOverride:
    model: str | None = None
    effort: Effort | None = None

    def apply(self, settings: ModelSettings) -> ModelSettings:
        return settings.with_overrides(self.model, self.effort)

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "effort": self.effort}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ModelOverride:
        data = data or {}
        effort = data.get("effort")
        if effort is not None:
            validate_effort(effort, where="bot state")
        return cls(model=data.get("model") or None, effort=effort)


class BotStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()

    # -- sessions --------------------------------------------------------

    def session_id(self, bot_id: str) -> str | None:
        return self._bot(bot_id).get("session_id")

    def set_session_id(self, bot_id: str, session_id: str | None) -> None:
        if self.session_id(bot_id) != session_id:
            self._update_bot(bot_id, session_id=session_id)

    # -- model overrides -------------------------------------------------

    def defaults_override(self) -> ModelOverride:
        return ModelOverride.from_dict(self._data.get("defaults"))

    def set_defaults_override(self, override: ModelOverride) -> None:
        with self._lock:
            self._data["defaults"] = override.to_dict()
            self._save()

    def bot_override(self, bot_id: str) -> ModelOverride:
        return ModelOverride.from_dict(self._bot(bot_id).get("override"))

    def set_bot_override(self, bot_id: str, override: ModelOverride) -> None:
        self._update_bot(bot_id, override=override.to_dict())

    # -- persistence -----------------------------------------------------

    def forget(self, bot_id: str) -> None:
        """Drop everything kept for a removed bot: its session and model choice."""

        with self._lock:
            if self._data.get("bots", {}).pop(bot_id, None) is not None:
                self._save()

    def _bot(self, bot_id: str) -> dict[str, Any]:
        return self._data.setdefault("bots", {}).get(bot_id, {})

    def _update_bot(self, bot_id: str, **values: Any) -> None:
        with self._lock:
            bots = self._data.setdefault("bots", {})
            bots[bot_id] = {**bots.get(bot_id, {}), **values}
            self._save()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable bot state %s: %s", self.path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.path)
