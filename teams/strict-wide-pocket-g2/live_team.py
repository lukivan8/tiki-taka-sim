"""Validator-checked recovery guard for Strict Wide Pocket G1."""
from __future__ import annotations

import importlib
from dataclasses import replace

from live_match_server import discover_teams, load_strategy


class RecoveryGuardTeam:
    def __init__(self):
        self.parent = load_strategy(discover_teams()["strict-wide-pocket-g1"], "strict-wide-pocket-g2-parent")
        self.agents = self.parent.agents
        package = self.parent.__class__.__module__.rsplit(".", 1)[0]
        self.perception_module = importlib.import_module(package + ".shared.perception")
        self.commands_module = importlib.import_module(package + ".shared.commands")

    def _candidate_wire(self, payload: dict):
        perception = self.perception_module.build_perception(payload)
        player_id = int(payload["myPlayers"][0])
        available = self.perception_module.allowed_commands(perception)
        if "DRIBBLE" in available and perception.owns_ball:
            origin = perception.self_player.position
            points = [(min(46.0, origin.x + step), max(-30.0, min(30.0, origin.y + dy)))
                      for step, dy in ((6.0, 0.0), (7.0, -4.0), (7.0, 4.0), (10.0, 0.0))]
            for target_x, target_y in points:
                try:
                    self.perception_module.validate_semantics(perception, "DRIBBLE", target_x=target_x, target_y=target_y)
                except ValueError:
                    continue
                command = self.commands_module.Dribble(commandType="DRIBBLE", target_x=target_x, target_y=target_y, sprint=False)
                return self.commands_module.AgentDecision(command=command, rationale="Validated forward recovery after model carry repair failed.")
        if "MOVE_TO" in available:
            anchor = self.perception_module.dynamic_anchor(perception, player_id)
            for target_x, target_y in ((anchor.x, anchor.y), (anchor.x, anchor.y-4.0), (anchor.x, anchor.y+4.0), (anchor.x-4.0, anchor.y), (anchor.x+4.0, anchor.y)):
                try:
                    self.perception_module.validate_semantics(perception, "MOVE_TO", target_x=target_x, target_y=target_y)
                except ValueError:
                    continue
                command = self.commands_module.MoveTo(commandType="MOVE_TO", target_x=target_x, target_y=target_y, sprint=False)
                return self.commands_module.AgentDecision(command=command, rationale="Validated role recovery after model movement repair failed.")
        return None

    def decide(self, payload: dict):
        result = self.parent.decide(payload)
        if getattr(result, "source", "") != "error-idle":
            return result
        decision = self._candidate_wire(payload)
        if decision is None:
            return result
        player_id = int(payload["myPlayers"][0])
        wire = self.commands_module.to_wire(decision, int(payload["teamId"]), player_id)
        return replace(result, wire=wire, source="deterministic-recovery", rationale=decision.rationale, error=None)


def create_team():
    return RecoveryGuardTeam()
