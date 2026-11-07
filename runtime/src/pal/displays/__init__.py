"""Per-bot X displays: on-demand start, idle sleep, and VNC access."""

from .backend import (
    DisplayBackend,
    DisplayBackendError,
    InMemoryDisplayBackend,
    SystemdDisplayBackend,
    create_backend,
)
from .manager import DisplayManager, UnknownDisplayError
from .models import Display, DisplayState
from .proxy import VncProxy

__all__ = [
    "Display",
    "DisplayBackend",
    "DisplayBackendError",
    "DisplayManager",
    "DisplayState",
    "InMemoryDisplayBackend",
    "SystemdDisplayBackend",
    "UnknownDisplayError",
    "VncProxy",
    "create_backend",
]
