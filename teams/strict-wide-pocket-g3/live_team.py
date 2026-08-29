"""Forward-boundary carry repair for Strict Wide Pocket G2."""
from __future__ import annotations

from dataclasses import replace

from live_match_server import discover_teams, load_strategy


class BoundaryGuardTeam:
    def __init__(self):
        self.parent = load_strategy(discover_teams()["strict-wide-pocket-g2"], "strict-wide-pocket-g3-parent")
        self.agents = self.parent.agents
        self.perception_module = self.parent.perception_module
        self.commands_module = self.parent.commands_module

    def decide(self, payload: dict):
        result = self.parent.decide(payload)
        if getattr(result, "source", "") != "error-idle":
            return result
        perception = self.perception_module.build_perception(payload)
        if not perception.owns_ball or "DRIBBLE" not in self.perception_module.allowed_commands(perception):
            return result
        origin = perception.self_player.position
        inward = -1.0 if origin.y > 0 else 1.0
        candidates = [
            (min(54.5, origin.x + 5.0), origin.y + inward * 6.0),
            (min(54.5, origin.x + 3.0), origin.y + inward * 9.0),
            (min(54.5, origin.x + 5.0), origin.y + inward * 12.0),
        ]
        for target_x, target_y in candidates:
            target_y = max(-34.0, min(34.0, target_y))
            try:
                self.perception_module.validate_semantics(perception, "DRIBBLE", target_x=target_x, target_y=target_y)
            except ValueError:
                continue
            command = self.commands_module.Dribble(commandType="DRIBBLE", target_x=target_x, target_y=target_y, sprint=False)
            decision = self.commands_module.AgentDecision(command=command, rationale="Validated inward carry at the forward touchline boundary.")
            wire = self.commands_module.to_wire(decision, int(payload["teamId"]), int(payload["myPlayers"][0]))
            return replace(result, wire=wire, source="deterministic-recovery", rationale=decision.rationale, error=None)
        return result


def create_team():
    return BoundaryGuardTeam()
