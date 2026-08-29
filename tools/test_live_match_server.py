#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path
from unittest.mock import patch

import live_match_server
import create_team as create_team_tool
from live_match_server import Handler, LiveMatch, LiveServer, discover_teams, load_strategy
from nova_gateway import GatewayAccess, NovaGateway
from nova_backend import ModelDecision


TEST_TOKEN = "test-token-that-is-long-enough-for-gateway-authentication"


def test_gateway(directory: str, daily_limit: int = 5000,
                 allow_anonymous_matches: bool = False) -> NovaGateway:
    root = Path(directory)
    token_file = root / "tokens.json"
    token_file.write_text(json.dumps({
        "schemaVersion": "afc-gateway-tokens/v1",
        "tokens": [{
            "name": "test", "token": TEST_TOKEN, "dailyCallLimit": daily_limit,
            "requestsPerMinute": 1000, "maxConcurrent": 10,
        }],
    }), encoding="utf-8")
    return NovaGateway(GatewayAccess(
        token_file, root / "usage.sqlite3",
        allow_anonymous_matches=allow_anonymous_matches,
    ))


def authorization_headers(extra=None):
    return {**(extra or {}), "authorization": f"Bearer {TEST_TOKEN}"}


class FakeStrategy:
    def decide(self, payload):
        return {"commandType":"IDLE", "teamId":payload["teamId"],
                "playerId":payload["myPlayers"][0], "parameters":{}, "duration":0}


class SlowFakeStrategy(FakeStrategy):
    def decide(self, payload):
        time.sleep(0.2)
        return super().decide(payload)


