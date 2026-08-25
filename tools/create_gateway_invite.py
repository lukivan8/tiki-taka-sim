#!/usr/bin/env python3
"""Create or rotate one personal Nova gateway invite token."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from pathlib import Path


DEFAULT_PATH = Path.home() / ".config/tiki-taka-sim/gateway-tokens.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="short friend identifier used in quota accounting")
    parser.add_argument("--file", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--daily-limit", type=int, default=3000)
    parser.add_argument("--rpm", type=int, default=600)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if not args.name or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in args.name):
        parser.error("name may contain only letters, digits, '-' and '_'")
    if min(args.daily_limit, args.rpm, args.concurrency) <= 0:
        parser.error("limits must be positive")

    path = args.file.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"schemaVersion": "afc-gateway-tokens/v1", "tokens": []}
    if data.get("schemaVersion") != "afc-gateway-tokens/v1":
        raise SystemExit("unsupported token file schemaVersion")
    existing = next((entry for entry in data["tokens"] if entry["name"] == args.name), None)
    if existing and not args.replace:
        raise SystemExit(f"invite {args.name!r} already exists; use --replace to rotate it")
    if existing:
        data["tokens"].remove(existing)
    token = secrets.token_urlsafe(36)
    data["tokens"].append({
        "name": args.name,
        "token": token,
        "dailyCallLimit": args.daily_limit,
        "requestsPerMinute": args.rpm,
        "maxConcurrent": args.concurrency,
    })
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    print(f"AFC_GATEWAY_TOKEN={token}")
    print(f"Stored invite {args.name!r} in {path}")


if __name__ == "__main__":
    main()
