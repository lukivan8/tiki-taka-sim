"""Strict Pydantic output contract converted to the AFC wire protocol."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


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
    intensity: float | None = Field(default=0.8, ge=0, le=1,
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


def validate_model_decision(model_decision: ModelDecision) -> AgentDecision:
    raw = model_decision.model_dump(by_alias=True, exclude_none=True)
    kind = raw.pop("commandType")
    rationale = raw.pop("rationale")
    command_types = {
        "MOVE_TO": MoveTo, "DRIBBLE": Dribble, "PASS": Pass, "SHOOT": Shoot,
        "PRESS_BALL": PressBall, "MARK": Mark, "INTERCEPT": Intercept,
        "SLIDE_TACKLE": SlideTackle, "CLEAR": Clear,
        "GK_DISTRIBUTE": GoalkeeperDistribute, "IDLE": Idle,
    }
    allowed_fields = {
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
    command_data = {"commandType":kind, **{key:value for key,value in raw.items()
                                             if key in allowed_fields[kind]}}
    return AgentDecision(command=command_types[kind].model_validate(command_data),
                         rationale=rationale)


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
