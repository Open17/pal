"""Computer-control tools: screenshots, pointer, keyboard, windows, OCR."""

from .desktop import Desktop, DesktopError, Window, normalize_keys, parse_windows
from .provider import ComputerTools

__all__ = ["ComputerTools", "Desktop", "DesktopError", "Window", "normalize_keys", "parse_windows"]
