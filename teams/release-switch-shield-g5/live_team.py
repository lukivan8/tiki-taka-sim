"""Far-side switch shield layered on Release Deep Denial G4."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Release Switch Shield G5 — defend the successful far-side exploiter
During opponent control, apply these rules over inherited examples:
- Only the named primary player closes the owner.
- If the ball is on our left side, player 3 is the far wingback: recover goal-side into the right inner channel and stay between the far high forward and goal. If the ball is on our right side, player 1 performs the mirrored duty in the left inner channel.
- The far wingback must not approach the owner or become a second presser. Protect the opposite shooting lane before width.
- Player 2 remains central and goal-side. The near wingback delays the ball-side route; player 4 remains the counter outlet.

During our control, use the original Release and Run attack: carry into measured space, release forward under pressure, send the far wing ahead and inside, and finish every available shot.
Never become a third teammate within six metres of the ball. Return one available command with all required fields and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["release-deep-denial-g4"], "release-switch-shield-g5-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
