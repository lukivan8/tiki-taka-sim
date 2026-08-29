"""English deep-denial mutation layered on immutable Release and Run."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Release Deep Denial G2 — authoritative current-state priorities
The repeated threat is a wide attacker receiving 8–20 metres from goal and shooting after the goalkeeper is drawn forward.

When the opponent controls the ball:
- Only the explicitly named primary player closes the ball. Use controlled PRESS_BALL rather than an unnecessary tackle.
- Player 2 stays goal-side in the central route and never follows the ball to a wing.
- Player 1 protects the left inner channel and player 3 protects the right inner channel. Non-primary defenders recover to their dynamic role target and stay between a high forward and goal; do not advance toward the owner.
- Player 4 remains a central outlet but does not leave the middle to chase.

When our team wins the ball, release forward immediately to player 4 or the far wing if that pass is open; otherwise carry through the clearest forward corridor. Finish every available shot.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["release-and-run"], "release-deep-denial-g2-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
