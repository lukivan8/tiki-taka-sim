"""Shot-quality and operational reliability repair for Aggressive xG Wave G4."""
from __future__ import annotations

import importlib
from dataclasses import replace

from live_match_server import discover_teams, load_strategy


MAXIMUM_OPTIONAL_SHOT_DISTANCE = 24.0


MUTATION = """

## Aggressive xG Wave G5 — quality and reliability repair
- Do not spend possession on a shot beyond 24 metres. Continue the penetration, release, or switch until a closer lane appears.
- Preserve G4's forward-carry guard and immediate close finish. The aim is repeated high-value chances, not a higher count of hopeful attempts.
- Off-ball players keep their assigned wave lane; if a requested movement is invalid, recover to the nearest legal role-relative point without joining the ball cluster.

Return exactly one available command with every required field and a brief English rationale.
"""


class AggressiveXGWaveG5:
    def __init__(self):
        self.parent = load_strategy(
            discover_teams()["aggressive-xg-wave-g4"],
            "aggressive-xg-wave-g5-parent",
        )
        self.agents = self.parent.agents
        self.perception_module = self.parent.perception_module
        self.commands_module = self.parent.commands_module
        runtime_module = importlib.import_module(
            self.perception_module.__package__ + ".runtime"
        )
        original_allowed = self.perception_module.allowed_commands

        def quality_allowed_commands(perception):
            commands = original_allowed(perception)
            if not perception.owns_ball or perception.player_id == 0 or "SHOOT" not in commands:
                return commands
            distance, _, _, _, _ = self.perception_module._shot_geometry(
                perception, perception.self_player.position
            )
            if distance <= MAXIMUM_OPTIONAL_SHOT_DISTANCE:
                return commands
            filtered = tuple(command for command in commands if command != "SHOOT")
            return filtered or commands

        self.perception_module.allowed_commands = quality_allowed_commands
        runtime_module.allowed_commands = quality_allowed_commands

        for agent in self.agents.values():
            prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
            if hasattr(agent, "system_prompt"):
                agent.system_prompt = prompt
            agent.afc_system_prompt = prompt

    def _recover_move(self, payload: dict, result):
        perception = self.perception_module.build_perception(payload)
        if perception.owns_ball or "MOVE_TO" not in self.perception_module.allowed_commands(perception):
            return result
        player_id = int(payload["myPlayers"][0])
        anchor = self.perception_module.dynamic_anchor(perception, player_id)
        candidates = (
            (anchor.x, anchor.y),
            (anchor.x - 3.0, anchor.y),
            (anchor.x + 3.0, anchor.y),
            (anchor.x, anchor.y - 3.0),
            (anchor.x, anchor.y + 3.0),
        )
        for target_x, target_y in candidates:
            try:
                self.perception_module.validate_semantics(
                    perception,
                    "MOVE_TO",
                    target_x=target_x,
                    target_y=target_y,
                )
            except ValueError:
                continue
            command = self.commands_module.MoveTo(
                commandType="MOVE_TO",
                target_x=target_x,
                target_y=target_y,
                sprint=False,
            )
            decision = self.commands_module.AgentDecision(
                command=command,
                rationale="Validated nearest-lane recovery after movement repair failed.",
            )
            wire = self.commands_module.to_wire(
                decision,
                int(payload["teamId"]),
                player_id,
            )
            return replace(
                result,
                wire=wire,
                source="deterministic-recovery",
                rationale=decision.rationale,
                error=None,
            )
        return result

    def decide(self, payload: dict):
        result = self.parent.decide(payload)
        if getattr(result, "source", "") != "error-idle":
            return result
        return self._recover_move(payload, result)


def create_team():
    return AggressiveXGWaveG5()
