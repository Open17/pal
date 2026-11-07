"""Display records: one X display per bot, plus the operator's display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

DisplayState = Literal["stopped", "starting", "running", "sleeping", "failed"]


@dataclass
class Display:
    owner: str
    number: int
    vnc_internal_port: int
    vnc_public_port: int
    state: DisplayState = "stopped"
    viewers: int = 0
    last_activity: float = 0.0  # monotonic seconds
    error: str | None = None

    @property
    def name(self) -> str:
        """The X display name, e.g. ``:10``."""

        return f":{self.number}"

    @property
    def is_live(self) -> bool:
        """Running or sleeping: the session and its windows still exist."""

        return self.state in ("running", "sleeping")

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "display": self.name,
            "number": self.number,
            "state": self.state,
            "viewers": self.viewers,
            "vnc_port": self.vnc_public_port,
            "error": self.error,
        }
