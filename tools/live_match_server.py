#!/usr/bin/env python3
"""Static site and live matches streamed as exact 60 Hz simulation frames."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import threading
import time
import types
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from nova_gateway import GatewayAccess, GatewayError, MAX_BODY_BYTES, NovaGateway
from simulator import SimulationParameters, World, normalize_wire_command


ROOT = Path(__file__).resolve().parents[1]
TEAMS_ROOT = ROOT / "teams"
LIVE_ROOT = ROOT / "var/matches"
ARENA_PATH = ROOT / "arena/arena.yaml"

TEAM_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{1,47}")


def discover_teams(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Discover strict, self-contained Nova teams from direct child folders."""
    catalog: dict[str, dict[str, Any]] = {}
    teams_root = root or TEAMS_ROOT
    if not teams_root.is_dir():
        return catalog
    _, parameters = SimulationParameters.load_arena(ARENA_PATH)
    available_formations = set(parameters.formation["presets"])
    for folder in sorted(teams_root.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or folder.name.startswith((".", "_")):
            continue
        manifest_path = folder / "team.yaml"
        if not manifest_path.is_file():
            continue
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != "afc-team/v1":
            raise RuntimeError(f"{manifest_path}: unsupported schemaVersion")
        team_id = str(manifest.get("teamId", ""))
        if not TEAM_ID_PATTERN.fullmatch(team_id) or team_id != folder.name:
            raise RuntimeError(f"{manifest_path}: teamId must equal its slug folder name")
        if manifest.get("backend") != "nova-micro":
            raise RuntimeError(f"{manifest_path}: backend must be nova-micro")
        required = ("displayName", "teamVersion", "description", "formationPreset")
        missing = [key for key in required if not str(manifest.get(key, "")).strip()]
        if missing:
            raise RuntimeError(f"{manifest_path}: missing {', '.join(missing)}")
        formation_preset = str(manifest["formationPreset"])
        if formation_preset not in available_formations:
            raise RuntimeError(
                f"{manifest_path}: unknown formationPreset {formation_preset!r}; "
                f"choose one of {sorted(available_formations)}"
            )
        catalog[team_id] = {
            "id": team_id,
            "name": str(manifest["displayName"]),
            "style": formation_preset,
            "description": str(manifest["description"]),
            "formationPreset": formation_preset,
            "version": str(manifest["teamVersion"]),
            "backend": "nova-micro",
            "root": folder.resolve(),
        }
    return catalog


def public_team(team: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in team.items() if key != "root"}


def formation_catalog() -> list[dict[str, str]]:
    _, parameters = SimulationParameters.load_arena(ARENA_PATH)
    return [{"id": preset_id, "label": preset["label"], "description": preset["description"]}
            for preset_id, preset in parameters.formation["presets"].items()]


def load_strategy(team: dict[str, Any], instance: str):
    team_root = Path(team["root"])
    source = team_root / "live_team.py"
    package_name = "_afc_team_" + hashlib.sha256(
        f"{team_root}:{instance}".encode()
    ).hexdigest()[:20]
    package = types.ModuleType(package_name)
    package.__path__ = [str(team_root)]
    package.__package__ = package_name
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.live_team", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load strategy {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.create_team()


def load_manifest(team: dict[str, Any], side: int) -> dict[str, Any]:
    path = Path(team["root"]) / "team.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest["teamId"] = team["id"]
    manifest["teamVersion"] = team.get("version", manifest.get("teamVersion", "v1"))
    return {"side": side, "manifestPath": str(path), **manifest}


def write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
                            for row in rows), encoding="utf-8")


