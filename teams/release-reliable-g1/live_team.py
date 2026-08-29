"""Validated role-recovery guard on the Release and Run generalist."""
from __future__ import annotations

import importlib
from dataclasses import replace

from live_match_server import discover_teams, load_strategy


class RecoveryGuardTeam:
    def __init__(self):
        self.parent = load_strategy(discover_teams()["release-and-run"], "release-reliable-g1-parent")
        self.agents = self.parent.agents
        package = self.parent.__class__.__module__.rsplit(".", 1)[0]
        self.perception_module = importlib.import_module(package + ".shared.perception")
        self.commands_module = importlib.import_module(package + ".shared.commands")

    def decide(self, payload: dict):
        result = self.parent.decide(payload)
        if getattr(result, "source", "") != "error-idle" or "MOVE_TO" not in str(getattr(result, "error", "")):
            return result
        perception = self.perception_module.build_perception(payload)
        player_id = int(payload["myPlayers"][0])
        anchor = self.perception_module.dynamic_anchor(perception, player_id)
        for target_x, target_y in ((anchor.x, anchor.y), (anchor.x, anchor.y-6.0), (anchor.x, anchor.y+6.0), (anchor.x-4.0, anchor.y), (anchor.x+4.0, anchor.y)):
            try:
                self.perception_module.validate_semantics(perception, "MOVE_TO", target_x=target_x, target_y=target_y)
            except ValueError:
                continue
            command = self.commands_module.MoveTo(commandType="MOVE_TO", target_x=target_x, target_y=target_y, sprint=False)
            decision = self.commands_module.AgentDecision(command=command, rationale="Validated role recovery after model movement repair failed.")
            wire = self.commands_module.to_wire(decision, int(payload["teamId"]), player_id)
            return replace(result, wire=wire, source="deterministic-recovery", rationale=decision.rationale, error=None)
        return result


def create_team():
    return RecoveryGuardTeam()
