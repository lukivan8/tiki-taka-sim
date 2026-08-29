"""English prompt mutation layered on the immutable Release and Run parent."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Release Counterpress G1 — authoritative current-state priorities
These rules use only the current observation and override conflicting general examples.

When the opponent controls the ball or the ball is free:
- If you are explicitly named the primary ball player, close immediately with PRESS_BALL intensity=1.0 or INTERCEPT aggressive=true, choosing only an available command. The objective is a recovery before the opponent can reach a shooting state.
- If you are not primary, never join the chase. Players 1 and 3 recover their channels, player 2 protects the central goal route, and player 4 remains a central counter outlet.

When our team controls the ball:
- The owner carries or passes forward; a backward pass is an emergency action only.
- The far wing advances ahead and inside while player 2 remains the sole rest defender.
- Finish immediately whenever HIGH_QUALITY_SHOT or GOOD_ENOUGH_SHOT is reported.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["release-and-run"], "release-counterpress-g1-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
