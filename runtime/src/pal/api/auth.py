"""Bearer-token authentication for the API."""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from aiohttp import web

from .context import CONTEXT
from .errors import Handler, error_response

API_TOKEN_FILE = "api-token"
PUBLIC_PATHS = frozenset({"/v1/health"})


def load_or_create_token(secrets_dir: Path) -> str:
    """Read the API token, creating one if the VM was provisioned without it."""

    path = secrets_dir / API_TOKEN_FILE
    if path.is_file() and (token := path.read_text().strip()):
        return token
    secrets_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n")
    path.chmod(0o600)
    return token


def presented_token(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    # WebSocket clients that cannot set headers may pass the token as a query parameter.
    return request.query.get("token")


@web.middleware
async def auth_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    if request.path in PUBLIC_PATHS:
        return await handler(request)
    expected = request.app[CONTEXT].api_token
    token = presented_token(request)
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        return error_response(401, "unauthorized", "missing or invalid API token")
    return await handler(request)
