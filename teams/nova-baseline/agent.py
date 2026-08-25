#!/usr/bin/env python3
"""Local AFC-compatible HTTP bridge for one isolated Nova Micro player."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from shared.runtime import create_agent, invoke_agent  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    player_id: int
    agent = None

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_json({"status":"ok", "playerId":self.player_id,
                        "model":"us.amazon.nova-micro-v1:0"})

    def do_POST(self):
        if self.path != "/invocations":
            self.send_error(404)
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            result = invoke_agent(self.agent, self.player_id, payload)
            headers = {
                "x-afc-decision-source": result.source,
                "x-afc-rationale": urllib.parse.quote(result.rationale, safe=""),
            }
            if result.error:
                headers["x-afc-model-error"] = urllib.parse.quote(result.error[:500], safe="")
            self.send_json(json.dumps([result.wire], ensure_ascii=False, separators=(",", ":")), headers=headers)
        except Exception as error:
            self.send_json({"error":f"{type(error).__name__}: {error}"}, status=400)

    def send_json(self, value, status=200, headers=None):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--player-id", type=int, choices=range(5), required=True)
    args = parser.parse_args()
    Handler.player_id = args.player_id
    Handler.agent = create_agent(args.player_id)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
