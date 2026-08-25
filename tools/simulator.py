#!/usr/bin/env python3
"""Canonical config-driven 60 Hz football simulation."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


Key = tuple[int, int]


def _distance(a: list[float], b: list[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(x: float, y: float) -> tuple[float, float]:
    length = math.hypot(x, y)
    return (x / length, y / length) if length > 1e-9 else (0.0, 0.0)


def _approach(current: float, target: float, maximum_delta: float) -> float:
    if current < target:
        return min(target, current + maximum_delta)
    return max(target, current - maximum_delta)


@dataclass
class Player:
    key: Key
    position: list[float]
    velocity: list[float] = field(default_factory=lambda: [0.0, 0.0])
    orientation: float = 0.0
    stamina: float = 1.0
    stance: int = 0
    last_action: str = "IDLE"
    sprinting: bool = False
    intent: dict[str, Any] | None = None
    control_blocked_until: int = 0


@dataclass
class Ball:
    position: list[float] = field(default_factory=lambda: [0.0, 0.0])
    velocity: list[float] = field(default_factory=lambda: [0.0, 0.0])
    owner: Key | None = None
    intended_receiver: Key | None = None
    last_kicker: Key | None = None


class SimulationParameters:
    """Strict view of the one authoritative simulationParameters object."""

    REQUIRED_KEYS = {
        "timing": {"physicsHz", "durationSeconds", "decisionIntervalSeconds", "decisionDeadlineMs"},
        "field": {"halfLength", "halfWidth", "goalHalfWidth", "boundaryRestitution", "playerBoundaryMargin"},
        "players": {"walkSpeed", "runSpeed", "sprintSpeed", "acceleration", "braking",
                    "idleVelocityRetentionPerSecond", "targetStopDistance", "physicalRadius",
                    "separationStrength", "possessionBallOffset", "attackingStanceSpeedFactor",
                    "defensiveStanceSpeedFactor"},
        "stamina": {"sprintThreshold", "sprintDrainPerSecond", "movingRecoveryPerSecond",
                    "idleRecoveryPerSecond", "exhaustedSpeedFactor"},
        "ball": {"dragPerSecond", "stopSpeed", "controlRadius", "intendedReceiverRadius",
                 "maxControlSpeed", "maxIntendedReceiveSpeed", "goalkeeperControlRadius",
                 "goalkeeperMaxControlSpeed", "goalkeeperControlDepth", "kickSeparation",
                 "kickerRecontrolSeconds", "lostPossessionRecontrolSeconds", "kickerVelocityRetention"},
        "goalkeeping": {"goalLineOffset", "reactionDelaySeconds", "maximumPredictionSeconds",
                        "minimumIncomingSpeed", "lateralSpeed", "acceleration",
                        "predictionMargin", "maximumLateralPosition"},
        "passing": {"normalSpeed", "throughSpeed", "aerialSpeed", "goalkeeperThrowSpeed",
                    "goalkeeperKickSpeed", "targetLeadSeconds", "minimumTravelDistance"},
        "shooting": {"baseSpeed", "minimumPower", "maximumPower", "targetLeftY",
                     "targetRightY", "targetDepth"},
        "clearances": {"speed", "lateralBias"},
        "defending": {"defaultPressIntensity", "sprintPressThreshold", "tightMarkDistance",
                      "looseMarkDistance", "minimumMarkDistance", "maximumMarkDistance",
                      "interceptLookaheadSeconds", "tackleMinimumReach", "tackleMaximumReach",
                      "tackleBallReleaseSpeed", "tackleRecoverySeconds"},
        "formation": {"defaultPreset", "presets", "awayMirrorX", "awayMirrorY"},
        "rules": {"initialKickoffTeam", "kickoffPlayerId", "kickoffPlayerXOffset"},
    }
    REQUIRED_SECTIONS = set(REQUIRED_KEYS)

    def __init__(self, values: dict[str, Any]):
        missing = self.REQUIRED_SECTIONS - values.keys()
        unknown = values.keys() - self.REQUIRED_SECTIONS
        if missing or unknown:
            raise ValueError(f"simulationParameters sections missing={sorted(missing)} unknown={sorted(unknown)}")
        for section, required in self.REQUIRED_KEYS.items():
            actual = set(values[section])
            missing_keys, unknown_keys = required - actual, actual - required
            if missing_keys or unknown_keys:
                raise ValueError(f"simulationParameters.{section} missing={sorted(missing_keys)} unknown={sorted(unknown_keys)}")
        presets = values["formation"]["presets"]
        default_preset = values["formation"]["defaultPreset"]
        if default_preset not in presets:
            raise ValueError(f"simulationParameters.formation defaultPreset {default_preset!r} is unknown")
        for preset_id, preset in presets.items():
            if set(preset) != {"label", "description", "coordinates"}:
                raise ValueError(f"formation preset {preset_id!r} must contain label, description, coordinates")
            coordinates = preset["coordinates"]
            if sorted(int(item["playerId"]) for item in coordinates) != list(range(5)):
                raise ValueError(f"formation preset {preset_id!r} must place players 0..4 exactly once")
            if any(float(item["x"]) > 0.0 for item in coordinates):
                raise ValueError(f"formation preset {preset_id!r} places a home player outside its own half")
        self.values = copy.deepcopy(values)

    def __getattr__(self, name: str) -> dict[str, Any]:
        try:
            return self.values[name]
        except KeyError as error:
            raise AttributeError(name) from error

    @classmethod
    def load_arena(cls, path: Path) -> tuple[dict[str, Any], "SimulationParameters"]:
        arena = yaml.safe_load(path.read_text(encoding="utf-8"))
        return arena, cls(arena["simulationParameters"])


class World:
    def __init__(self, parameters: SimulationParameters, seed: int = 42,
                 formation_presets: tuple[str, str] | None = None):
        self.p = parameters
        self.seed = seed
        self.tick = 0
        self.score = [0, 0]
        self.ball = Ball()
        self.ended = False
        default_formation = str(self.p.formation["defaultPreset"])
        self.formation_presets = formation_presets or (default_formation, default_formation)
        unknown_formations = set(self.formation_presets) - set(self.p.formation["presets"])
        if unknown_formations:
            raise ValueError(f"unknown formation presets: {sorted(unknown_formations)}")
        self.players: dict[Key, Player] = {}
        self.events: list[dict[str, Any]] = []
        self.metrics = {
            "kicks": 0, "passes": 0, "shots": 0, "tackles": 0,
            "successfulTackles": 0, "possessionChanges": 0,
            "kickerRecaptures": 0, "completedPasses": 0,
            "interceptedPasses": 0, "looseBallSeconds": 0.0,
            "clusterFrames": 0, "duelFrames": 0, "minimumPlayerDistance": 999.0,
            "goalkeeperSaves": 0,
        }
        self._goalkeeper_threat_since: dict[Key, int | None] = {(0, 0): None, (1, 0): None}
        self._reset_positions(reset_score=False, kickoff_team=int(self.p.rules["initialKickoffTeam"]))

    @property
    def hz(self) -> int:
        return int(self.p.timing["physicsHz"])

    @property
    def time(self) -> float:
        return self.tick / self.hz

    def snapshot(self) -> dict[str, Any]:
        players = []
        for key in sorted(self.players):
            player = self.players[key]
            players.append({
                "agentId": f"agentId_{key[1]}",
                "teamCode": "home" if key[0] == 0 else "away",
                "position": {"x": player.position[0], "y": player.position[1]},
                "velocity": {"x": player.velocity[0], "y": player.velocity[1]},
                "orientation": player.orientation,
                "stamina": player.stamina,
                "currentAction": 1 if player.intent else 0,
                "lastAction": player.last_action,
                "speed": math.hypot(*player.velocity),
                "isSprinting": player.sprinting,
            })
        owner = self.ball.owner
        return {
            "tick": self.tick,
            "gameTime": self.time,
            "playMode": "FULL_TIME" if self.ended else "OPEN_PLAY",
            "modeTeamId": None,
            "score": {"home": self.score[0], "away": self.score[1]},
            "ball": {
                "position": {"x": self.ball.position[0], "y": self.ball.position[1], "z": 0.0},
                "velocity": {"x": self.ball.velocity[0], "y": self.ball.velocity[1], "z": 0.0},
                "isFree": owner is None,
                "possessionAgentId": f"agentId_{owner[1]}" if owner else None,
                "possessionTeamId": owner[0] if owner else None,
            },
            "players": players,
            "teamChat": [],
        }

    def compact_frame(self, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        owner = self.ball.owner
        return {
            "type": "simulation_frame", "tick": self.tick, "time": self.time,
            "score": self.score.copy(), "mode": "FULL_TIME" if self.ended else "OPEN_PLAY",
            "ball": [self.ball.position[0], self.ball.position[1], 0.0, owner is None,
                     owner[0] if owner else None, owner[1] if owner else None],
            "players": [[*key, *self.players[key].position] for key in sorted(self.players)],
            "events": events or [],
        }

    def apply_commands(self, commands: dict[Key, dict[str, Any]]) -> list[dict[str, Any]]:
        self.events = []
        owner_before = self.ball.owner
        order = ([owner_before] if owner_before in commands else [])
        order += [key for key in sorted(commands) if key != owner_before]
        for key in order:
            if key not in self.players:
                continue
            command = commands[key]
            try:
                self._apply_command(key, command)
                self.events.append({"type": "COMMAND_APPLIED", "player": self._event_key(key),
                                    "command": command.get("type", "IDLE")})
            except (KeyError, TypeError, ValueError) as error:
                self.events.append({"type": "COMMAND_REJECTED", "player": self._event_key(key),
                                    "reason": str(error)})
        return self.events.copy()

    def _apply_command(self, key: Key, command: dict[str, Any]) -> None:
        kind = str(command.get("type", "IDLE")).upper()
        player = self.players[key]
        player.last_action = kind
        if kind in {"MOVE_TO", "DRIBBLE"}:
            player.intent = {"type": "move", "target": [float(command["target"]["x"]), float(command["target"]["y"])],
                             "sprint": bool(command.get("sprint", False))}
        elif kind == "PRESS_BALL":
            player.intent = {"type": "press", "intensity": float(command.get(
                "intensity", self.p.defending["defaultPressIntensity"]))}
        elif kind == "MARK":
            target_team = 1 - key[0]
            tightness = str(command.get("tightness", "LOOSE")).upper()
            distance = float(command.get("distance", self.p.defending[
                "tightMarkDistance" if tightness == "TIGHT" else "looseMarkDistance"
            ]))
            distance = min(self.p.defending["maximumMarkDistance"],
                           max(self.p.defending["minimumMarkDistance"], distance))
            player.intent = {"type": "mark", "target": (target_team, int(command["targetPlayerId"])),
                             "distance": distance}
        elif kind == "INTERCEPT":
            player.intent = {"type": "intercept", "aggressive": bool(command.get("aggressive", False))}
        elif kind == "IDLE":
            player.intent = None
            player.sprinting = False
        elif kind == "PASS":
            self._require_owner(key, kind)
            target = (key[0], min(4, int(command["targetPlayerId"])))
            if target == key:
                raise ValueError("cannot pass to self")
            target_player = self.players[target]
            if _distance(player.position, target_player.position) < self.p.passing["minimumTravelDistance"]:
                raise ValueError("pass target is too close")
            lead = self.p.passing["targetLeadSeconds"]
            destination = [target_player.position[0] + target_player.velocity[0] * lead,
                           target_player.position[1] + target_player.velocity[1] * lead]
            pass_type = str(command.get("passType", "NORMAL")).upper()
            speed_key = {"THROUGH": "throughSpeed", "AERIAL": "aerialSpeed"}.get(pass_type, "normalSpeed")
            self._kick(key, destination, self.p.passing[speed_key], kind, target)
            self.metrics["passes"] += 1
        elif kind == "GK_DISTRIBUTE":
            self._require_owner(key, kind)
            if key[1] != 0:
                raise ValueError("GK_DISTRIBUTE is goalkeeper-only")
            target = (key[0], min(4, int(command["targetPlayerId"])))
            method = str(command.get("method", "KICK")).upper()
            speed = self.p.passing["goalkeeperThrowSpeed" if method == "THROW" else "goalkeeperKickSpeed"]
            self._kick(key, self.players[target].position, speed, kind, target)
            self.metrics["passes"] += 1
        elif kind == "SHOOT":
            self._require_owner(key, kind)
            aim = str(command.get("aimLocation", "CENTER")).upper()
            target_y = self.p.shooting["targetLeftY"] if aim in {"TL", "BL"} else (
                self.p.shooting["targetRightY"] if aim in {"TR", "BR"} else 0.0
            )
            goal_x = (self.p.field["halfLength"] + self.p.shooting["targetDepth"]) * (1 if key[0] == 0 else -1)
            power = min(self.p.shooting["maximumPower"], max(self.p.shooting["minimumPower"],
                                                              float(command.get("power", 1.0))))
            self._kick(key, [goal_x, target_y], self.p.shooting["baseSpeed"] * power, kind, None)
            self.metrics["shots"] += 1
        elif kind == "CLEAR":
            self._require_owner(key, kind)
            attack = 1 if key[0] == 0 else -1
            bias = self.p.clearances["lateralBias"] * (1 if key[1] % 2 == 0 else -1)
            self._kick_direction(key, attack, bias, self.p.clearances["speed"], kind, None)
        elif kind == "SLIDE_TACKLE":
            self._tackle(key, command)
        else:
            raise ValueError(f"unsupported command {kind}")

    def _require_owner(self, key: Key, kind: str) -> None:
        if self.ball.owner != key:
            raise ValueError(f"{kind} requires possession")

    def _kick(self, key: Key, destination: list[float], speed: float, kind: str,
              receiver: Key | None) -> None:
        dx, dy = destination[0] - self.ball.position[0], destination[1] - self.ball.position[1]
        ux, uy = _unit(dx, dy)
        self._kick_direction(key, ux, uy, speed, kind, receiver)

    def _kick_direction(self, key: Key, dx: float, dy: float, speed: float, kind: str,
                        receiver: Key | None) -> None:
        ux, uy = _unit(dx, dy)
        self.ball.owner = None
        self.ball.last_kicker = key
        self.ball.intended_receiver = receiver
        self.ball.velocity = [ux * speed, uy * speed]
        separation = self.p.ball["kickSeparation"]
        self.ball.position[0] += ux * separation
        self.ball.position[1] += uy * separation
        kicker = self.players[key]
        kicker.intent = None
        kicker.velocity[0] *= self.p.ball["kickerVelocityRetention"]
        kicker.velocity[1] *= self.p.ball["kickerVelocityRetention"]
        kicker.control_blocked_until = self.tick + round(self.p.ball["kickerRecontrolSeconds"] * self.hz)
        self.metrics["kicks"] += 1
        self.events.append({"type": "BALL_KICKED", "player": self._event_key(key), "kind": kind})

    def _tackle(self, key: Key, command: dict[str, Any]) -> None:
        self.metrics["tackles"] += 1
        victim = self.ball.owner
        requested = command.get("targetPlayerId")
        if requested is not None:
            victim = (1 - key[0], min(4, int(requested)))
        reach = min(self.p.defending["tackleMaximumReach"], max(self.p.defending["tackleMinimumReach"],
                    float(command.get("distance", self.p.defending["tackleMaximumReach"]))))
        success = victim in self.players and self.ball.owner == victim and (
            _distance(self.players[key].position, self.players[victim].position) <= reach
        )
        if success:
            old = self.ball.owner
            direction = _unit(self.players[victim].position[0] - self.players[key].position[0],
                              self.players[victim].position[1] - self.players[key].position[1])
            self.ball.owner = None
            self.ball.position = self.players[victim].position.copy()
            self.ball.velocity = [direction[0] * self.p.defending["tackleBallReleaseSpeed"],
                                  direction[1] * self.p.defending["tackleBallReleaseSpeed"]]
            self.ball.last_kicker = key
            self.ball.intended_receiver = None
            self.players[key].control_blocked_until = self.tick + round(
                self.p.defending["tackleRecoverySeconds"] * self.hz)
            self.players[old].control_blocked_until = self.tick + round(
                self.p.ball["lostPossessionRecontrolSeconds"] * self.hz)
            self.metrics["successfulTackles"] += 1
        self.events.append({"type": "TACKLE", "player": self._event_key(key), "success": success})

    def advance_one(self) -> list[dict[str, Any]]:
        if self.ended:
            return []
        frame_events: list[dict[str, Any]] = []
        self._move_players()
        self._separate_players()
        self._move_ball(frame_events)
        self.tick += 1
        scoring_team = self._detect_goal()
        if scoring_team is not None:
            self.score[scoring_team] += 1
            frame_events.append({"type": "GOAL", "team_id": scoring_team,
                                 "home": self.score[0], "away": self.score[1]})
            self._reset_positions(reset_score=False, kickoff_team=1 - scoring_team)
        if self.time >= self.p.timing["durationSeconds"]:
            self.ended = True
            frame_events.append({"type": "MATCH_ENDED", "home": self.score[0], "away": self.score[1]})
        self._sample_metrics()
        return frame_events

    def _move_players(self) -> None:
        dt = 1.0 / self.hz
        positions = {key: player.position.copy() for key, player in self.players.items()}
        ball_position = self.ball.position.copy()
        ball_owner = self.ball.owner
        for player in self.players.values():
            target = None
            sprint = False
            speed_override = None
            acceleration_override = None
            intent = player.intent
            reflex_target = self._goalkeeper_reflex_target(player)
            if reflex_target is not None:
                target = reflex_target
                speed_override = self.p.goalkeeping["lateralSpeed"]
                acceleration_override = self.p.goalkeeping["acceleration"]
            elif intent and intent["type"] == "move":
                target, sprint = intent["target"], intent["sprint"]
            elif intent and intent["type"] == "press":
                target = positions.get(ball_owner, ball_position)
                sprint = intent["intensity"] > self.p.defending["sprintPressThreshold"]
            elif intent and intent["type"] == "mark" and intent["target"] in positions:
                marked = positions[intent["target"]]
                own_goal = [-self.p.field["halfLength"] if player.key[0] == 0 else self.p.field["halfLength"], 0.0]
                ux, uy = _unit(own_goal[0] - marked[0], own_goal[1] - marked[1])
                target = [marked[0] + ux * intent["distance"], marked[1] + uy * intent["distance"]]
            elif intent and intent["type"] == "intercept":
                lead = self.p.defending["interceptLookaheadSeconds"]
                target = [ball_position[0] + self.ball.velocity[0] * lead,
                          ball_position[1] + self.ball.velocity[1] * lead]
                sprint = intent["aggressive"]

            # A two-second strategy command may shade toward the ball, but a
            # goalkeeper must not abandon the goal mouth while merely setting
            # position. Shot interception is handled by the reflex target above.
            if (player.key[1] == 0 and reflex_target is None and target is not None
                    and intent and intent["type"] == "move"):
                lateral_limit = self.p.goalkeeping["maximumLateralPosition"]
                target = [target[0], min(lateral_limit, max(-lateral_limit, target[1]))]

            if target is None:
                retention = self.p.players["idleVelocityRetentionPerSecond"] ** dt
                player.velocity[0] *= retention
                player.velocity[1] *= retention
                player.stamina = min(1.0, player.stamina + self.p.stamina["idleRecoveryPerSecond"] * dt)
                player.sprinting = False
            else:
                dx, dy = target[0] - player.position[0], target[1] - player.position[1]
                ux, uy = _unit(dx, dy)
                wants_sprint = sprint and player.stamina > self.p.stamina["sprintThreshold"]
                base_speed = self.p.players["sprintSpeed"] if wants_sprint else self.p.players["runSpeed"]
                if not sprint:
                    base_speed = self.p.players["walkSpeed"]
                if speed_override is not None:
                    base_speed = speed_override
                stance = self.p.players["attackingStanceSpeedFactor"] if player.stance == 1 else (
                    self.p.players["defensiveStanceSpeedFactor"] if player.stance == 2 else 1.0
                )
                fatigue = self.p.stamina["exhaustedSpeedFactor"] + (1 - self.p.stamina["exhaustedSpeedFactor"]) * player.stamina
                desired_speed = base_speed * stance * fatigue
                if math.hypot(dx, dy) < self.p.players["targetStopDistance"]:
                    desired = [0.0, 0.0]
                else:
                    desired = [ux * desired_speed, uy * desired_speed]
                    player.orientation = math.atan2(uy, ux)
                changing_faster = math.hypot(*desired) > math.hypot(*player.velocity)
                rate = (acceleration_override if changing_faster and acceleration_override is not None else
                        self.p.players["acceleration" if changing_faster else "braking"]) * dt
                player.velocity[0] = _approach(player.velocity[0], desired[0], rate)
                player.velocity[1] = _approach(player.velocity[1], desired[1], rate)
                player.sprinting = wants_sprint
                delta = (-self.p.stamina["sprintDrainPerSecond"] if wants_sprint
                         else self.p.stamina["movingRecoveryPerSecond"]) * dt
                player.stamina = min(1.0, max(0.0, player.stamina + delta))
            margin = self.p.field["playerBoundaryMargin"]
            player.position[0] = min(self.p.field["halfLength"] - margin, max(-self.p.field["halfLength"] + margin,
                                       player.position[0] + player.velocity[0] * dt))
            player.position[1] = min(self.p.field["halfWidth"] - margin, max(-self.p.field["halfWidth"] + margin,
                                       player.position[1] + player.velocity[1] * dt))

    def _goalkeeper_reflex_target(self, player: Player) -> list[float] | None:
        """Return a 60 Hz save target without replacing the goalkeeper's strategic intent."""
        key = player.key
        if key[1] != 0 or self.ball.owner is not None:
            if key[1] == 0:
                self._goalkeeper_threat_since[key] = None
            return None

        goal_direction = -1.0 if key[0] == 0 else 1.0
        incoming_speed = self.ball.velocity[0] * goal_direction
        goal_x = goal_direction * self.p.field["halfLength"]
        keeper_x = goal_direction * (self.p.field["halfLength"] - self.p.goalkeeping["goalLineOffset"])
        if incoming_speed < self.p.goalkeeping["minimumIncomingSpeed"]:
            self._goalkeeper_threat_since[key] = None
            return None

        time_to_goal = (goal_x - self.ball.position[0]) / self.ball.velocity[0]
        if not 0.0 < time_to_goal <= self.p.goalkeeping["maximumPredictionSeconds"]:
            self._goalkeeper_threat_since[key] = None
            return None

        # Drag scales both velocity components equally, so the ground trajectory
        # remains a straight line even though its speed decays.
        predicted_y = self.ball.position[1] + self.ball.velocity[1] * time_to_goal
        reach = self.p.field["goalHalfWidth"] + self.p.goalkeeping["predictionMargin"]
        if abs(predicted_y) > reach:
            self._goalkeeper_threat_since[key] = None
            return None

        first_seen = self._goalkeeper_threat_since[key]
        if first_seen is None:
            self._goalkeeper_threat_since[key] = self.tick
            first_seen = self.tick
        reaction_ticks = round(self.p.goalkeeping["reactionDelaySeconds"] * self.hz)
        if self.tick - first_seen < reaction_ticks:
            return None

        time_to_keeper = (keeper_x - self.ball.position[0]) / self.ball.velocity[0]
        if time_to_keeper <= 0.0:
            return None
        # The save happens where the goalkeeper stands, not five metres behind
        # them on the goal line. For diagonal shots these two Y coordinates can
        # even have opposite signs.
        intercept_y = self.ball.position[1] + self.ball.velocity[1] * time_to_keeper
        lateral_limit = self.p.goalkeeping["maximumLateralPosition"]
        target_y = min(lateral_limit, max(-lateral_limit, intercept_y))
        return [keeper_x, target_y]

    def _separate_players(self) -> None:
        radius = self.p.players["physicalRadius"]
        minimum = radius * 2
        strength = self.p.players["separationStrength"]
        keys = sorted(self.players)
        for index, left_key in enumerate(keys):
            for right_key in keys[index + 1:]:
                left, right = self.players[left_key], self.players[right_key]
                dx, dy = right.position[0] - left.position[0], right.position[1] - left.position[1]
                distance = math.hypot(dx, dy)
                if distance >= minimum:
                    continue
                ux, uy = _unit(dx, dy)
                if distance < 1e-6:
                    ux, uy = (1.0 if left_key < right_key else -1.0), 0.0
                shift = (minimum - distance) * 0.5 * strength
                left.position[0] -= ux * shift
                left.position[1] -= uy * shift
                right.position[0] += ux * shift
                right.position[1] += uy * shift

    def _move_ball(self, events: list[dict[str, Any]]) -> None:
        dt = 1.0 / self.hz
        if self.ball.owner is not None:
            player = self.players[self.ball.owner]
            offset = self.p.players["possessionBallOffset"]
            self.ball.position = [player.position[0] + math.cos(player.orientation) * offset,
                                  player.position[1] + math.sin(player.orientation) * offset]
            self.ball.velocity = player.velocity.copy()
            return
        self.metrics["looseBallSeconds"] += dt
        self.ball.position[0] += self.ball.velocity[0] * dt
        self.ball.position[1] += self.ball.velocity[1] * dt
        damping = math.exp(-self.p.ball["dragPerSecond"] * dt)
        self.ball.velocity[0] *= damping
        self.ball.velocity[1] *= damping
        if math.hypot(*self.ball.velocity) < self.p.ball["stopSpeed"]:
            self.ball.velocity = [0.0, 0.0]
        if abs(self.ball.position[1]) > self.p.field["halfWidth"]:
            self.ball.position[1] = min(self.p.field["halfWidth"], max(-self.p.field["halfWidth"], self.ball.position[1]))
            self.ball.velocity[1] *= -self.p.field["boundaryRestitution"]
        if abs(self.ball.position[0]) > self.p.field["halfLength"] and abs(self.ball.position[1]) >= self.p.field["goalHalfWidth"]:
            self.ball.position[0] = min(self.p.field["halfLength"], max(-self.p.field["halfLength"], self.ball.position[0]))
            self.ball.velocity[0] *= -self.p.field["boundaryRestitution"]

        speed = math.hypot(*self.ball.velocity)
        candidates = []
        for key, player in self.players.items():
            if self.tick < player.control_blocked_until:
                continue
            intended = key == self.ball.intended_receiver
            goalkeeper_in_box = key[1] == 0 and (
                (key[0] == 0 and player.position[0] <= -self.p.field["halfLength"] + self.p.ball["goalkeeperControlDepth"])
                or (key[0] == 1 and player.position[0] >= self.p.field["halfLength"] - self.p.ball["goalkeeperControlDepth"])
            )
            if goalkeeper_in_box:
                radius = self.p.ball["goalkeeperControlRadius"]
                max_speed = self.p.ball["goalkeeperMaxControlSpeed"]
            else:
                radius = self.p.ball["intendedReceiverRadius" if intended else "controlRadius"]
                max_speed = self.p.ball["maxIntendedReceiveSpeed" if intended else "maxControlSpeed"]
            distance = _distance(player.position, self.ball.position)
            if distance <= radius and speed <= max_speed:
                candidates.append((0 if intended else 1, distance, key))
        if not candidates:
            return
        new_owner = min(candidates)[2]
        last_kicker = self.ball.last_kicker
        receiver = self.ball.intended_receiver
        captured_speed = speed
        if new_owner == last_kicker:
            self.metrics["kickerRecaptures"] += 1
        elif receiver is not None and new_owner == receiver:
            self.metrics["completedPasses"] += 1
        elif receiver is not None and new_owner[0] != receiver[0]:
            self.metrics["interceptedPasses"] += 1
        self.ball.owner = new_owner
        self.ball.velocity = [0.0, 0.0]
        self.ball.intended_receiver = None
        self.metrics["possessionChanges"] += 1
        events.append({"type": "POSSESSION_CHANGED", "from": None, "to": self._event_key(new_owner)})
        if new_owner[1] == 0 and last_kicker is not None and last_kicker[0] != new_owner[0]:
            self.metrics["goalkeeperSaves"] += 1
            events.append({"type": "GOALKEEPER_SAVE", "player": self._event_key(new_owner),
                           "shotSpeed": captured_speed})

    def _detect_goal(self) -> int | None:
        if abs(self.ball.position[1]) >= self.p.field["goalHalfWidth"]:
            return None
        if self.ball.position[0] > self.p.field["halfLength"]:
            return 0
        if self.ball.position[0] < -self.p.field["halfLength"]:
            return 1
        return None

    def _reset_positions(self, reset_score: bool, kickoff_team: int) -> None:
        if reset_score:
            self.score = [0, 0]
        self.players.clear()
        for team in (0, 1):
            preset = self.p.formation["presets"][self.formation_presets[team]]
            for item in preset["coordinates"]:
                x, y = float(item["x"]), float(item["y"])
                if team == 1:
                    x = -x if self.p.formation["awayMirrorX"] else x
                    y = -y if self.p.formation["awayMirrorY"] else y
                key = (team, int(item["playerId"]))
                self.players[key] = Player(key, [x, y], orientation=0.0 if team == 0 else math.pi)
        self.ball = Ball()
        self._goalkeeper_threat_since = {(0, 0): None, (1, 0): None}
        kickoff_key = (kickoff_team, int(self.p.rules["kickoffPlayerId"]))
        offset = self.p.rules["kickoffPlayerXOffset"] * (-1 if kickoff_team == 0 else 1)
        self.players[kickoff_key].position = [offset, 0.0]
        self.players[kickoff_key].orientation = 0.0 if kickoff_team == 0 else math.pi
        self.ball.owner = kickoff_key
        self.ball.position = [0.0, 0.0]

    def _sample_metrics(self) -> None:
        positions = [player.position for player in self.players.values()]
        for index, left in enumerate(positions):
            for right in positions[index + 1:]:
                self.metrics["minimumPlayerDistance"] = min(self.metrics["minimumPlayerDistance"], _distance(left, right))
        near = sum(_distance(player.position, self.ball.position) <= 3.0 for player in self.players.values())
        if near >= 3:
            self.metrics["clusterFrames"] += 1
        nearest_by_team = [min(_distance(player.position, self.ball.position)
                               for player in self.players.values() if player.key[0] == team)
                           for team in (0, 1)]
        if max(nearest_by_team) <= 2.6:
            self.metrics["duelFrames"] += 1

    @staticmethod
    def _event_key(key: Key | None) -> dict[str, int] | None:
        return {"team_id": key[0], "player_id": key[1]} if key else None


def normalize_wire_command(wire: dict[str, Any], expected: Key) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the team's canonical wire command and normalize it for physics."""
    if not isinstance(wire, dict):
        raise ValueError("response must be one command object")
    kind = str(wire.get("commandType", "IDLE")).upper()
    params = wire.get("parameters") or {}
    aliases = {
        "target_player_id": "targetPlayerId", "target_team": "targetTeam",
        "aim_location": "aimLocation", "type": "passType",
    }
    normalized: dict[str, Any] = {"type": kind}
    if kind in {"MOVE_TO", "DRIBBLE"}:
        normalized.update(target={"x": float(params["target_x"]), "y": float(params["target_y"])},
                          sprint=bool(params.get("sprint", False)))
    else:
        for source, target in aliases.items():
            if source in params:
                normalized[target] = params[source]
        for name in ("sprint", "intensity", "tightness", "distance", "aggressive", "power", "method"):
            if name in params:
                normalized[name] = params[name]
    if int(wire.get("teamId", expected[0])) != expected[0] or int(wire.get("playerId", expected[1])) != expected[1]:
        # AFC runner normalizes identity to the endpoint binding.
        wire = dict(wire)
    return wire, normalized
