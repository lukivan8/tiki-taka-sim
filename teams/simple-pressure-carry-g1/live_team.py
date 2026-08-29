"""English pressure-and-carry mutation layered on Simple Four Modes."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Simple Pressure Carry G1 — authoritative current-state priorities
- When the opponent owns the ball, only the explicitly named primary player closes immediately with PRESS_BALL intensity=1.0. Every other player keeps the compact 3-1 recovery shape.
- When the ball is free, only the named primary player uses INTERCEPT aggressive=true.
- After our recovery, the owner carries through an open forward corridor unless an open forward pass gains more ground immediately. A backward pass is not progress.
- The far wing advances ahead and inside; the forward stays central and separated. If SHOOT is available, finish immediately.
- Never become a third teammate within six metres of the ball.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["simple-four-modes"], "simple-pressure-carry-g1-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
