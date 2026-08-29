"""Narrow model-driven reliability repair for Release Deep Denial G2."""
from __future__ import annotations

from dataclasses import replace

from live_match_server import discover_teams, load_strategy


class RetryingTeam:
    def __init__(self):
        self.parent = load_strategy(discover_teams()["release-deep-denial-g2"], "release-deep-denial-g3-parent")
        self.agents = self.parent.agents

    def decide(self, payload: dict):
        result = self.parent.decide(payload)
        if getattr(result, "source", "") != "error-idle":
            return result
        retry = self.parent.decide(payload)
        if getattr(retry, "source", "") == "error-idle":
            return retry
        return replace(retry, source="nova-retry", error=None)


def create_team():
    return RetryingTeam()
