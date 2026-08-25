from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
try:
    from pydantic import ValidationError
except ModuleNotFoundError as error:
    raise unittest.SkipTest("Nova contract tests require pydantic; run make test-nova") from error

ROOT = Path(__file__).resolve().parents[1]
TEAM_ROOT = ROOT / "team"
sys.path.insert(0, str(TEAM_ROOT))

from shared.commands import AgentDecision, ModelDecision, MoveTo, Pass, to_wire  # noqa: E402
from shared.perception import (allowed_commands, build_perception, responsibility,
                               validate_semantics)  # noqa: E402
from shared.prompting import build_observation, build_system_prompt, load_player  # noqa: E402
import shared.runtime as runtime  # noqa: E402
from shared.runtime import GatewayAgent, invoke_agent  # noqa: E402


def snapshot() -> dict:
    players = []
    positions = {
        0: [(-50, 0), (-29, 0), (-3, 0), (22, -14), (22, 14)],
        1: [(50, 0), (29, 0), (3, 0), (-22, 14), (-22, -14)],
    }
    for team_id in (0, 1):
        code = "home" if team_id == 0 else "away"
        for player_id, (x, y) in enumerate(positions[team_id]):
            players.append({"agentId":f"{code}_{player_id}", "teamCode":code,
                            "position":{"x":x,"y":y}, "speed":0, "stamina":1})
    return {"gameTime":2, "players":players,
            "ball":{"position":{"x":0,"y":0}, "possessionTeamId":None,
                    "possessionAgentId":None}}


def envelope(team_id: int, player_id: int) -> dict:
    return {"prompt":json.dumps({"gameState":snapshot(), "teamId":team_id,
                                  "myPlayers":[player_id]})}


def model_decision(**overrides) -> ModelDecision:
    complete = {
        "commandType":"IDLE", "target_x":None, "target_y":None, "sprint":None,
        "target_player_id":None, "type":None, "aim_location":None, "power":None,
        "intensity":None, "tightness":None, "aggressive":None, "distance":None,
        "method":None, "rationale":"Тестовое решение",
    }
    complete.update(overrides)
    return ModelDecision.model_validate(complete)


class FakeAgent:
    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error

    def structured_output(self, output_model, prompt):
        if self.error:
            raise self.error
        self.output_model = output_model
        self.prompt = prompt
        return self.decision


