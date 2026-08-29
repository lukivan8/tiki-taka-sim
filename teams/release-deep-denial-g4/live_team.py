"""Deterministic role-recovery guard for the Deep Denial lineage."""
from __future__ import annotations

import importlib
from dataclasses import replace

from live_match_server import discover_teams, load_strategy


class RecoveryGuardTeam:
    def __init__(self):
        self.parent = load_strategy(discover_teams()["release-deep-denial-g3"], "release-deep-denial-g4-parent")
        self.agents = self.parent.agents
        base = self.parent.parent
        package = base.__class__.__module__.rsplit(".", 1)[0]
        self.perception_module = importlib.import_module(package + ".shared.perception")
        self.commands_module = importlib.import_module(package + ".shared.commands")

    def decide(self, payload: dict):
        result = self.parent.decide(payload)
        if getattr(result, "source", "") != "error-idle" or "MOVE_TO" not in str(getattr(result, "error", "")):
            return result
        perception = self.perception_module.build_perception(payload)
        player_id = int(payload["myPlayers"][0])
        anchor = self.perception_module.dynamic_anchor(perception, player_id)
        candidates = [
            (anchor.x, anchor.y), (anchor.x, anchor.y - 6.0), (anchor.x, anchor.y + 6.0),
            (anchor.x - 4.0, anchor.y), (anchor.x + 4.0, anchor.y),
        ]
        for target_x, target_y in candidates:
            try:
                self.perception_module.validate_semantics(perception, "MOVE_TO", target_x=target_x, target_y=target_y)
            except ValueError:
                continue
            decision = self.commands_module.AgentDecision(
                command=self.commands_module.MoveTo(commandType="MOVE_TO", target_x=target_x, target_y=target_y, sprint=False),
                rationale="Deterministic recovery to the nearest valid role-anchor point after model repair failed.",
            )
            wire = self.commands_module.to_wire(decision, int(payload["teamId"]), player_id)
            return replace(result, wire=wire, source="deterministic-recovery", rationale=decision.rationale, error=None)
        return result


def create_team():
    return RecoveryGuardTeam()
