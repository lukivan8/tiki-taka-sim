"""Deterministic 60-decision simulator probe; no model calls or mutable clock."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


# One line per decision makes the intended experiment obvious in the replay.
SCHEDULE = (
    "movement-straight", "movement-diagonal", "movement-boundary",
    "movement-collision-approach", "movement-collision-contact", "orientation-mirror",
    "pass-short-stage", "pass-short-clear", "pass-receive",
    "pass-medium-stage", "pass-medium-clear", "pass-receive",
    "pass-long-stage", "pass-long-clear", "pass-receive",
    "pass-diagonal-stage", "pass-diagonal-clear", "pass-receive",
    "pass-medium-natural-pressure-stage", "pass-medium-natural-pressure-stage", "pass-medium-natural-pressure",
    "pass-medium-natural-lane-stage", "pass-medium-natural-lane-stage", "pass-medium-natural-lane",
    "pressure-far-stage", "pressure-far", "pressure-near-stage", "pressure-near",
    "pressure-pass-before-contact", "interception-stage", "interception-near",
    "tackle-stage", "tackle-near", "defensive-next-decision-reach",
    "control-recovery", "control-recovery",
    "shot-central-stage", "shot-central", "shot-recovery",
    "shot-wide-stage", "shot-wide", "shot-recovery",
    "shot-close-stage", "shot-close", "shot-recovery",
    "shot-natural-blocker-stage", "shot-natural-blocker", "shot-recovery",
    "shot-sample-keeper-stage", "shot-sample-keeper", "shot-rebound",
    "boundary-repeat", "collision-repeat", "pressure-repeat", "interception-repeat",
    "shot-final-stage", "shot-final", "control-final", "orientation-final", "probe-finish",
)


@dataclass(frozen=True)
class ProbeDecision:
    wire: dict[str, Any]
    source: str
    rationale: str
    error: None = None
    model_prompt: None = None


def _pid(player: dict) -> int:
    return int(player["agentId"].rsplit("_", 1)[1])


def _is_team(player: dict, team_id: int) -> bool:
    return player["teamCode"] == ("home" if team_id == 0 else "away")


def _wire(kind: str, team_id: int, player_id: int, **params: Any) -> dict[str, Any]:
    return {"commandType": kind, "teamId": team_id, "playerId": player_id,
            "parameters": params, "duration": 0}


class SimulatorProbeTeam:
    def decide(self, payload: dict) -> ProbeDecision:
        state = payload["gameState"]
        team_id = int(payload["teamId"])
        player_id = int(payload["myPlayers"][0])
        decision = min(len(SCHEDULE) - 1, max(0, int(round(float(state.get("gameTime", 0)) / 2.0))))
        phase = SCHEDULE[decision]
        command, detail = self._command(state, team_id, player_id, decision, phase)
        marker = f"PROBE {phase.split('-', 1)[0]} player={player_id} experiment={phase} {detail}".strip()
        return ProbeDecision(command, f"probe:{phase}", marker)

    def _command(self, state: dict, team_id: int, player_id: int,
                 decision: int, phase: str) -> tuple[dict, str]:
        players = state.get("players") or []
        mine = [p for p in players if _is_team(p, team_id)]
        me = next(p for p in mine if _pid(p) == player_id)
        attack = 1.0 if team_id == 0 else -1.0
        ball = state.get("ball") or {}
        owner_team = ball.get("possessionTeamId")
        owner_agent = ball.get("possessionAgentId")
        owner_id = int(owner_agent.rsplit("_", 1)[1]) if owner_agent else None
        i_own = owner_team == team_id and owner_id == player_id
        team_owns = owner_team == team_id
        ball_pos = ball.get("position") or {"x": 0.0, "y": 0.0}

        def move(x: float, y: float, sprint: bool = False):
            return _wire("MOVE_TO", team_id, player_id, target_x=x, target_y=y, sprint=sprint)

        # Parallel movement/orientation/bounds/collision measurements.
        if decision <= 5:
            targets = {
                0: (-54.0 * attack, 0.0),
                1: (-8.0 * attack, -18.0),
                2: (0.0, 0.0),
                3: (16.0 * attack, -22.0),
                4: (54.0 * attack, 34.0),
            }
            if decision in (3, 4):
                targets[1] = targets[3] = (4.0 * attack, -8.0)
            x, y = targets[player_id]
            return move(x, y, decision in (1, 2, 3)), f"target=({x},{y}) side={team_id}"

        # Passing stages place receivers at known short/medium/long/diagonal offsets.
        pass_specs = {
            "short": (1, -2.0, 0.0), "medium": (3, 16.0, 0.0),
            "long": (4, 40.0, 0.0), "diagonal": (3, 24.0, 18.0),
            "medium-natural-pressure": (4, 34.0, -8.0),
            "medium-natural-lane": (4, 34.0, 8.0),
        }
        if phase.startswith("pass-"):
            name = phase.removeprefix("pass-").removesuffix("-stage").removesuffix("-clear")
            if ball.get("isFree", True):
                return _wire("INTERCEPT", team_id, player_id, aggressive=False), "free-ball-reacquisition"
            if name == "receive":
                return move(ball_pos["x"], ball_pos["y"], False), "receiver-control-follow-ball"
            target_id, rx, ry = pass_specs[name]
            target_x, target_y = rx * attack, ry
            # The built-in sample is uncontrolled. Recover from it instead of
            # assuming its players will follow a second copy of this schedule.
            if owner_team is not None and owner_team != team_id:
                nearest = min(mine, key=lambda p: math.dist(
                    (p["position"]["x"], p["position"]["y"]),
                    (ball_pos["x"], ball_pos["y"])))
                if _pid(nearest) == player_id:
                    return _wire("PRESS_BALL", team_id, player_id, intensity=1.0), "sample-owner-recovery"
                if player_id == target_id:
                    return move(target_x, target_y), "receiver-staged-while-recovering"
                return move((-12.0 + player_id * 7.0) * attack,
                            -12.0 + player_id * 6.0), "recovery-shape"
            if phase.endswith("stage") or not i_own:
                if player_id == target_id:
                    return move(target_x, target_y), f"receiver={target_id} target=({target_x},{target_y})"
                return move((-12.0 + player_id * 7.0) * attack, (-12.0 + player_id * 6.0)), "pass-shape"
            actual_target = target_id if target_id != player_id else (target_id + 1) % 5
            target = next(p for p in mine if _pid(p) == actual_target)
            distance = math.dist((me["position"]["x"], me["position"]["y"]),
                                 (target["position"]["x"], target["position"]["y"]))
            if distance > 2.3:
                return _wire("PASS", team_id, player_id, target_player_id=actual_target, type="GROUND"), \
                    f"execute target={actual_target} observed-distance={distance:.1f}"
            return move(target_x, target_y), f"skipped-target-too-close distance={distance:.1f}"

        # Controlled defensive spacing. Only the non-owner P1 performs the test command.
        if any(word in phase for word in ("pressure", "interception", "tackle", "defensive-next")):
            if ball.get("isFree", True):
                return _wire("INTERCEPT", team_id, player_id, aggressive=False), "free-ball-reacquisition"
            defending = owner_team is not None and owner_team != team_id
            distance = 8.0 if "far" in phase else (2.0 if "tackle" in phase else 3.5)
            if defending and player_id == 1:
                owner_attack = 1.0 if owner_team == 0 else -1.0
                target_x, target_y = ball_pos["x"] - owner_attack * distance, ball_pos["y"]
                if "stage" in phase:
                    return move(target_x, target_y, True), f"stage-distance={distance}"
                actual = math.dist((me["position"]["x"], me["position"]["y"]),
                                   (ball_pos["x"], ball_pos["y"]))
                if "tackle" in phase and actual <= 2.2:
                    return _wire("SLIDE_TACKLE", team_id, player_id,
                                 target_player_id=owner_id, sprint=True, distance=2.2), f"range={actual:.1f}"
                if "interception" in phase:
                    return _wire("INTERCEPT", team_id, player_id, aggressive=True), f"range={actual:.1f}"
                return _wire("PRESS_BALL", team_id, player_id, intensity=1.0), f"range={actual:.1f}"
            if team_owns and i_own and phase == "pressure-pass-before-contact":
                target = 3 if player_id != 3 else 4
                return _wire("PASS", team_id, player_id, target_player_id=target, type="GROUND"), "owner-pass-before-contact"
            return move((-18.0 + player_id * 8.0) * attack, 12.0), "support-or-observe"

        # Shot stages move the actual owner and defending keeper/blocker; execution is possession-gated.
        if phase.startswith("shot-"):
            name = "rebound" if phase == "shot-recovery" else phase.removeprefix("shot-").removesuffix("-stage")
            execute_shot = name in {"central", "wide", "close", "natural-blocker", "sample-keeper", "final"} \
                and not phase.endswith("stage")
            locations = {
                "central": (24.0, 0.0), "wide": (31.0, 20.0), "close": (40.0, 0.0),
                "natural-blocker": (34.0, 0.0), "sample-keeper": (36.0, -12.0),
                "rebound": (40.0, 0.0), "final": (38.0, 8.0),
            }
            shot_x, shot_y = locations[name]
            if owner_team is not None and owner_team != team_id:
                nearest = min(mine, key=lambda p: math.dist(
                    (p["position"]["x"], p["position"]["y"]),
                    (ball_pos["x"], ball_pos["y"])))
                if _pid(nearest) == player_id:
                    return _wire("PRESS_BALL", team_id, player_id, intensity=1.0), "sample-owner-recovery"
                return move((-10.0 + player_id * 7.0) * attack,
                            player_id * 5.0 - 10.0), "shot-recovery-shape"
            if phase.endswith("stage") and i_own:
                return move(shot_x * attack, shot_y, True), f"shot-location=({shot_x * attack},{shot_y})"
            if execute_shot and i_own:
                aim = "CENTER" if name in {"central", "close", "natural-blocker"} else ("TR" if attack > 0 else "TL")
                return _wire("SHOOT", team_id, player_id, aim_location=aim, power=1.0), f"execute aim={aim}"
            if ball.get("isFree", True):
                return _wire("INTERCEPT", team_id, player_id, aggressive=True), "rebound-chase"
            return move((-10.0 + player_id * 7.0) * attack, player_id * 5.0 - 10.0), "shot-observer"

        # Final repeat/control decisions remain valid regardless of possession.
        if phase == "control-recovery" and ball.get("isFree", True):
            return _wire("INTERCEPT", team_id, player_id, aggressive=False), "free-ball-reacquisition"
        if i_own and phase in {"control-final", "probe-finish"}:
            return move(20.0 * attack, 0.0), "controlled-carry"
        if phase == "interception-repeat":
            return _wire("INTERCEPT", team_id, player_id, aggressive=False), "repeat"
        return move((player_id * 9.0 - 18.0) * attack, player_id * 6.0 - 12.0), "repeat-observation"


def create_team() -> SimulatorProbeTeam:
    return SimulatorProbeTeam()
