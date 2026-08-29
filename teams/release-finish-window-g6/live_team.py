"""Measured finish-window mutation layered on Release Balanced G5."""
from __future__ import annotations

import importlib

from live_match_server import discover_teams, load_strategy


def create_team():
    parent = load_strategy(discover_teams()["release-balanced-g5"], "release-finish-window-g6-parent")
    base = parent.parent.parent
    package = base.__class__.__module__.rsplit(".", 1)[0]
    perception_module = importlib.import_module(package + ".shared.perception")
    runtime_module = importlib.import_module(package + ".shared.runtime")

    def measured_finish(perception):
        if not perception.owns_ball or perception.player_id == 0:
            return False
        distance, angle, visible, blockers = perception_module._shot_geometry(
            perception, perception.self_player.position
        )
        return distance <= 22.0 and angle >= 9.0 and not blockers and bool(visible)

    perception_module.high_quality_shot = measured_finish
    runtime_module.high_quality_shot = measured_finish
    for agent in parent.agents.values():
        suffix = """

## Release Finish Window G6
The sensor now marks a finish as mandatory only when the owner is within 22 metres, the shooting lane has no measured blocker, the goal angle is at least nine degrees, and an aim is visible. When SHOOT is the only available command, execute it immediately. Return a brief English rationale.
"""
        prompt = getattr(agent, "afc_system_prompt", "") + suffix
        if hasattr(agent, "system_prompt"):
            agent.system_prompt = prompt
        agent.afc_system_prompt = prompt
    return parent