class NovaTeamTests(unittest.TestCase):
    def test_all_five_players_are_isolated_and_fully_described(self):
        strategy = yaml.safe_load((TEAM_ROOT / "strategy.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(strategy["players"]), set(range(5)))
        for player_id in range(5):
            config, role, situations = load_player(player_id)
            self.assertEqual(config["player_id"], player_id)
            self.assertTrue(config["strategic_focus"]["priorities"])
            self.assertTrue(config["control_points"])
            self.assertNotIn("combinations", config)
            system_prompt = build_system_prompt(player_id)
            self.assertIn(f"ТОЛЬКО игроком №{player_id}", system_prompt)
            self.assertIn(role, system_prompt)
            self.assertIn(situations, system_prompt)
            self.assertIn("stateless", system_prompt)
            self.assertNotIn("Стабильные комбинации", system_prompt)
            self.assertTrue((TEAM_ROOT / strategy["players"][player_id] / "main.py").exists())

        self.assertTrue((TEAM_ROOT / "strategy.md").exists())
        self.assertFalse((TEAM_ROOT / "shared/combinations.yaml").exists())

    def test_pydantic_rejects_incomplete_move(self):
        decision = model_decision(commandType="MOVE_TO", sprint=True, rationale="Открываюсь")
        from shared.commands import validate_model_decision
        with self.assertRaises(ValidationError):
            validate_model_decision(decision)

    def test_pydantic_command_becomes_afc_wire_command(self):
        decision = AgentDecision(command=Pass(commandType="PASS", target_player_id=4,
                                               type="THROUGH"), rationale="Свободна диагональ")
        wire = to_wire(decision, team_id=0, player_id=2)
        self.assertEqual(wire, {"commandType":"PASS", "teamId":0, "playerId":2,
                               "parameters":{"target_player_id":4,"type":"THROUGH"}, "duration":0})

    def test_away_targets_are_mirrored_by_transport(self):
        decision = AgentDecision(command=MoveTo(commandType="MOVE_TO", target_x=30,
                                                 target_y=-12, sprint=True), rationale="Открываюсь слева")
        wire = to_wire(decision, team_id=1, player_id=3)
        self.assertEqual(wire["parameters"], {"target_x":-30,"target_y":12,"sprint":True})

    def test_runtime_uses_structured_output_and_records_rationale(self):
        decision = model_decision(commandType="MOVE_TO", target_x=10, target_y=-8,
                                  sprint=False, rationale="Создаю угол паса")
        agent = FakeAgent(decision=decision)
        agent.afc_decision_source = "nova-micro"
        result = invoke_agent(agent, 3, envelope(0, 3))
        self.assertEqual(agent.output_model, ModelDecision)
        self.assertIn("Текущее наблюдение", agent.prompt)
        self.assertEqual(result.source, "nova-micro")
        self.assertEqual(result.rationale, "Создаю угол паса")
        self.assertEqual(result.wire["commandType"], "MOVE_TO")

    def test_model_failure_is_explicit_idle_not_tactical_fallback(self):
        result = invoke_agent(FakeAgent(error=TimeoutError("deadline")), 1, envelope(0, 1))
        self.assertEqual(result.source, "error-idle")
        self.assertEqual(result.wire["commandType"], "IDLE")
        self.assertIn("TimeoutError", result.error)

    def test_gateway_agent_sends_local_prompt_without_aws_credentials(self):
        captured = {}

        class GatewayHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured["authorization"] = self.headers.get("authorization")
                length = int(self.headers["content-length"])
                captured["payload"] = json.loads(self.rfile.read(length))
                body = json.dumps({"decision": model_decision(
                    commandType="MOVE_TO", target_x=10, target_y=-8,
                    sprint=False, rationale="Открываю линию",
                ).model_dump(by_alias=True)}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        previous = (runtime.GATEWAY_URL, runtime.GATEWAY_TOKEN)
        runtime.GATEWAY_URL = f"http://127.0.0.1:{server.server_address[1]}/api/inference"
        runtime.GATEWAY_TOKEN = "personal-invite-token"
        try:
            agent = GatewayAgent(3, "Персональная роль №3")
            result = agent.structured_output(ModelDecision, "Геометрические факты")
        finally:
            runtime.GATEWAY_URL, runtime.GATEWAY_TOKEN = previous
            server.shutdown()
            server.server_close()
        self.assertEqual(result.structured_output.command_type, "MOVE_TO")
        self.assertEqual(captured["authorization"], "Bearer personal-invite-token")
        self.assertEqual(captured["payload"]["systemPrompt"], "Персональная роль №3")
        self.assertEqual(captured["payload"]["observation"], "Геометрические факты")
        self.assertNotIn("modelId", captured["payload"])

    def test_observation_contains_lines_and_control_points(self):
        observation = build_observation(4, json.loads(envelope(0, 4)["prompt"]))
        self.assertIn("Линии от тебя", observation)
        self.assertIn("правая ударная точка", observation)
        self.assertIn("ТЫ НЕ ПЕРВИЧНЫЙ", observation)
        self.assertIn("ДОСТУПНЫЕ КОМАНДЫ", observation)
        self.assertIn("вратарь", observation)

    def test_only_primary_player_can_intercept_a_free_ball(self):
        payload = json.loads(envelope(0, 4)["prompt"])
        perceptions = [build_perception({**payload, "myPlayers":[pid]}) for pid in range(5)]
        primary = responsibility(perceptions[0])[0][0][1]
        self.assertEqual(primary, 2)
        self.assertIn("INTERCEPT", allowed_commands(perceptions[primary]))
        for pid, perception in enumerate(perceptions):
            if pid != primary:
                self.assertNotIn("INTERCEPT", allowed_commands(perception))

    def test_ball_actions_require_possession(self):
        payload = json.loads(envelope(0, 4)["prompt"])
        perception = build_perception(payload)
        for command in ("PASS", "DRIBBLE", "SHOOT", "CLEAR", "GK_DISTRIBUTE"):
            with self.assertRaises(ValueError):
                validate_semantics(perception, command, 2)


if __name__ == "__main__":
    unittest.main()
