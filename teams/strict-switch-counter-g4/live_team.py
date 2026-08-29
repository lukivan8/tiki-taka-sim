"""Switch-play champion exploiter layered on Strict Wide Pocket G3."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Strict Switch Counter G4 — target the compact 3-1 denial champion
- When the central route is risky, do not force another central pass. Use the open forward or square pass toward the far high forward with the largest positive interception margin.
- The ball-side forward stays wide enough to pull the wingback outward. The far forward attacks the opposite inner shooting lane; maintain at least twelve metres of separation.
- If no switch is open, the owner carries diagonally away from the nearest presser into measured space. Never dribble into the compact central block.
- The midfielder stays behind the ball as the switch outlet. Finish immediately whenever SHOOT is available.
- Without possession, preserve the strict single-primary ball responsibility and do not cluster.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["strict-wide-pocket-g3"], "strict-switch-counter-g4-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
