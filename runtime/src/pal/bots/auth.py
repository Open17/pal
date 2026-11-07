"""Authentication for agent sessions.

Pal signs in with a Claude account rather than a developer API key. The
preferred credential is a long-lived OAuth token created with
``claude setup-token`` and provisioned into the VM as a secret file. Without
it, sessions fall back to the login stored by running ``claude login`` inside
the VM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pal.log import get_logger

log = get_logger(__name__)

OAUTH_TOKEN_FILE = "oauth-token"
OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
# Variables that would switch sessions from the account login to API billing.
API_CREDENTIAL_ENVS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
STORED_LOGIN = Path("~/.claude/.credentials.json")


@dataclass(frozen=True)
class AuthStatus:
    method: Literal["oauth-token", "stored-login", "none"]
    detail: str

    @property
    def ok(self) -> bool:
        return self.method != "none"


def scrub_api_credentials(environ: dict[str, str] | os._Environ[str] = os.environ) -> list[str]:
    """Remove API credentials from the process environment.

    Agent sessions inherit this environment, so removing them here guarantees
    every bot uses the account login.
    """

    removed = [name for name in API_CREDENTIAL_ENVS if environ.pop(name, None) is not None]
    for name in removed:
        log.warning("ignoring %s: Pal uses the signed-in account, not an API key", name)
    return removed


def read_oauth_token(secrets_dir: Path) -> str | None:
    path = secrets_dir / OAUTH_TOKEN_FILE
    try:
        token = path.read_text().strip()
    except FileNotFoundError:
        return None
    return token or None


def session_environment(secrets_dir: Path) -> dict[str, str]:
    """Environment variables that authenticate an agent session."""

    token = read_oauth_token(secrets_dir)
    return {OAUTH_TOKEN_ENV: token} if token else {}


def auth_status(secrets_dir: Path, *, home: Path | None = None) -> AuthStatus:
    if read_oauth_token(secrets_dir) or os.environ.get(OAUTH_TOKEN_ENV):
        return AuthStatus("oauth-token", f"token from {secrets_dir / OAUTH_TOKEN_FILE}")
    stored = (home / ".claude/.credentials.json") if home else STORED_LOGIN.expanduser()
    if stored.exists():
        return AuthStatus("stored-login", f"login stored in {stored}")
    return AuthStatus(
        "none",
        f"no credentials: put a token from `claude setup-token` in "
        f"{secrets_dir / OAUTH_TOKEN_FILE}, or run `claude login` in the VM",
    )