class LiveMatchTests(unittest.TestCase):
    def test_hosted_match_can_run_without_token_while_inference_stays_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            server = LiveServer(
                ("127.0.0.1", 0),
                partial(Handler, directory=str(live_match_server.ROOT)),
                test_gateway(directory, allow_anonymous_matches=True),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                request = urllib.request.Request(
                    f"{base}/api/matches",
                    json.dumps({"homeTeamId":"nova-baseline",
                                "awayTeamId":"nova-baseline"}).encode(),
                    {"content-type":"application/json"},
                )
                with patch("live_match_server.load_strategy", return_value=FakeStrategy()):
                    created = json.load(urllib.request.urlopen(request))
                    stop = urllib.request.Request(
                        f"{base}/api/matches/{created['matchId']}/stop", b"{}",
                        {"content-type":"application/json"}, method="POST",
                    )
                    self.assertEqual(urllib.request.urlopen(stop).status, 200)
                    server.matches[created["matchId"]].thread.join(3)

                inference = urllib.request.Request(
                    f"{base}/api/inference", b"{}",
                    {"content-type":"application/json"}, method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(inference)
                self.assertEqual(caught.exception.code, 401)
            finally:
                server.shutdown()
                server.server_close()

    def test_catalog_discovers_the_nova_baseline(self):
        teams = discover_teams()
        self.assertIn("nova-baseline", teams)
        self.assertIn("vertical-wingbacks", teams)
        self.assertEqual(teams["nova-baseline"]["backend"], "nova-micro")
        self.assertTrue((teams["nova-baseline"]["root"] / "live_team.py").is_file())
        self.assertEqual(teams["vertical-wingbacks"]["formationPreset"], "3-1")

    def test_create_team_is_immediately_discoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            teams_root = Path(directory) / "teams"
            shutil.copytree(live_match_server.TEAMS_ROOT / "nova-baseline",
                            teams_root / "nova-baseline")
            previous = create_team_tool.TEAMS_ROOT
            create_team_tool.TEAMS_ROOT = teams_root
            try:
                target = create_team_tool.create_team(
                    "alice-press", "Alice Press", formation="3-1"
                )
            finally:
                create_team_tool.TEAMS_ROOT = previous
            teams = discover_teams(teams_root)
            self.assertEqual(list(teams), ["alice-press", "nova-baseline"])
            self.assertEqual(teams["alice-press"]["name"], "Alice Press")
            self.assertEqual(teams["alice-press"]["backend"], "nova-micro")
            self.assertEqual(teams["alice-press"]["formationPreset"], "3-1")
            self.assertIn("teams/alice-press/agent.py",
                          (target / "team.yaml").read_text(encoding="utf-8"))

    def test_strategy_modules_are_isolated_between_teams(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loaded = []
            for team_id in ("alpha-team", "beta-team"):
                folder = root / team_id
                folder.mkdir()
                (folder / "helper.py").write_text(f"TEAM_ID = {team_id!r}\n", encoding="utf-8")
                (folder / "live_team.py").write_text(
                    "from .helper import TEAM_ID\n"
                    "class Team:\n"
                    "    identity = TEAM_ID\n"
                    "def create_team(): return Team()\n", encoding="utf-8")
                loaded.append(load_strategy({"id":team_id, "root":folder}, team_id))
            self.assertEqual([team.identity for team in loaded], ["alpha-team", "beta-team"])

    def test_generated_real_teams_build_distinct_prompts_on_the_same_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            teams_root = Path(directory) / "teams"
            shutil.copytree(live_match_server.TEAMS_ROOT / "nova-baseline",
                            teams_root / "nova-baseline")
            previous = create_team_tool.TEAMS_ROOT
            create_team_tool.TEAMS_ROOT = teams_root
            try:
                create_team_tool.create_team("alpha-nova", "Alpha Nova")
                create_team_tool.create_team("beta-nova", "Beta Nova")
            finally:
                create_team_tool.TEAMS_ROOT = previous
            teams = discover_teams(teams_root)
            with patch.dict(os.environ, {
                "AFC_NOVA_GATEWAY_URL":"https://gateway.invalid/api/inference",
                "AFC_GATEWAY_TOKEN":TEST_TOKEN,
            }):
                alpha = load_strategy(teams["alpha-nova"], "alpha")
                beta = load_strategy(teams["beta-nova"], "beta")
            alpha_prompt = alpha.agents[0].afc_system_prompt
            beta_prompt = beta.agents[0].afc_system_prompt
            self.assertIn("Alpha Nova", alpha_prompt)
            self.assertIn("Beta Nova", beta_prompt)
            self.assertNotEqual(alpha_prompt, beta_prompt)
            self.assertEqual(alpha.agents[0].afc_decision_source, "nova-gateway")
            self.assertEqual(beta.agents[0].afc_decision_source, "nova-gateway")

    def test_local_clone_can_reuse_its_remote_invite_for_match_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access = GatewayAccess(root / "missing-tokens.json", root / "usage.sqlite3",
                                   inline_token=TEST_TOKEN)
            identity = access.authenticate(f"Bearer {TEST_TOKEN}")
            self.assertEqual(identity.name, "local-developer")
            self.assertGreater(access.reserve_match(identity, 600), 0)

    def test_fast_match_publishes_every_exact_physics_tick(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = live_match_server.LIVE_ROOT
            live_match_server.LIVE_ROOT = Path(directory)
            try:
                with patch("live_match_server.load_strategy", return_value=FakeStrategy()):
                    match = LiveMatch("nova-baseline", "nova-baseline", realtime=False, duration_seconds=0.2)
                    match.start()
                    match.thread.join(5)
            finally:
                live_match_server.LIVE_ROOT = previous
        self.assertEqual(match.status, "finished", match.error)
        frames = [message["frame"] for message in match.messages if message["type"] == "simulation_frame"]
        self.assertEqual([frame["tick"] for frame in frames], list(range(1, 13)))
        self.assertEqual(match.messages[-1]["frameCount"], 13)

    def test_realtime_physics_does_not_wait_for_slow_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = live_match_server.LIVE_ROOT
            live_match_server.LIVE_ROOT = Path(directory)
            timestamps = []
            try:
                with patch("live_match_server.load_strategy", return_value=SlowFakeStrategy()):
                    match = LiveMatch("nova-baseline", "nova-baseline", realtime=True,
                                      duration_seconds=0.4)
                    original_publish = match._publish
                    def timed_publish(message):
                        if message["type"] == "simulation_frame":
                            timestamps.append(time.monotonic())
                        original_publish(message)
                    match._publish = timed_publish
                    match.start()
                    match.thread.join(3)
            finally:
                live_match_server.LIVE_ROOT = previous
        self.assertEqual(match.status, "finished", match.error)
        self.assertGreaterEqual(len(timestamps), 23)
        self.assertLess(max(b-a for a, b in zip(timestamps, timestamps[1:])), 0.08)

    def test_http_api_streams_live_frames_and_can_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = live_match_server.LIVE_ROOT
            live_match_server.LIVE_ROOT = Path(directory)
            server = LiveServer(("127.0.0.1", 0),
                                partial(Handler, directory=str(live_match_server.ROOT)),
                                test_gateway(directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                catalog = json.load(urllib.request.urlopen(f"{base}/api/teams"))
                team_ids = [team["id"] for team in catalog["teams"]]
                self.assertIn("nova-baseline", team_ids)
                self.assertIn("vertical-wingbacks", team_ids)
                self.assertEqual([item["id"] for item in catalog["formations"]], [
                    "1-1-2", "1-2-1", "2-1-1", "2-2-0", "3-1", "1-3",
                    "1-1-1-2-high",
                ])
                override = urllib.request.Request(f"{base}/api/matches",
                    json.dumps({"homeTeamId":"nova-baseline",
                                "awayTeamId":"nova-baseline",
                                "homeFormation":"3-1"}).encode(),
                    authorization_headers({"content-type":"application/json"}))
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(override)
                self.assertEqual(caught.exception.code, 400)
                request = urllib.request.Request(f"{base}/api/matches",
                    json.dumps({"homeTeamId":"nova-baseline",
                                "awayTeamId":"nova-baseline"}).encode(),
                    authorization_headers({"content-type":"application/json"}))
                with patch("live_match_server.load_strategy", return_value=FakeStrategy()):
                    created = json.load(urllib.request.urlopen(request))
                    self.assertEqual(created["formations"],
                                     {"home":"1-1-2", "away":"1-1-2"})
                    ticks = []
                    with urllib.request.urlopen(f"{base}{created['streamUrl']}", timeout=3) as response:
                        while len(ticks) < 3:
                            line = response.readline().decode().strip()
                            if not line.startswith("data: "):
                                continue
                            message = json.loads(line[6:])
                            if message["type"] == "simulation_frame":
                                ticks.append(message["frame"]["tick"])
                    self.assertEqual(ticks, [1, 2, 3])
                    stop = urllib.request.Request(f"{base}/api/matches/{created['matchId']}/stop",
                                                  b"{}", authorization_headers({"content-type":"application/json"}), method="POST")
                    urllib.request.urlopen(stop).read()
                    match = server.matches[created["matchId"]]
                    match.thread.join(3)
                    self.assertEqual(match.status, "stopped")
            finally:
                server.shutdown()
                server.server_close()
                live_match_server.LIVE_ROOT = previous

    def test_inference_gateway_requires_auth_and_returns_strict_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            server = LiveServer(("127.0.0.1", 0),
                                partial(Handler, directory=str(live_match_server.ROOT)),
                                test_gateway(directory))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            payload = json.dumps({
                "schemaVersion":"afc-nova-decision/v1", "playerId":2,
                "systemPrompt":"Ты управляешь только игроком №2.",
                "observation":"Мяч свободен в центре.",
            }).encode()
            try:
                unauthorized = urllib.request.Request(
                    f"{base}/api/inference", payload, {"content-type":"application/json"}
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(unauthorized)
                self.assertEqual(caught.exception.code, 401)
                decision = ModelDecision.model_validate({
                    "commandType":"IDLE", "rationale":"Сохраняю позицию",
                })
                request = urllib.request.Request(
                    f"{base}/api/inference", payload,
                    authorization_headers({"content-type":"application/json"}),
                )
                with patch("nova_gateway.invoke_fixed_nova", return_value=decision):
                    response = json.load(urllib.request.urlopen(request))
                self.assertEqual(response["model"], "us.amazon.nova-micro-v1:0")
                self.assertEqual(response["decision"]["commandType"], "IDLE")
                self.assertNotIn("modelId", response)
            finally:
                server.shutdown()
                server.server_close()

    def test_gateway_rejects_model_override_and_enforces_daily_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            server = LiveServer(("127.0.0.1", 0),
                                partial(Handler, directory=str(live_match_server.ROOT)),
                                test_gateway(directory, daily_limit=1))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            payload = {
                "schemaVersion":"afc-nova-decision/v1", "playerId":2,
                "systemPrompt":"Только игрок №2.", "observation":"Мяч свободен.",
            }
            decision = ModelDecision.model_validate({
                "commandType":"IDLE", "rationale":"Сохраняю позицию",
            })
            try:
                override = urllib.request.Request(
                    f"{base}/api/inference",
                    json.dumps({**payload, "modelId":"another-model"}).encode(),
                    authorization_headers({"content-type":"application/json"}),
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(override)
                self.assertEqual(caught.exception.code, 400)
                request = lambda: urllib.request.Request(
                    f"{base}/api/inference", json.dumps(payload).encode(),
                    authorization_headers({"content-type":"application/json"}),
                )
                with patch("nova_gateway.invoke_fixed_nova", return_value=decision):
                    self.assertEqual(urllib.request.urlopen(request()).status, 200)
                    with self.assertRaises(urllib.error.HTTPError) as exhausted:
                        urllib.request.urlopen(request())
                self.assertEqual(exhausted.exception.code, 429)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
