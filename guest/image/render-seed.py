#!/usr/bin/env python3
"""Render the cloud-init seed files for the Pal guest.

Usage: render-seed.py OUTPUT_DIR --payload FILE --secrets DIR [--env KEY=VALUE ...]
"""

from __future__ import annotations

import argparse
import base64
import json
import string
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_secret(secrets: Path, name: str, *, required: bool = True) -> str:
    path = secrets / name
    if not path.exists():
        if required:
            raise SystemExit(f"missing secret {path}")
        return ""
    return path.read_text().strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--secrets", type=Path, required=True)
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args()

    env_lines = []
    for item in args.env:
        key, _, value = item.partition("=")
        if not key.isidentifier():
            raise SystemExit(f"invalid --env {item!r}")
        env_lines.append(f"      {key}={json.dumps(value)}")

    values = {
        "ssh_public_key": read_secret(args.secrets, "id_ed25519.pub"),
        "payload_b64": base64.b64encode(args.payload.read_bytes()).decode(),
        "provision_env": "\n".join(env_lines) or "      # no settings",
        # JSON strings are valid YAML scalars and keep tokens safely quoted.
        "api_token": json.dumps(read_secret(args.secrets, "api-token")),
        "vnc_password": json.dumps(read_secret(args.secrets, "vnc-password")),
        "oauth_token": json.dumps(read_secret(args.secrets, "oauth-token", required=False)),
        "instance_id": f"pal-{uuid.uuid4()}",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("user-data", "meta-data", "network-config"):
        template = string.Template((HERE / "cloud-init" / f"{name}.yaml.tmpl").read_text())
        (args.output / name).write_text(template.substitute(values))


if __name__ == "__main__":
    main()
