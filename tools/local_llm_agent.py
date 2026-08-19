#!/usr/bin/env python3
"""AFC HTTP bridge for a tiny model served by llama.cpp's OpenAI endpoint."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROLE = {0: "goalkeeper", 1: "defender", 2: "midfielder", 3: "left forward", 4: "right forward"}
ALLOWED = {"MOVE_TO", "PRESS_BALL", "SHOOT", "PASS", "MARK", "IDLE"}


def compact_observation(payload: dict) -> dict:
    state = payload["gameState"]
    team_id = int(payload["teamId"])
    player_id = int(payload["myPlayers"][0])
    side = "home" if team_id == 0 else "away"
    players = []
    for player in state["players"]:
        agent_id = player["agentId"]
        players.append({
            "team": player["teamCode"],
            "id": int(agent_id.rsplit("_", 1)[-1]),
            "x": round(player["position"]["x"], 1),
            "y": round(player["position"]["y"], 1),
        })
    return {
        "you": {"team": side, "id": player_id, "role": ROLE[player_id],
                "attack": "+x" if team_id == 0 else "-x"},
        "time": round(state["gameTime"], 1),
        "score": state["score"],
        "ball": {"x": round(state["ball"]["position"]["x"], 1),
                 "y": round(state["ball"]["position"]["y"], 1),
                 "free": state["ball"]["isFree"],
                 "owner": state["ball"].get("possessionAgentId")},
        "players": players,
    }


def extract_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("model response is not an object")
    return value


def to_wire(choice: dict, team_id: int, player_id: int, observation: dict | None = None) -> dict:
    action = str(choice.get("action", "IDLE")).upper()
    if action not in ALLOWED:
        raise ValueError(f"unsupported action {action}")
    parameters: dict = {}
    if action == "MOVE_TO":
        ball = (observation or {}).get("ball", {})
        parameters = {
            "target_x": max(-55.0, min(55.0, float(choice.get("target_x", ball.get("x", 0))))),
            "target_y": max(-35.0, min(35.0, float(choice.get("target_y", ball.get("y", 0))))),
            "sprint": bool(choice.get("sprint", False)),
        }
    elif action == "PRESS_BALL":
        parameters = {"intensity": max(0.1, min(1.0, float(choice.get("intensity", 0.8))))}
    elif action == "SHOOT":
        parameters = {"aim_location": "CENTER", "power": max(0.3, min(1.0, float(choice.get("power", 0.8))))}
    elif action in {"PASS", "MARK"}:
        target = max(0, min(4, int(choice.get("target_player_id", (player_id + 1) % 5))))
        parameters = {"target_player_id": target}
        if action == "PASS":
            parameters["type"] = "GROUND"
        else:
            parameters["tightness"] = "TIGHT"
    return {"commandType": action, "playerId": player_id, "teamId": team_id,
            "parameters": parameters, "duration": 0}


class Handler(BaseHTTPRequestHandler):
    model_url = ""
    model = ""
    metrics: Path | None = None
    metrics_lock = threading.Lock()

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        self.send_json({"status": "ok", "backend": self.model_url, "model": self.model})

    def do_POST(self):
        if self.path != "/invocations":
            self.send_error(404)
            return
        started = time.monotonic()
        model_valid = False
        raw = ""
        error = None
        action = "IDLE"
        try:
            length = int(self.headers.get("content-length", "0"))
            envelope = json.loads(self.rfile.read(length))
            prompt = envelope.get("prompt", "{}")
            payload = json.loads(prompt) if isinstance(prompt, str) else prompt
            team_id = int(payload["teamId"])
            player_id = int(payload["myPlayers"][0])
            observation = compact_observation(payload)
            request_body = {
                "model": self.model,
                "temperature": 0.1,
                "max_tokens": 80,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "football_decision",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "target_x": {"type": "number"},
                                "target_y": {"type": "number"},
                                "target_player_id": {"type": "integer", "minimum": 0, "maximum": 4},
                                "power": {"type": "number", "minimum": 0.3, "maximum": 1.0},
                                "intensity": {"type": "number", "minimum": 0.1, "maximum": 1.0},
                                "sprint": {"type": "boolean"},
                            },
                            "required": ["action"],
                            "additionalProperties": False,
                        },
                    },
                },
                "messages": [
                    {"role": "system", "content": (
                        "You control one football player. Never repeat the state. Return one tiny JSON object only. "
                        "A good answer is {\"action\":\"PRESS_BALL\"}. Choose one useful action. "
                        "Schema: {\"action\":\"MOVE_TO|PRESS_BALL|SHOOT|PASS|MARK|IDLE\","
                        "\"target_x\":number,\"target_y\":number,\"target_player_id\":0..4,"
                        "\"power\":0.3..1,\"intensity\":0.1..1,\"sprint\":boolean}. "
                        "Use only fields needed by the chosen action. Shoot or pass only if you likely own the ball."
                    )},
                    {"role": "user", "content": "STATE (never copy this):\n" + json.dumps(observation, separators=(",", ":"))
                     + "\nReturn your tiny decision object now:"},
                ],
            }
            req = urllib.request.Request(
                self.model_url.rstrip("/") + "/v1/chat/completions",
                data=json.dumps(request_body).encode(),
                headers={"content-type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                completion = json.load(response)
            raw = completion["choices"][0]["message"]["content"]
            choice = extract_object(raw)
            wire = to_wire(choice, team_id, player_id, observation)
            action = wire["commandType"]
            model_valid = True
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                team_id = int(payload["teamId"])
                player_id = int(payload["myPlayers"][0])
            except Exception:
                self.send_json({"error": error}, status=400)
                return
            wire = to_wire({"action": "IDLE"}, team_id, player_id)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        self.write_metric({"teamId": team_id, "playerId": player_id, "modelValid": model_valid,
                           "action": action, "latencyMs": elapsed_ms, "raw": raw, "error": error})
        # Match the AgentCore sample's JSON-string response envelope.
        self.send_json(json.dumps([wire], separators=(",", ":")))

    def write_metric(self, row: dict):
        if not self.metrics:
            return
        with self.metrics_lock:
            with self.metrics.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")

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
    parser.add_argument("--model-url", default="http://127.0.0.1:8090")
    parser.add_argument("--model", default="local-qwen-0.5b")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8200, type=int)
    parser.add_argument("--metrics", type=Path)
    args = parser.parse_args()
    Handler.model_url = args.model_url
    Handler.model = args.model
    Handler.metrics = args.metrics
    if args.metrics:
        args.metrics.parent.mkdir(parents=True, exist_ok=True)
        args.metrics.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"local LLM bridge ready on http://{args.host}:{args.port} -> {args.model_url}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
