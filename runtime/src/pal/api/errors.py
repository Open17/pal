"""Uniform JSON errors for the API."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from pal.bots import UnknownBotError, UnknownMessageError
from pal.config import ConfigError
from pal.displays import DisplayBackendError, UnknownDisplayError
from pal.log import get_logger
from pal.memory import MemoryAccessError, MemoryFormatError

log = get_logger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": {"code": code, "message": message}}, status=status)


@web.middleware
async def error_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    try:
        return await handler(request)
    except ApiError as exc:
        return error_response(exc.status, exc.code, exc.message)
    except UnknownBotError as exc:
        return error_response(404, "unknown_bot", f"no bot called {exc.args[0]!r}")
    except UnknownMessageError as exc:
        return error_response(404, "unknown_message", f"no message {exc.args[0]!r}")
    except UnknownDisplayError as exc:
        return error_response(404, "unknown_display", f"no display for {exc.args[0]!r}")
    except MemoryAccessError as exc:
        return error_response(403, "forbidden", str(exc))
    except (ConfigError, MemoryFormatError, ValueError) as exc:
        return error_response(400, "invalid_request", str(exc))
    except DisplayBackendError as exc:
        return error_response(502, "display_error", str(exc))
    except web.HTTPException as exc:
        if exc.status >= 400 and exc.content_type != "application/json":
            return error_response(exc.status, exc.reason.lower().replace(" ", "_"), exc.reason)
        raise
    except Exception:
        log.exception("unhandled error for %s %s", request.method, request.path)
        return error_response(500, "internal_error", "internal error")


async def json_body(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise ApiError(400, "invalid_json", f"request body is not valid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_json", "request body must be a JSON object")
    return body


def optional_text(body: dict[str, Any], key: str) -> str:
    """A free-text field that may be left out or blank; blank means none."""

    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApiError(400, "invalid_request", f"{key!r} must be a string")
    return value.strip()


def optional_str(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, "invalid_request", f"{key!r} must be a non-empty string")
    return value.strip()
