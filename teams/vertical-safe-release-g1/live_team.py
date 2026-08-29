"""English robustification prompt layered on immutable Nova Vertical."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Vertical Safe Release G1 — authoritative current-state priorities
Use only the current observation and override conflicting general examples.

When you own the ball under close pressure:
- Never choose a pass labelled risky when an open pass or executable forward dribble exists.
- Choose the open forward or square pass with the largest positive interception margin. If none exists, carry through the best open forward corridor.
- A backward pass is an emergency action only; do not use it to escape pressure when a measured forward route is available.

When you do not own the ball during team control:
- The two forwards keep different lanes and different depths. Stay ahead of the ball, outside a defender's shadow, and at least five metres from the other forward.
- The midfielder remains a clear release behind the forwards; the defender retains central rest defence.

Choose SHOOT immediately whenever it is available. Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["nova-vertical"], "vertical-safe-release-g1-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
