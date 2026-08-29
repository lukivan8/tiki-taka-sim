"""Chance-quality geometry repair for Aggressive xG Wave G1."""
from __future__ import annotations

import importlib

from live_match_server import discover_teams, load_strategy


CLOSE_FINISH_DISTANCE = 22.0
MINIMUM_FINISH_ANGLE = 10.0


MUTATION = """

## Aggressive xG Wave G2 — chance-quality repair
- The wide pockets are launch positions, not shooting destinations. As the ball advances, forwards arrive in opposite inner channels around y=±8 rather than remaining near the touchline.
- Preserve two receiving lanes: one forward attacks beyond the ball and the other stays available for the early switch. Do not occupy the same lane.
- A clear finish within 22 metres is immediate. Outside that distance, prefer an open release, far-side switch, or inward carry that creates a closer next action.
- Player 2 advances behind the wave as the bounce-pass and counterpress player. Recycle through player 2 only to change the point of attack, never to retreat into passive possession.

Return exactly one available command with every required field and a brief English rationale.
"""


class AggressiveXGWaveG2:
    def __init__(self):
        self.parent = load_strategy(
            discover_teams()["aggressive-xg-wave-g1"],
            "aggressive-xg-wave-g2-parent",
        )
        self.agents = self.parent.agents
        self.perception_module = self.parent.perception_module
        self.commands_module = self.parent.commands_module

        original_anchor = self.perception_module.dynamic_anchor
        original_allowed = self.perception_module.allowed_commands
        point_type = self.perception_module.Point

        def attacking_anchor(perception, player_id):
            base = original_anchor(perception, player_id)
            if perception.possession_team != perception.team_id:
                return base
            ball = perception.ball
            if player_id == 2:
                point = point_type(
                    max(-18.0, min(36.0, ball.x - 7.0)),
                    max(-10.0, min(10.0, ball.y * 0.25)),
                )
                return self.perception_module._avoid_collisions(point, perception)
            if player_id in (3, 4):
                side = -1.0 if player_id == 3 else 1.0
                point = point_type(
                    max(-6.0, min(47.0, ball.x + 24.0)),
                    max(-14.0, min(14.0, side * 8.0 + ball.y * 0.10)),
                )
                return self.perception_module._avoid_collisions(point, perception)
            return base

        def quality_allowed_commands(perception):
            commands = original_allowed(perception)
            if not perception.owns_ball or perception.player_id == 0:
                return commands
            distance, angle, visible, _, _ = self.perception_module._shot_geometry(
                perception, perception.self_player.position
            )
            close_finish = (
                distance <= CLOSE_FINISH_DISTANCE
                and angle >= MINIMUM_FINISH_ANGLE
                and bool(visible)
            )
            if close_finish:
                return ("SHOOT",)
            if commands == ("SHOOT",):
                return ("PASS", "DRIBBLE")
            return tuple(command for command in commands if command != "SHOOT")

        self.perception_module.dynamic_anchor = attacking_anchor
        self.perception_module.allowed_commands = quality_allowed_commands
        self.commands_module.dynamic_anchor = attacking_anchor

        package = self.perception_module.__package__
        runtime_module = importlib.import_module(package + ".runtime")
        runtime_module.allowed_commands = quality_allowed_commands

        for agent in self.agents.values():
            prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
            if hasattr(agent, "system_prompt"):
                agent.system_prompt = prompt
            agent.afc_system_prompt = prompt

    def decide(self, payload: dict):
        return self.parent.decide(payload)


def create_team():
    return AggressiveXGWaveG2()
