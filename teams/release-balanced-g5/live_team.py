"""Balanced tactical crossover layered on Release Deep Denial G4."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Release Balanced G5 — authoritative phase split
Trust the current observation. The defensive denial rules apply only while the opponent controls the ball.

During our control:
- Players 1 and 3 must leave the deep line and use the named WINGER PASS AND RUN target ahead of the ball and slightly inside when MOVE_TO is available.
- Player 4 stays separated as the central release. If player 4 owns the ball inside the final 20 metres and cannot shoot, release to the open advanced wing with the best positive margin.
- The owner finishes every available shot. Otherwise carry through measured open space or play the best open forward/square pass; never restore a defensive anchor while owning the ball.
- If two teammates are already within six metres of the ball, every non-primary player moves away toward a distinct role target. Never become a third nearby player.

During opponent control, preserve Deep Denial: one primary closer, player 2 central and goal-side, both wingbacks protecting inner channels, and player 4 as the counter outlet.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["release-deep-denial-g4"], "release-balanced-g5-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
