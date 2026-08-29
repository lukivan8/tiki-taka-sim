"""English prompt mutation layered on the immutable Release and Run parent."""
from __future__ import annotations

from live_match_server import discover_teams, load_strategy


MUTATION = """

## Release Forward Wave G1 — authoritative current-state priorities
These rules use only the current observation and override conflicting general examples.

When our team controls the ball and you do not own it:
- Players 1 and 3 immediately prefer the named WINGER PASS AND RUN target ahead of the ball and slightly inside. Use MOVE_TO with sprint=true when that command and target are available. Do not recover to a deep anchor during settled team control.
- Player 4 stays as the central outlet ahead of the ball. Move out of a defender's shadow instead of approaching the owner.

When you own the ball:
- Finish immediately whenever HIGH_QUALITY_SHOT or GOOD_ENOUGH_SHOT is reported.
- Outside PANIC, carry through the best open forward corridor unless an open forward or square pass advances the attack faster.
- Inside the final 20 metres with a blocked shot, release to the open advanced wing with the largest positive margin; do not recycle backward.

Return exactly one available command with every required field and a brief English rationale.
"""


def create_team():
    parent = load_strategy(discover_teams()["release-and-run"], "release-forward-wave-g1-parent")
    for agent in parent.agents.values():
        prompt = getattr(agent, "afc_system_prompt", "") + MUTATION
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
