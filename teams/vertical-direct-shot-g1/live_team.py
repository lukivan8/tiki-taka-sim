"""English shot-commitment prompt layered on immutable Nova Vertical."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Vertical Direct Shot G1 — authoritative current-state priorities
Use only the current observation and override conflicting general examples.

- If SHOOT appears in AVAILABLE COMMANDS, choose SHOOT now with the best reported open aim and high power. Do not take another pass or dribble.
- A ball owner outside shooting range chooses the action with the greatest immediate forward progress: an open forward pass first, otherwise an executable forward dribble.
- Forwards without the ball remain high and wide enough to receive beyond the nearest defender. They must not approach the owner or recycle toward the goalkeeper.
- On a free ball, only the named primary player intercepts. Everyone else keeps the next passing or shooting lane open.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["nova-vertical"], "vertical-direct-shot-g1-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
