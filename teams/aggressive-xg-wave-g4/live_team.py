"""Executable penetration guard for Aggressive xG Wave G3."""
from __future__ import annotations

import importlib

from live_match_server import discover_teams, load_strategy


MINIMUM_PROGRESSIVE_PASS = 5.0
MAXIMUM_GUARDED_CARRY_X = 38.0


MUTATION = """

## Aggressive xG Wave G4 — break the safe-pass loop
- An owner without a genuinely open forward pass must penetrate by the supplied forward or diagonal carry. Do not exchange another harmless square pass.
- The nearest forward clears the carrier's lane; the other forward remains available for the switch or next close finish.
- After the carry commits a defender, release the newly open runner immediately. Inside the close-finish state, shoot without another touch.

Return exactly one available command with every required field and a brief English rationale.
"""


class AggressiveXGWaveG4:
    def __init__(self):
        self.parent = load_strategy(
            discover_teams()["aggressive-xg-wave-g3"],
            "aggressive-xg-wave-g4-parent",
        )
        self.agents = self.parent.agents
        self.perception_module = self.parent.perception_module
        self.commands_module = self.parent.commands_module
        runtime_module = importlib.import_module(
            self.perception_module.__package__ + ".runtime"
        )

        original_allowed = self.perception_module.allowed_commands

        def penetration_allowed_commands(perception):
            commands = original_allowed(perception)
            if (
                not perception.owns_ball
                or perception.player_id == 0
                or commands == ("SHOOT",)
                or "DRIBBLE" not in commands
                or perception.self_player.position.x >= MAXIMUM_GUARDED_CARRY_X
            ):
                return commands
            open_progressive = [
                option
                for option in self.perception_module.pass_options(perception)
                if option[1].open and option[2] >= MINIMUM_PROGRESSIVE_PASS
            ]
            if not open_progressive:
                return ("DRIBBLE",)
            return commands

        self.perception_module.allowed_commands = penetration_allowed_commands
        runtime_module.allowed_commands = penetration_allowed_commands

        for agent in self.agents.values():
            prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
            if hasattr(agent, "system_prompt"):
                agent.system_prompt = prompt
            agent.afc_system_prompt = prompt

    def decide(self, payload: dict):
        return self.parent.decide(payload)


def create_team():
    return AggressiveXGWaveG4()
