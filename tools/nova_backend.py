"""Server-owned Nova Micro backend and fixed AFC decision contract."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MODEL_ID = "us.amazon.nova-micro-v1:0"
AWS_REGION = "us-east-1"


class ModelDecision(BaseModel):
    """Flat structured output shared by every team using the gateway."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    command_type: Literal[
        "MOVE_TO", "DRIBBLE", "PASS", "SHOOT", "PRESS_BALL", "MARK",
        "INTERCEPT", "SLIDE_TACKLE", "CLEAR", "GK_DISTRIBUTE", "IDLE",
    ] = Field(alias="commandType")
    target_x: float | None = Field(default=None, ge=-55, le=55)
    target_y: float | None = Field(default=None, ge=-35, le=35)
    sprint: bool | None = None
    target_player_id: int | None = Field(default=None, ge=0, le=4)
    pass_type: Literal["GROUND", "AERIAL", "THROUGH", "NORMAL"] | None = Field(
        default=None, alias="type"
    )
    aim_location: Literal["TL", "TR", "BL", "BR", "CENTER"] | None = None
    power: float | None = Field(default=None, ge=0, le=1)
    intensity: float | None = Field(default=None, ge=0, le=1)
    tightness: Literal["LOOSE", "TIGHT"] | None = None
    aggressive: bool | None = None
    distance: float | None = Field(default=None, ge=0, le=8)
    method: Literal["THROW", "KICK"] | None = None
    rationale: str = Field(min_length=1, max_length=180)


def create_bedrock_agent(system_prompt: str):
    """Create the one server-side model; clients cannot override its identity."""
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.1,
        max_tokens=180,
    )
    return Agent(model=model, system_prompt=system_prompt, callback_handler=None)
