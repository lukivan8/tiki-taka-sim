#!/usr/bin/env python3
"""Expose the football-workshop sample agents' real fallback policies over HTTP."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def load_policies(sample_root: Path):
    lib = sample_root / "lib"
    required = [lib / "fallback.py", lib / "state.py", lib / "test_helpers.py"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("not an agentic-football-sample-agents checkout; missing: " + ", ".join(missing))
    sys.path.insert(0, str(lib))
    fallback = importlib.import_module("fallback")
    return {
        0: fallback.build_fallback(fallback.GK_CONFIG),
        1: fallback.build_fallback(fallback.DEF_CONFIG),
        2: fallback.build_fallback(fallback.MID_CONFIG),
        3: fallback.build_fallback(fallback.FWD1_CONFIG),
        4: fallback.build_fallback(fallback.FWD2_CONFIG),
    }


class Handler(BaseHTTPRequestHandler):
    policies = {}

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_json({"status": "ok", "source": "football-workshop/lib/fallback.py"})

    def do_POST(self):
        if self.path != "/invocations":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            envelope = json.loads(self.rfile.read(length))
            prompt = envelope.get("prompt", "{}")
            payload = json.loads(prompt) if isinstance(prompt, str) else prompt
            state = payload["gameState"]
            team_id = int(payload["teamId"])
            my_players = payload["myPlayers"]
            if len(my_players) != 1:
                raise ValueError("bridge expects exactly one controlled player")
            player_id = int(my_players[0])
            commands = self.policies[player_id](state, team_id, player_id)
            # AgentCore examples yield json.dumps(commands). Preserve that string
            # envelope so the Rust adapter exercises the deployed response shape.
            self.send_json(json.dumps(commands, separators=(",", ":")))
        except Exception as error:
            self.send_json({"error": type(error).__name__, "message": str(error)}, status=500)

    def send_json(self, value, status=200):
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-root", required=True, type=Path,
                        help="path to agentic-football-sample-agents")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8100, type=int)
    args = parser.parse_args()
    Handler.policies = load_policies(args.sample_root.resolve())
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"sample bridge ready on http://{args.host}:{args.port} using {args.sample_root}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
