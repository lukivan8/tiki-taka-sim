"""High-volume, close-chance attacking crossover built on Strict Wide Pocket G3."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


# The inherited strict substrate forces every geometrically open shot from the
# attacking two-thirds. That created volume but many low-value attempts around
# 25-30 metres. Preserve the mask, but move its compulsory zone close enough to
# reward progression before finishing.
FORCED_FINISH_X = 32.0


MUTATION = """

## Aggressive xG Wave G1 — authoritative attacking crossover
This section overrides inherited advice to shoot merely because a distant shot is available.
The objective is repeated close, open chances—not sterile possession and not speculative volume.

### Immediate transition
- On recovery, attack before the block resets. The owner first takes the open forward pass with the greatest positive interception margin.
- If a high forward receives, the passer immediately runs beyond and inside into the vacated lane. Do not admire the pass or recover while we retain control.
- Player 2 follows the attack as the central bounce option, but stays far enough behind the ball to counterpress a turnover.

### Three-lane wave
- Forwards 3 and 4 begin in separated wide pockets. The ball-side forward comes only far enough to receive; the far forward attacks the opposite inner channel and remains at least twelve metres away.
- After the first forward release, one runner attacks the central or near-post lane and the other preserves the far-side lane. Never let both forwards converge on the owner.
- Prefer an open pass to a runner closer to goal over an extra carry by the owner. A receiver inside 22 metres finishes immediately when a goal direction is clear.

### Break compact blocks
- If the central lane or ball-side lane is risky, switch early to the far high forward with the best positive margin. The switch is a progression action, not a reset.
- If no forward pass or switch is open, carry diagonally into the least-pressured half-space. Carry toward goal and inward; never dribble straight into the nearest defender.
- Outside roughly 22 metres, an available shot is not automatically the best action when an open forward pass or safe advancing carry can create a closer next touch.

### Aggressive rest defence
- On loss, exactly one closest eligible player presses or intercepts immediately at full intensity. Player 2 closes the central return lane.
- Everyone else protects the two direct counter lanes while holding an advanced compact rest-defence shape. Do not retreat into a passive low block while pressure is active.
- On regain, abandon the press shape instantly and restart the three-lane wave.

Decision order: close open finish; open forward release; open far-side switch; safe diagonal carry; central bounce pass; structural attacking run; single-player counterpress.
Return exactly one available command with every required field and a brief English rationale.
"""


class AggressiveXGWaveTeam:
    def __init__(self):
        self.parent = load_strategy(
            discover_teams()["strict-wide-pocket-g3"],
            "aggressive-xg-wave-g1-parent",
        )
        self.agents = self.parent.agents
        self.perception_module = self.parent.perception_module
        self.commands_module = self.parent.commands_module

        # allowed_commands() reads this module constant at decision time.
        self.perception_module.ATTACK_TWO_THIRDS_X = FORCED_FINISH_X

        for agent in self.agents.values():
            prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
            if hasattr(agent, "system_prompt"):
                agent.system_prompt = prompt
            agent.afc_system_prompt = prompt

    def decide(self, payload: dict):
        return self.parent.decide(payload)


def create_team():
    return AggressiveXGWaveTeam()
