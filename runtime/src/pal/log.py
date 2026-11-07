"""Logging setup shared by the runtime and the CLI."""

from __future__ import annotations

import logging
import os
import sys

LOG_LEVEL_ENV = "PAL_LOG_LEVEL"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str | None = None) -> None:
    """Send runtime logs to stderr, which the service manager captures."""

    resolved = (level or os.environ.get(LOG_LEVEL_ENV) or "INFO").upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(resolved)
    # Third-party libraries are noisy at INFO.
    for noisy in ("aiohttp.access", "asyncio"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("pal") else f"pal.{name}")
