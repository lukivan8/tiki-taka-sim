"""Nova Micro + Strands runtime shared by five independently deployed players."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from .commands import AgentDecision, ModelDecision, idle_wire, to_wire, validate_model_decision
from .perception import build_perception, validate_semantics
from .prompting import build_observation, build_system_prompt


MODEL_ID = os.environ.get("AFC_MODEL_ID", "us.amazon.nova-micro-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_URL = os.environ.get("AFC_NOVA_GATEWAY_URL", "").rstrip("/")
GATEWAY_TOKEN = os.environ.get("AFC_GATEWAY_TOKEN", "")
GATEWAY_TIMEOUT_SECONDS = float(os.environ.get("AFC_GATEWAY_TIMEOUT_SECONDS", "90"))


@dataclass(frozen=True)
class InvocationResult:
    wire: dict
    source: str
    rationale: str
    latency_ms: int
    error: str | None = None
    model_prompt: str | None = None


class GatewayAgent:
    """Small HTTP client; prompts and football logic remain in the local clone."""

    afc_decision_source = "nova-gateway"

    def __init__(self, player_id: int, system_prompt: str):
        if not GATEWAY_TOKEN:
            raise RuntimeError("AFC_GATEWAY_TOKEN is required with AFC_NOVA_GATEWAY_URL")
        self.player_id = player_id
        self.afc_system_prompt = system_prompt

    def structured_output(self, output_model, observation: str):
        payload = json.dumps({
            "schemaVersion": "afc-nova-decision/v1",
            "playerId": self.player_id,
            "systemPrompt": self.afc_system_prompt,
            "observation": observation,
        }, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {
            "authorization": f"Bearer {GATEWAY_TOKEN}",
            "content-type": "application/json; charset=utf-8",
            "user-agent": "afc-nova-workshop/1.0",
        }
        client_id = os.environ.get("CF_ACCESS_CLIENT_ID")
        client_secret = os.environ.get("CF_ACCESS_CLIENT_SECRET")
        if client_id and client_secret:
            headers["CF-Access-Client-Id"] = client_id
            headers["CF-Access-Client-Secret"] = client_secret
        request = urllib.request.Request(GATEWAY_URL, payload, headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=GATEWAY_TIMEOUT_SECONDS) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"Nova gateway returned HTTP {error.code}: {detail}") from error
        return SimpleNamespace(structured_output=output_model.model_validate(body["decision"]))


def create_bedrock_agent(player_id: int, system_prompt: str | None = None):
    """Create a direct Nova agent. This path runs only on the credentialed server."""
    from strands import Agent
    from strands.models import BedrockModel

    prompt = system_prompt or build_system_prompt(player_id)
    model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION,
                         temperature=0.1, max_tokens=180)
    agent = Agent(model=model, system_prompt=prompt, callback_handler=None)
    agent.afc_decision_source = "nova-micro"
    agent.afc_system_prompt = prompt
    return agent


def create_agent(player_id: int):
    """Create a remote developer agent or a direct server-side Nova agent."""
    prompt = build_system_prompt(player_id)
    if GATEWAY_URL:
        return GatewayAgent(player_id, prompt)
    return create_bedrock_agent(player_id, prompt)


def invoke_agent(agent: Any, player_id: int, payload: dict) -> InvocationResult:
    prompt_data = json.loads(payload.get("prompt", "{}")) if isinstance(payload.get("prompt"), str) else payload["prompt"]
    team_id = int(prompt_data["teamId"])
    requested_players = [int(item) for item in prompt_data.get("myPlayers", [])]
    if requested_players != [player_id]:
        raise ValueError(f"player {player_id} received assignment {requested_players}")
    observation = build_observation(player_id, prompt_data)
    system_prompt = getattr(agent, "afc_system_prompt", "")
    perception = build_perception(prompt_data)
    started = time.perf_counter()
    current_observation = observation
    final_prompt = system_prompt + "\n\n## Текущее персональное наблюдение\n" + current_observation
    error: Exception | None = None
    for attempt in range(2):
        final_prompt = system_prompt + "\n\n## Текущее персональное наблюдение\n" + current_observation
        try:
            result = agent.structured_output(ModelDecision, current_observation)
            model_decision = getattr(result, "structured_output", result)
            if not isinstance(model_decision, ModelDecision):
                model_decision = ModelDecision.model_validate(model_decision)
            decision = validate_model_decision(model_decision)
            command_dump = decision.command.model_dump()
            validate_semantics(perception, command_dump["command_type"],
                               command_dump.get("target_player_id"),
                               command_dump.get("target_x"), command_dump.get("target_y"))
            wire = to_wire(decision, team_id, player_id)
            source = getattr(agent, "afc_decision_source", "model")
            return InvocationResult(wire, source, decision.rationale,
                                    round((time.perf_counter()-started)*1000),
                                    model_prompt=final_prompt)
        except (ValidationError, ValueError) as caught:
            error = caught
            if attempt == 0:
                current_observation = (observation + "\n\nПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: " +
                    str(caught).split("\n", 1)[0] +
                    ". Повтори выбор, используй только ДОСТУПНЫЕ КОМАНДЫ и заполни все обязательные параметры.")
                continue
        except Exception as caught:
            error = caught
        break
    return InvocationResult(idle_wire(team_id, player_id), "error-idle",
                            "Модель не вернула валидное решение вовремя.",
                            round((time.perf_counter()-started)*1000),
                            f"{type(error).__name__}: {error}", final_prompt)


def create_agentcore_app(player_id: int):
    """Create the exact Bedrock AgentCore entrypoint deployed for one player."""
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    app = BedrockAgentCoreApp()
    agent = create_agent(player_id)

    @app.entrypoint
    async def invoke(payload, context):
        result = invoke_agent(agent, player_id, payload)
        app.logger.info("DECISION " + json.dumps({
            "playerId": player_id, "source": result.source,
            "command": result.wire["commandType"], "latencyMs": result.latency_ms,
            "rationale": result.rationale, "error": result.error,
        }, ensure_ascii=False, separators=(",", ":")))
        yield json.dumps([result.wire], ensure_ascii=False, separators=(",", ":"))

    return app