class LiveMatch:
    def __init__(self, home_id: str, away_id: str, seed: int = 42,
                 realtime: bool = True, duration_seconds: float | None = None):
        self.id = uuid.uuid4().hex[:12]
        teams = discover_teams()
        self.home = teams[home_id]
        self.away = teams[away_id]
        self.seed = seed
        arena, parameters = SimulationParameters.load_arena(ARENA_PATH)
        if duration_seconds is not None:
            values = parameters.values
            values["timing"]["durationSeconds"] = duration_seconds
            parameters = SimulationParameters(values)
        self.arena = arena
        self.parameters = parameters
        self.formations = (self.home["formationPreset"], self.away["formationPreset"])
        self.world = World(parameters, seed, self.formations)
        self.realtime = realtime
        self.condition = threading.Condition()
        self.messages: list[dict[str, Any]] = []
        self.stop_requested = threading.Event()
        self.status = "created"
        self.error: str | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.owner_token_digest: str | None = None
        self.thread = threading.Thread(target=self._run_guarded, name=f"live-match-{self.id}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_requested.set()

    def summary(self) -> dict[str, Any]:
        return {
            "matchId": self.id, "status": self.status, "home": public_team(self.home),
            "away": public_team(self.away), "seed": self.seed, "physicsHz": self.world.hz,
            "formations": {"home": self.formations[0], "away": self.formations[1]},
            "gameTime": self.world.time, "score": self.world.score, "frames": self.world.tick + 1,
            "error": self.error,
        }

    def _publish(self, message: dict[str, Any]) -> None:
        with self.condition:
            self.messages.append(message)
            self.condition.notify_all()

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as error:  # keep API status useful if a strategy fails unexpectedly
            self.error = f"{type(error).__name__}: {error}"
            self.status = "failed"
            self.finished_at = time.time()
            self._publish({"type": "match_failed", "matchId": self.id, "error": self.error})

    def _run(self) -> None:
        self.status = "running"
        self.started_at = time.time()
        home_strategy = load_strategy(self.home, f"{self.id}_home")
        away_strategy = load_strategy(self.away, f"{self.id}_away")
        strategies = {0: home_strategy, 1: away_strategy}
        teams = [load_manifest(self.home, 0), load_manifest(self.away, 1)]
        match_started = {
            "type": "match_started", "schemaVersion": self.arena["replaySchemaVersion"],
            "matchId": self.id, "arena": self.arena, "teams": teams, "seed": self.seed,
            "decisionDeadlineMs": self.parameters.timing["decisionDeadlineMs"],
            "expectedDecisions": round(self.parameters.timing["durationSeconds"] /
                                       self.parameters.timing["decisionIntervalSeconds"]),
            "agentsConfig": "live in-process strategy catalog",
            "matchConfig": {"durationSeconds": self.parameters.timing["durationSeconds"],
                            "decisionIntervalSeconds": self.parameters.timing["decisionIntervalSeconds"],
                            "formations": {"home": self.formations[0], "away": self.formations[1]}},
            "agents": [], "world": self.world.snapshot(), "stateHash": self._state_hash(),
        }
        replay = [match_started]
        recording_frames = [self.world.compact_frame()]
        self._publish({
            "type": "match_started", "matchId": self.id, "arenaVersion": self.arena["arenaVersion"],
            "physicsHz": self.world.hz, "durationSeconds": self.parameters.timing["durationSeconds"],
            "home": public_team(self.home), "away": public_team(self.away), "seed": self.seed,
            "formations": {"home": self.formations[0], "away": self.formations[1]},
            "frame": recording_frames[0],
        })

        interval_steps = round(self.parameters.timing["decisionIntervalSeconds"] * self.world.hz)
        next_frame_deadline = time.monotonic()
        decision_tick = 0
        with ThreadPoolExecutor(max_workers=10) as pool:
            if not self.realtime:
                # Deterministic fast recording mode used by tests and offline analysis.
                while not self.world.ended and not self.stop_requested.is_set():
                    before = self.world.snapshot()
                    before_hash = self._state_hash()
                    futures = [pool.submit(self._decide, strategies[team], team, player, before)
                               for team in (0, 1) for player in range(5)]
                    results = [future.result() for future in futures]
                    commands = {(result["teamId"], result["playerId"]): result["normalizedCommand"]
                                for result in results}
                    interval_events = self.world.apply_commands(commands)
                    for step in range(interval_steps):
                        if self.stop_requested.is_set() or self.world.ended:
                            break
                        physics_events = self.world.advance_one()
                        frame_events = (interval_events if step == 0 else []) + physics_events
                        frame = self.world.compact_frame(frame_events)
                        recording_frames.append(frame)
                        message = {"type": "simulation_frame", "frame": frame,
                                   "decisionTick": decision_tick}
                        if step == 0:
                            message["agentResults"] = results
                        self._publish(message)
                    after = self.world.snapshot()
                    replay.append({
                        "type": "decision", "decisionTick": decision_tick, "matchId": self.id,
                        "arenaVersion": self.arena["arenaVersion"], "worldBefore": before,
                        "worldBeforeHash": before_hash, "agentResults": results,
                        "events": interval_events, "worldAfter": after,
                        "worldAfterHash": self._state_hash(),
                    })
                    decision_tick += 1
            else:
                # The physics clock never waits for Bedrock. Commands are computed from
                # immutable snapshots and atomically replace the previous actions when all
                # ten responses arrive. This keeps the viewer at a true wall-clock 60 Hz.
                pending = None
                next_decision_world_tick = 0
                applied_results = None
                while not self.world.ended and not self.stop_requested.is_set():
                    if pending is None and self.world.tick >= next_decision_world_tick:
                        before = self.world.snapshot()
                        before_hash = self._state_hash()
                        futures = [pool.submit(self._decide, strategies[team], team, player, before)
                                   for team in (0, 1) for player in range(5)]
                        pending = (decision_tick, before, before_hash, futures)
                        decision_tick += 1
                        next_decision_world_tick = self.world.tick + interval_steps

                    interval_events = []
                    if pending is not None and all(future.done() for future in pending[3]):
                        computed_tick, before, before_hash, futures = pending
                        results = [future.result() for future in futures]
                        commands = {(result["teamId"], result["playerId"]): result["normalizedCommand"]
                                    for result in results}
                        interval_events = self.world.apply_commands(commands)
                        replay.append({
                            "type": "decision", "decisionTick": computed_tick,
                            "decisionAppliedAtTick": self.world.tick,
                            "decisionAppliedAtGameTime": self.world.time,
                            "matchId": self.id, "arenaVersion": self.arena["arenaVersion"],
                            "worldBefore": before, "worldBeforeHash": before_hash,
                            "agentResults": results, "events": interval_events,
                            "worldAfter": self.world.snapshot(), "worldAfterHash": self._state_hash(),
                        })
                        applied_results = results
                        pending = None

                    physics_events = self.world.advance_one()
                    frame = self.world.compact_frame(interval_events + physics_events)
                    recording_frames.append(frame)
                    message = {"type": "simulation_frame", "frame": frame,
                               "decisionTick": max(0, decision_tick-1)}
                    if applied_results is not None:
                        message["agentResults"] = applied_results
                        applied_results = None
                    self._publish(message)
                    next_frame_deadline += 1.0/self.world.hz
                    delay = next_frame_deadline-time.monotonic()
                    if delay > 0:
                        time.sleep(delay)

        self.status = "stopped" if self.stop_requested.is_set() else "finished"
        self.finished_at = time.time()
        ended = {
            "type": "match_ended", "schemaVersion": self.arena["replaySchemaVersion"],
            "matchId": self.id, "arenaVersion": self.arena["arenaVersion"], "teams": teams,
            "seed": self.seed,
            "decisionCount": sum(row.get("type") == "decision" for row in replay),
            "score": {"home": self.world.score[0], "away": self.world.score[1]},
            "gameTime": self.world.time, "world": self.world.snapshot(),
            "stateHash": self._state_hash(), "simulationMetrics": self.world.metrics,
            "status": self.status,
        }
        replay.append(ended)
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.started_at))
        stem = f"{timestamp}-{self.id}-{self.home['id']}-vs-{self.away['id']}"
        replay_path = LIVE_ROOT / "matches" / f"{stem}.ndjson"
        recording_path = LIVE_ROOT / "recordings" / f"{stem}.frames.ndjson"
        write_ndjson(replay_path, replay)
        source_sha = hashlib.sha256(replay_path.read_bytes()).hexdigest()
        write_ndjson(recording_path, [{
            "type": "simulation_recording_started", "schemaVersion": "afc-simulation-recording/v1",
            "sourceReplay": str(replay_path), "sourceReplaySha256": source_sha,
            "physicsHz": self.world.hz, "seed": self.seed, "match": match_started,
        }, *recording_frames, {
            "type": "simulation_recording_ended", "frameCount": len(recording_frames),
            "gameTime": self.world.time,
            "score": {"home": self.world.score[0], "away": self.world.score[1]},
            "stateHash": self._state_hash(), "status": self.status,
        }])
        try:
            public_replay = f"/{replay_path.relative_to(ROOT)}"
            public_recording = f"/{recording_path.relative_to(ROOT)}"
        except ValueError:  # used by isolated tests with a temporary output root
            public_replay, public_recording = str(replay_path), str(recording_path)
        self._publish({
            "type": "match_ended", "matchId": self.id, "status": self.status,
            "score": self.world.score, "gameTime": self.world.time,
            "frameCount": len(recording_frames),
            "replay": public_replay, "recording": public_recording,
            "metrics": self.world.metrics,
        })

    def _decide(self, strategy, team: int, player: int,
                snapshot: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        payload = {"gameState": snapshot, "teamId": team, "myPlayers": [player]}
        try:
            decision = strategy.decide(payload)
            wire = decision.wire if hasattr(decision, "wire") else decision
            wire, normalized = normalize_wire_command(wire, (team, player))
            decision_source = getattr(decision, "source", "strategy")
            rationale = getattr(decision, "rationale", None)
            model_error = getattr(decision, "error", None)
            model_prompt = getattr(decision, "model_prompt", None)
            status = "valid" if model_error is None else "fallback"
            error = model_error
        except Exception as caught:
            wire, normalized = None, {"type": "IDLE"}
            status, error = "fallback", f"{type(caught).__name__}: {caught}"
            decision_source, rationale, model_error, model_prompt = "runner-idle", None, error, None
        selected_team = self.home if team == 0 else self.away
        return {
            "teamId": team, "playerId": player, "agentName": f"{selected_team['id']}-p{player}",
            "teamIdentity": selected_team["id"], "teamVersion": selected_team.get("version", "v1"),
            "correlationId": f"{self.id}:{self.world.tick}:{team}:{player}",
            "url": "in-process", "status": status,
            "validationStatus": "accepted" if error is None else "fallback",
            "fallbackApplied": error is not None, "fallbackReason": error,
            "decisionSource": decision_source, "rationale": rationale,
            "modelError": model_error,
            "modelPrompt": model_prompt,
            "latencyMs": round((time.perf_counter() - started) * 1000, 3),
            "request": {"tick": self.world.tick, "teamId": team, "playerId": player},
            "rawResponse": json.dumps(wire) if wire else None, "wireCommand": wire,
            "normalizedCommand": normalized, "error": error,
        }

    def _state_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.world.snapshot(), sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()


class LiveServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, gateway: NovaGateway | None = None):
        super().__init__(address, handler)
        self.matches: dict[str, LiveMatch] = {}
        self.matches_lock = threading.Lock()
        self.gateway = gateway or NovaGateway(GatewayAccess.from_environment())


