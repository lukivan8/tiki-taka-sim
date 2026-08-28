"""Create the five isolated AWS Nova players used by the live simulator."""
from __future__ import annotations

from .shared.runtime import create_agent, invoke_agent


class LiveTeam:
    def __init__(self):
        self.agents = {player_id: create_agent(player_id) for player_id in range(5)}

    def decide(self, payload: dict):
        player_id = int(payload["myPlayers"][0])
        return invoke_agent(self.agents[player_id], player_id, {"prompt": payload})


def create_team() -> LiveTeam:
    return LiveTeam()
