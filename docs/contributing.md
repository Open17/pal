# Contributing

## Branches

| Branch | Purpose |
| --- | --- |
| `main` | Releases only. Updated by the project owner when a version is done. Never commit or merge into it directly. |
| `development` | Integration branch. Every feature branch merges here. |
| `feature/<name>` | New functionality. |
| `fix/<name>` | Bug fixes. |
| `chore/<name>` | Tooling, configuration, repository housekeeping. |
| `docs/<name>` | Documentation-only changes. |

Workflow:

1. Branch from the latest `development`.
2. Make small, focused commits — one logical change per commit.
3. Merge back into `development` with `git merge --no-ff` so each feature stays
   visible as a unit in the history.

## Commit messages

- Imperative subject line, at most ~72 characters ("Add display idle monitor").
- Optional body explaining *why*, wrapped at ~72 characters.
- Keep messages and code comments vendor-neutral. Name a third-party product
  only when the code is specifically about that integration (for example, the
  custom Gmail tool).

## Code layout and style

- **Runtime (Python ≥ 3.11):** `runtime/src/pal/`, tests in `runtime/tests/`.
  Type-annotated, `asyncio` throughout, formatted and linted with `ruff`.
- **Host (Swift ≥ 5.9, macOS 14+):** Swift package in `host/`.
- **Guest scripts (bash):** `set -euo pipefail`, one concern per script.

## Running tests

```sh
# Runtime
cd runtime
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest

# Host
cd host
swift build && swift test
```
