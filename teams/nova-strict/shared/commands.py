"""Strict Pydantic output contract converted to the AFC wire protocol."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .perception import (Perception, Point, _avoid_collisions, allowed_commands,
                         best_pass_target, best_shot_aim, dynamic_anchor)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MoveTo(StrictModel):
    command_type: Literal["MOVE_TO"] = Field(alias="commandType")
    target_x: float = Field(ge=-55, le=55)
    target_y: float = Field(ge=-35, le=35)
    sprint: bool = False


class Dribble(StrictModel):
    command_type: Literal["DRIBBLE"] = Field(alias="commandType")
    target_x: float = Field(ge=-55, le=55)
    target_y: float = Field(ge=-35, le=35)
    sprint: bool = False


class Pass(StrictModel):
    command_type: Literal["PASS"] = Field(alias="commandType")
    target_player_id: int = Field(ge=0, le=4)
    pass_type: Literal["GROUND", "AERIAL", "THROUGH", "NORMAL"] = Field(alias="type")


class Shoot(StrictModel):
    command_type: Literal["SHOOT"] = Field(alias="commandType")
    aim_location: Literal["TL", "TR", "BL", "BR", "CENTER"]
    power: float = Field(ge=0, le=1)


class PressBall(StrictModel):
    command_type: Literal["PRESS_BALL"] = Field(alias="commandType")
    intensity: float = Field(ge=0, le=1)


class Mark(StrictModel):
    command_type: Literal["MARK"] = Field(alias="commandType")
    target_player_id: int = Field(ge=0, le=4)
    tightness: Literal["LOOSE", "TIGHT"]


class Intercept(StrictModel):
    command_type: Literal["INTERCEPT"] = Field(alias="commandType")
    aggressive: bool = False


class SlideTackle(StrictModel):
    command_type: Literal["SLIDE_TACKLE"] = Field(alias="commandType")
    target_player_id: int = Field(ge=0, le=4)
    sprint: bool = True
    distance: float = Field(default=5, ge=0, le=8)


class Clear(StrictModel):
    command_type: Literal["CLEAR"] = Field(alias="commandType")


class GoalkeeperDistribute(StrictModel):
    command_type: Literal["GK_DISTRIBUTE"] = Field(alias="commandType")
    target_player_id: int = Field(ge=0, le=4)
    method: Literal["THROW", "KICK"]


class Idle(StrictModel):
    command_type: Literal["IDLE"] = Field(alias="commandType")


COMMAND_TYPES = {
    "MOVE_TO": MoveTo, "DRIBBLE": Dribble, "PASS": Pass, "SHOOT": Shoot,
    "PRESS_BALL": PressBall, "MARK": Mark, "INTERCEPT": Intercept,
    "SLIDE_TACKLE": SlideTackle, "CLEAR": Clear,
    "GK_DISTRIBUTE": GoalkeeperDistribute, "IDLE": Idle,
}
ALLOWED_FIELDS = {
    "MOVE_TO":{"target_x","target_y","sprint"},
    "DRIBBLE":{"target_x","target_y","sprint"},
    "PASS":{"target_player_id","type"},
    "SHOOT":{"aim_location","power"},
    "PRESS_BALL":{"intensity"},
    "MARK":{"target_player_id","tightness"},
    "INTERCEPT":{"aggressive"},
    "SLIDE_TACKLE":{"target_player_id","sprint","distance"},
    "CLEAR":set(), "GK_DISTRIBUTE":{"target_player_id","method"},
    "IDLE":set(),
}

Command = Annotated[Union[
    MoveTo, Dribble, Pass, Shoot, PressBall, Mark, Intercept,
    SlideTackle, Clear, GoalkeeperDistribute, Idle,
], Field(discriminator="command_type")]


class AgentDecision(StrictModel):
    """Exactly one autonomous action and one short replay explanation."""

    command: Command
    rationale: str = Field(min_length=1, max_length=180,
                           description="Одно короткое объяснение решения для лога реплея.")


class ModelDecision(StrictModel):
    """Flat small-model schema; the selected command is validated strictly afterwards."""

    command_type: Literal[
        "MOVE_TO", "DRIBBLE", "PASS", "SHOOT", "PRESS_BALL", "MARK",
        "INTERCEPT", "SLIDE_TACKLE", "CLEAR", "GK_DISTRIBUTE", "IDLE",
    ] = Field(alias="commandType")
    target_x: float | None = Field(default=None, ge=-55, le=55,
        description="Обязательно для MOVE_TO и DRIBBLE; иначе null.")
    target_y: float | None = Field(default=None, ge=-35, le=35,
        description="Обязательно для MOVE_TO и DRIBBLE; иначе null.")
    sprint: bool | None = Field(default=None,
        description="Для MOVE_TO, DRIBBLE и SLIDE_TACKLE; иначе null.")
    target_player_id: int | None = Field(default=None, ge=0, le=4,
        description="Обязательно для PASS, MARK, SLIDE_TACKLE и GK_DISTRIBUTE; иначе null.")
    pass_type: Literal["GROUND", "AERIAL", "THROUGH", "NORMAL"] | None = Field(
        default=None, alias="type", description="Обязательно для PASS; иначе null.")
    aim_location: Literal["TL", "TR", "BL", "BR", "CENTER"] | None = Field(
        default=None, description="Обязательно для SHOOT; иначе null.")
    power: float | None = Field(default=None, ge=0, le=1,
        description="Обязательно для SHOOT; иначе null.")
    intensity: float | None = Field(default=None, ge=0, le=1,
        description="Обязательно для PRESS_BALL; иначе null.")
    tightness: Literal["LOOSE", "TIGHT"] | None = Field(
        default=None, description="Обязательно для MARK; иначе null.")
    aggressive: bool | None = Field(default=None,
        description="Обязательно для INTERCEPT; иначе null.")
    distance: float | None = Field(default=None, ge=0, le=8,
        description="Для SLIDE_TACKLE; иначе null.")
    method: Literal["THROW", "KICK"] | None = Field(
        default=None, description="Обязательно для GK_DISTRIBUTE; иначе null.")
    rationale: str = Field(min_length=1, max_length=180)


def _nearest_opponent_id(perception: Perception) -> int:
    origin = perception.self_player.position
    return min(perception.opponents.values(),
               key=lambda player: origin.distance_to(player.position)).player_id


def _forward_point(perception: Perception) -> Point:
    """A dribble target that always satisfies the 2 m forward rule."""
    origin = perception.self_player.position
    anchor = dynamic_anchor(perception, perception.player_id)
    if anchor.x >= origin.x+2.5 and origin.distance_to(anchor) >= 2.5:
        return anchor
    fallback = Point(min(origin.x+6.0, 46.0), max(-30.0, min(30.0, origin.y*0.8)))
    return _avoid_collisions(fallback, perception)


def repair_parameters(perception: Perception, kind: str, raw: dict) -> dict:
    """Fill the fields a small model omits so a valid intent never becomes IDLE.

    Nova Micro regularly returns commandType without its mandatory arguments.
    Baseline dropped the whole command and idled the ball owner; here every
    missing field is derived from the same facts the observation already states.
    """
    filled = dict(raw)
    anchor = dynamic_anchor(perception, perception.player_id)
    if kind == "MOVE_TO":
        filled.setdefault("target_x", anchor.x)
        filled.setdefault("target_y", anchor.y)
    if kind == "DRIBBLE":
        point = _forward_point(perception)
        filled.setdefault("target_x", point.x)
        filled.setdefault("target_y", point.y)
    if kind in {"MOVE_TO", "DRIBBLE"}:
        filled.setdefault("sprint", False)
    if kind in {"PASS", "GK_DISTRIBUTE"}:
        target = best_pass_target(perception)
        if target is not None:
            filled.setdefault("target_player_id", target)
    if kind == "PASS":
        filled.setdefault("type", "GROUND")
    if kind == "GK_DISTRIBUTE":
        filled.setdefault("method", "KICK")
    if kind == "SHOOT":
        filled.setdefault("aim_location", best_shot_aim(perception) or "CENTER")
        filled.setdefault("power", 0.9)
    if kind == "PRESS_BALL":
        filled.setdefault("intensity", 0.7)
    if kind == "INTERCEPT":
        filled.setdefault("aggressive", True)
    if kind in {"MARK", "SLIDE_TACKLE"}:
        filled.setdefault("target_player_id", _nearest_opponent_id(perception))
    if kind == "MARK":
        filled.setdefault("tightness", "TIGHT")
    if kind == "SLIDE_TACKLE":
        filled.setdefault("sprint", True)
        filled.setdefault("distance", 5.0)
    return filled


def fallback_decision(perception: Perception) -> AgentDecision:
    """Deterministic last resort. The ball owner acts; only a spare player idles."""
    available = allowed_commands(perception)
    order = ["SHOOT", "PASS", "DRIBBLE", "GK_DISTRIBUTE", "INTERCEPT",
             "PRESS_BALL", "CLEAR", "MOVE_TO", "IDLE"]
    for kind in order:
        if kind not in available:
            continue
        if kind in {"PASS", "GK_DISTRIBUTE"} and best_pass_target(perception) is None:
            continue
        parameters = repair_parameters(perception, kind, {})
        try:
            decision = _build_decision(kind, parameters,
                                       "Детерминированный резерв вместо простоя.")
        except ValidationError:
            continue
        return decision
    return AgentDecision(command=Idle(commandType="IDLE"),
                         rationale="Нет доступного детерминированного резерва.")


def _build_decision(kind: str, raw: dict, rationale: str) -> AgentDecision:
    command_data = {"commandType": kind, **{key: value for key, value in raw.items()
                                            if key in ALLOWED_FIELDS[kind]}}
    return AgentDecision(command=COMMAND_TYPES[kind].model_validate(command_data),
                         rationale=rationale)


def forced_decision(perception: Perception, kind: str) -> AgentDecision:
    """Build the only command the mask allows, without spending a model call.

    When allowed_commands() returns a single option the model picks no command
    type at all, and its target reproduces dynamic_anchor() almost exactly
    (measured: 91 of 93 such decisions landed within 1 m of the anchor).
    """
    return _build_decision(kind, repair_parameters(perception, kind, {}),
                           f"Маска допускает только {kind}: иду в ролевой якорь без вызова модели.")


def validate_model_decision(model_decision: ModelDecision,
                            perception: Perception | None = None) -> AgentDecision:
    raw = model_decision.model_dump(by_alias=True, exclude_none=True)
    kind = raw.pop("commandType")
    rationale = raw.pop("rationale")
    if perception is not None:
        raw = repair_parameters(perception, kind, raw)
    return _build_decision(kind, raw, rationale)


def to_wire(decision: AgentDecision, team_id: int, player_id: int) -> dict:
    command = decision.command
    dumped = command.model_dump(by_alias=True)
    kind = dumped.pop("commandType")
    if kind in {"MOVE_TO", "DRIBBLE"} and int(team_id) == 1:
        dumped["target_x"] = -dumped["target_x"]
        dumped["target_y"] = -dumped["target_y"]
    if kind == "PASS":
        dumped["type"] = dumped.pop("type")
    duration = 3 if kind in {"PRESS_BALL", "MARK", "INTERCEPT", "SLIDE_TACKLE"} else 0
    return {
        "commandType": kind,
        "teamId": int(team_id),
        "playerId": int(player_id),
        "parameters": dumped,
        "duration": duration,
    }


def idle_wire(team_id: int, player_id: int) -> dict:
    return {"commandType": "IDLE", "teamId": int(team_id), "playerId": int(player_id),
            "parameters": {}, "duration": 0}