class Handler(SimpleHTTPRequestHandler):
    server: LiveServer

    def end_headers(self) -> None:
        if not urlparse(self.path).path.startswith("/api/"):
            self.send_header("cache-control", "no-cache")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/teams":
            self.send_json({"teams": [public_team(team) for team in discover_teams().values()],
                            "formations": formation_catalog()})
            return
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "matches"]:
            match = self.server.matches.get(parts[2])
            if match is None:
                self.send_json({"error": "match not found"}, 404)
            elif len(parts) == 4 and parts[3] == "stream":
                self.stream_match(match)
            elif len(parts) == 3:
                self.send_json(match.summary())
            else:
                self.send_json({"error": "unknown API route"}, 404)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/inference":
            try:
                result = self.server.gateway.infer(
                    self.headers.get("authorization"), self.read_json()
                )
                self.send_json(result)
            except GatewayError as error:
                self.send_json({"error": str(error)}, error.status)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, 400)
            except Exception as error:
                print(f"Nova gateway failure: {type(error).__name__}: {error}", flush=True)
                self.send_json({"error": "Nova inference failed"}, 502)
            return
        if path == "/api/matches":
            try:
                payload = self.read_json()
                unknown = set(payload) - {"homeTeamId", "awayTeamId", "seed"}
                if unknown:
                    raise ValueError(
                        "match formations belong to teams; unsupported fields: "
                        + ", ".join(sorted(unknown))
                    )
                home_id, away_id = payload["homeTeamId"], payload["awayTeamId"]
                teams = discover_teams()
                if home_id not in teams or away_id not in teams:
                    raise ValueError("unknown team")
                identity = self.server.gateway.authenticate(self.headers.get("authorization"))
                match = LiveMatch(home_id, away_id, int(payload.get("seed", 42)))
                expected_calls = round(
                    match.parameters.timing["durationSeconds"] /
                    match.parameters.timing["decisionIntervalSeconds"]
                ) * 10
                self.server.gateway.access.reserve_match(identity, expected_calls)
                match.owner_token_digest = identity.token_digest
                with self.server.matches_lock:
                    self.server.matches[match.id] = match
                match.start()
                self.send_json({**match.summary(), "streamUrl": f"/api/matches/{match.id}/stream"}, 201)
            except GatewayError as error:
                self.send_json({"error": str(error)}, error.status)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, 400)
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "matches"] and parts[3] == "stop":
            match = self.server.matches.get(parts[2])
            if match is None:
                self.send_json({"error": "match not found"}, 404)
            else:
                try:
                    identity = self.server.gateway.authenticate(self.headers.get("authorization"))
                    if identity.token_digest != match.owner_token_digest:
                        raise GatewayError(403, "match belongs to another invite token")
                    match.stop()
                    self.send_json({"matchId": match.id, "status": "stopping"})
                except GatewayError as error:
                    self.send_json({"error": str(error)}, error.status)
            return
        self.send_json({"error": "unknown API route"}, 404)

    def stream_match(self, match: LiveMatch) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache, no-transform")
        self.send_header("connection", "keep-alive")
        self.send_header("x-accel-buffering", "no")
        self.end_headers()
        index = 0
        try:
            while True:
                with match.condition:
                    while index >= len(match.messages) and match.status in {"created", "running"}:
                        match.condition.wait(timeout=10)
                    available = match.messages[index:]
                    index = len(match.messages)
                for message in available:
                    self.wfile.write(b"data: ")
                    self.wfile.write(json.dumps(message, separators=(",", ":")).encode())
                    self.wfile.write(b"\n\n")
                self.wfile.flush()
                if match.status not in {"created", "running"} and index >= len(match.messages):
                    break
        except (BrokenPipeError, ConnectionResetError):
            return

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length > MAX_BODY_BYTES:
            raise GatewayError(413, "request body is too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8300)
    args = parser.parse_args()
    handler = partial(Handler, directory=str(ROOT))
    server = LiveServer((args.host, args.port), handler)
    print(f"Live arena ready on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
