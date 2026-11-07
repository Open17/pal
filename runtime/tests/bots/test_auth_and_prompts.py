from __future__ import annotations

from pathlib import Path

from pal.bots import auth_status, frame_message, scrub_api_credentials, session_environment
from pal.messaging import Message


def test_api_credentials_are_scrubbed() -> None:
    environ = {"ANTHROPIC_API_KEY": "k", "PATH": "/bin"}
    assert scrub_api_credentials(environ) == ["ANTHROPIC_API_KEY"]
    assert environ == {"PATH": "/bin"}


def test_session_environment_uses_token_file(tmp_path: Path) -> None:
    assert session_environment(tmp_path) == {}
    (tmp_path / "oauth-token").write_text("  tok \n")
    assert session_environment(tmp_path) == {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}


def test_auth_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    home, secrets = tmp_path / "home", tmp_path / "secrets"
    assert auth_status(secrets, home=home).method == "none"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text("{}")
    assert auth_status(secrets, home=home).method == "stored-login"
    secrets.mkdir()
    (secrets / "oauth-token").write_text("tok")
    assert auth_status(secrets, home=home).method == "oauth-token"


def test_message_framing() -> None:
    chat = Message(sender="user", recipient="atlas", content="hi")
    assert frame_message(chat, "the user") == "hi"
    request = Message(sender="scout", recipient="atlas", content="q", kind="request")
    assert frame_message(request, "Scout").startswith("[Message from Scout (`scout`). They are")
    notice = Message(sender="scout", recipient="atlas", content="n", kind="notice")
    assert "No reply expected" in frame_message(notice, "Scout")
