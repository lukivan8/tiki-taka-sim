"""English wide-pocket progression mutation layered on Nova Strict."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Strict Wide Pocket G1 — authoritative current-state priorities
- At kickoff, the owner takes the open action with greatest positive progress; never pass toward our goalkeeper while a forward route is available.
- Forward 3 attacks the left wide shooting pocket and forward 4 attacks the right wide shooting pocket. Stay ahead of the ball, separated by at least ten metres, and outside defender shadows.
- The midfielder releases to the open forward with the larger interception margin. A forward receiving inside 30 metres checks SHOOT before every pass or dribble.
- When SHOOT is the only allowed command, execute it immediately. Non-primary players never join the ball chase.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["nova-strict"], "strict-wide-pocket-g1-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
