# Pal runtime

The process that runs inside the Pal VM. It hosts the bot team, shared memory,
messaging, on-demand displays, and the HTTP/WebSocket API used by the macOS app.

```
src/pal/
  config/      configuration models and loader (pal.toml + bots/*.toml)
  memory/      file-backed shared memory and per-bot knowledge
  messaging/   messages, event bus, conversation logs
  displays/    per-bot X displays: lifecycle, idle sleep, VNC proxy
  tools/       tool registry and built-in tool providers
  bots/        agent sessions, prompts, the bot team
  api/         HTTP + WebSocket API
  runtime.py   composition root
  cli.py       `pal` command
```

## Development

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check src tests
```

Run against the repository's default configuration:

```sh
PAL_CONFIG_DIR=../config pal config check
```
