"""The ``pal`` command."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pal import __version__
from pal.config import ConfigError, PalConfig, load_config
from pal.log import configure_logging

DEFAULT_URL = "http://127.0.0.1:8765"


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    return args.handler(config, args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pal", description="Pal runtime")
    parser.add_argument("--version", action="version", version=f"pal {__version__}")
    parser.add_argument("--config", type=Path, help="config directory (default: $PAL_CONFIG_DIR)")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ... (default: $PAL_LOG_LEVEL)")
    commands = parser.add_subparsers(required=True, metavar="command")

    serve = commands.add_parser("serve", help="run the runtime")
    serve.set_defaults(handler=_serve)

    config_cmd = commands.add_parser("config", help="configuration tools")
    config_sub = config_cmd.add_subparsers(required=True, metavar="action")
    config_sub.add_parser("check", help="validate and summarize the configuration").set_defaults(
        handler=_config_check
    )

    auth = commands.add_parser("auth", help="sign-in tools")
    auth_sub = auth.add_subparsers(required=True, metavar="action")
    auth_sub.add_parser("status", help="show how bots are signed in").set_defaults(
        handler=_auth_status
    )

    status = commands.add_parser("status", help="show the running runtime's status")
    status.add_argument("--url", default=DEFAULT_URL)
    status.set_defaults(handler=_status)

    chat = commands.add_parser("chat", help="chat with a bot from the terminal")
    chat.add_argument("bot", help="bot id, e.g. pal")
    chat.add_argument("--url", default=DEFAULT_URL)
    chat.set_defaults(handler=_chat)
    return parser


# -- commands ----------------------------------------------------------------


def _serve(config: PalConfig, args: argparse.Namespace) -> int:
    from pal.runtime import PalRuntime

    if not config.bots:
        print(f"no bots defined in {config.paths.bots}", file=sys.stderr)
        return 2
    asyncio.run(PalRuntime(config).run_forever())
    return 0


def _config_check(config: PalConfig, args: argparse.Namespace) -> int:
    print(f"config:      {config.paths.config}")
    print(f"workspaces:  {config.paths.workspaces}")
    print(f"data:        {config.paths.data}")
    print(f"default:     {config.model.model} ({config.model.effort} effort)")
    displays = config.displays
    print(f"displays:    {displays.backend}, sleep after {displays.idle_timeout_seconds}s idle")
    print(f"api:         {config.api.host}:{config.api.port}")
    print(f"bots ({len(config.bots)}):")
    for bot in config.bots:
        settings = bot.model_settings(config.model)
        role = bot.role or "no role"
        print(f"  {bot.id:<10} {bot.name} — {role} [{settings.model}, {settings.effort}]")
    return 0


def _auth_status(config: PalConfig, args: argparse.Namespace) -> int:
    from pal.bots import auth_status

    status = auth_status(config.paths.secrets)
    print(f"{status.method}: {status.detail}")
    return 0 if status.ok else 1


def _status(config: PalConfig, args: argparse.Namespace) -> int:
    return asyncio.run(_print_status(config, args.url))


def _chat(config: PalConfig, args: argparse.Namespace) -> int:
    try:
        return asyncio.run(_chat_loop(config, args.url, args.bot))
    except (KeyboardInterrupt, EOFError):
        print()
        return 0


# -- API client helpers --------------------------------------------------------


def _headers(config: PalConfig) -> dict[str, str]:
    from pal.api import API_TOKEN_FILE

    token_file = config.paths.secrets / API_TOKEN_FILE
    if not token_file.is_file():
        raise SystemExit(f"no API token at {token_file}; is the runtime installed?")
    return {"Authorization": f"Bearer {token_file.read_text().strip()}"}


async def _print_status(config: PalConfig, url: str) -> int:
    import aiohttp

    async with (
        aiohttp.ClientSession(url, headers=_headers(config)) as session,
        session.get("/v1/status") as response,
    ):
        body: dict[str, Any] = await response.json()
    print(f"auth: {body['auth']['method']} ({body['auth']['detail']})")
    for bot in body["bots"]:
        print(f"bot {bot['id']:<10} {bot['status']:<8} {bot['model']} [{bot['effort']}]")
    for display in body["displays"]:
        print(f"display {display['display']:<5} {display['owner']:<10} {display['state']}")
    return 0


async def _chat_loop(config: PalConfig, url: str, bot: str) -> int:
    import aiohttp

    async with (
        aiohttp.ClientSession(url, headers=_headers(config)) as session,
        session.ws_connect("/v1/events") as events,
    ):
        print(f"Chatting with {bot}. Ctrl-D to quit.")
        while True:
            text = await asyncio.to_thread(input, "you> ")
            if not text.strip():
                continue
            async with session.post(f"/v1/bots/{bot}/messages", json={"content": text}) as reply:
                if reply.status != 202:
                    print(json.dumps(await reply.json()), file=sys.stderr)
                    continue
            await _stream_turn(events, bot)


async def _stream_turn(events: Any, bot: str) -> None:
    streamed = False
    print(f"{bot}> ", end="", flush=True)
    async for frame in events:
        event = json.loads(frame.data)
        data = event.get("data", {})
        if data.get("bot") != bot and data.get("message", {}).get("sender") != bot:
            continue
        if event["type"] == "bot.text.delta":
            streamed = True
            print(data["text"], end="", flush=True)
        elif event["type"] == "bot.tool.started":
            print(f"\n  [{data['tool']}]", end="", flush=True)
        elif event["type"] == "message.created" and not streamed:
            print(data["message"]["content"], end="")
        elif event["type"] == "bot.turn.completed":
            print()
            return


if __name__ == "__main__":
    raise SystemExit(main())
