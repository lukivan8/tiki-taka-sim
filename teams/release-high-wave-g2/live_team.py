"""English high-wave formation crossover layered on immutable Release and Run."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Release High Wave G2 — authoritative current-state priorities
The actual starting formation for this candidate is 1-3: player 1 is the initial defender, while players 2, 3, and 4 begin high. Trust the current observation over any inherited formation example.

At kickoff and during team control:
- The owner plays the open action with greatest immediate forward progress. Never recycle toward the goalkeeper while a forward or square route is measured open.
- High players keep separate left, central, and right lanes. Do not approach the owner; advance beyond the nearest defender or hold an open shooting lane.
- If SHOOT is available, finish immediately.

Without possession:
- Only the named primary player presses or intercepts. Player 1 protects the central route; the other non-primary players recover without clustering.
- On recovery, attack before the opponent can restore shape: carry into open space or release to the highest open teammate.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["release-and-run"], "release-high-wave-g2-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
