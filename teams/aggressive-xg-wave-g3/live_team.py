"""Nova Vertical crossover with aggressive wave geometry and close finishing."""
from __future__ import annotations

import importlib

from live_match_server import discover_teams, load_strategy


CLOSE_FINISH_DISTANCE = 22.0
MINIMUM_FINISH_ANGLE = 10.0


MUTATION = """

## Aggressive xG Wave G3 — authoritative current-state policy
The objective is to exceed Nova Vertical's chance production while moving a larger share of shots inside 22 metres.

- Attack immediately after recovery. Prefer the open forward pass with the greatest positive margin; the passer then runs beyond and inside instead of dropping out of the attack.
- Preserve two distinct forward lanes. Before the final third, forwards stay separated in wide pockets. Once the ball advances, the far-side forward attacks the opposite inner channel while the ball-side forward preserves the switch lane.
- Against compact pressure, switch to the far high forward before the block can slide. Do not repeat a blocked central pass.
- Outside 22 metres, prefer an open forward release or safe diagonal inward carry over a speculative shot. Inside 22 metres with a clear goal direction, finish immediately.
- Player 2 follows behind the wave as a central bounce option and becomes the first counterpresser after loss. Exactly one player attacks the ball; the rest hold advanced passing and counterpress lanes.
- A regain is never a cue to retreat. Convert it into a forward pass, diagonal carry, or immediate close finish.

Decision order: close finish; open forward release; open far-side switch; diagonal inward carry; central bounce; off-ball inner-channel run; single-player counterpress.
Return exactly one available command with every required field and a brief English rationale.
"""


class AggressiveXGWaveG3:
    def __init__(self):
        self.parent = load_strategy(
            discover_teams()["nova-vertical"],
            "aggressive-xg-wave-g3-parent",
        )
        self.agents = self.parent.agents

        team_package = self.parent.__class__.__module__.rsplit(".", 1)[0]
        shared_package = team_package + ".shared"
        self.perception_module = importlib.import_module(shared_package + ".perception")
        self.commands_module = importlib.import_module(shared_package + ".commands")
        runtime_module = importlib.import_module(shared_package + ".runtime")

        original_anchor = self.perception_module.dynamic_anchor
        original_allowed = self.perception_module.allowed_commands
        point_type = self.perception_module.Point
        clamp = self.perception_module._clamp

        def wave_anchor(perception, player_id):
            base = original_anchor(perception, player_id)
            if perception.possession_team != perception.team_id:
                return base
            ball = perception.ball
            if player_id == 2:
                return point_type(
                    clamp(ball.x - 8.0, -18.0, 34.0),
                    clamp(ball.y * 0.28, -10.0, 10.0),
                )
            if player_id not in (3, 4):
                return base
            side = -1.0 if player_id == 3 else 1.0
            ball_side = ball.y * side > 3.0
            if ball.x < 15.0:
                lane_y = side * 14.0 + ball.y * 0.12
                run_offset = 25.0
            elif ball_side:
                lane_y = side * 12.0 + ball.y * 0.08
                run_offset = 18.0
            else:
                lane_y = side * 7.0 + ball.y * 0.06
                run_offset = 23.0
            return point_type(
                clamp(ball.x + run_offset, -6.0, 48.0),
                clamp(lane_y, -18.0, 18.0),
            )

        def aggressive_allowed_commands(perception):
            commands = original_allowed(perception)
            if not perception.owns_ball or perception.player_id == 0:
                return commands
            distance, angle, visible, _, _ = self.perception_module._shot_geometry(
                perception, perception.self_player.position
            )
            if (
                distance <= CLOSE_FINISH_DISTANCE
                and angle >= MINIMUM_FINISH_ANGLE
                and visible
            ):
                return ("SHOOT",)
            return commands

        self.perception_module.dynamic_anchor = wave_anchor
        self.perception_module.allowed_commands = aggressive_allowed_commands
        self.commands_module.dynamic_anchor = wave_anchor
        runtime_module.allowed_commands = aggressive_allowed_commands

        for agent in self.agents.values():
            prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
            if hasattr(agent, "system_prompt"):
                agent.system_prompt = prompt
            agent.afc_system_prompt = prompt

    def decide(self, payload: dict):
        return self.parent.decide(payload)


def create_team():
    return AggressiveXGWaveG3()
