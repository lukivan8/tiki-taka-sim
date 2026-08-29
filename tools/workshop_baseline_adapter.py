"""Run the upstream AFC workshop teams inside the frozen local Arena.

The adapter intentionally reuses the upstream prompts, per-role model choices,
fallbacks, scouting memory, tactical report, and optional aggressive overrides.
Only commands absent from nova-baseline-v2 are mapped to local equivalents.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


UPSTREAM_COMMIT = "cc2dbacf5fe3b5f6b3f640ebf0cd142f9603185a"
ROLE_DIRS = {0: "ai-gk", 1: "ai-def", 2: "ai-mid", 3: "ai-fwd1", 4: "ai-fwd2"}
LOCAL_COMMANDS = {
    "MOVE_TO", "PASS", "SHOOT", "SLIDE_TACKLE", "PRESS_BALL", "INTERCEPT",
    "MARK", "GK_DISTRIBUTE", "CLEAR",
}


@dataclass(frozen=True)
class InvocationResult:
    wire: dict[str, Any]
    source: str
    rationale: str | None = None
    latency_ms: float | None = None
    error: str | None = None
    model_prompt: str | None = None


@dataclass
class RoleRuntime:
    agent: Any
    position: str
    fallback: Any
    override: Any
    tracker: Any


def _source_root() -> Path:
    raw = os.environ.get("AFC_WORKSHOP_BASELINES_ROOT", "")
    if not raw:
        raise RuntimeError("AFC_WORKSHOP_BASELINES_ROOT must point to agentic-football-sample-agents")
    root = Path(raw).expanduser().resolve()
    required = root / "lib" / "agent_base.py"
    if not required.is_file():
        raise RuntimeError(f"invalid AFC_WORKSHOP_BASELINES_ROOT: missing {required}")
    return root


def _load_role(root: Path, upstream_team: str, player_id: int, instance: str) -> Any:
    source = root / upstream_team / ROLE_DIRS[player_id] / "src" / "main.py"
    if not source.is_file():
        raise RuntimeError(f"missing upstream role source: {source}")
    name = f"_afc_workshop_{upstream_team.replace('-', '_')}_{player_id}_{instance}"
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import upstream role: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class WorkshopBaselineTeam:
    def __init__(self, upstream_team: str):
        root = _source_root()
        lib = str(root / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        # These are the exact modules used by create_invoke_handler upstream.
        self._state = importlib.import_module("state")
        self._parsing = importlib.import_module("parsing")
        self._overrides = importlib.import_module("overrides")
        self._tactics = importlib.import_module("tactics")
        pattern_tracker = importlib.import_module("pattern_tracker")
        self.roles: dict[int, RoleRuntime] = {}
        instance = f"{id(self):x}"
        for player_id in range(5):
            module = _load_role(root, upstream_team, player_id, instance)
            self.roles[player_id] = RoleRuntime(
                agent=module.agent,
                position=module.POSITION_LABEL,
                fallback=module.fallback_commands,
                override=getattr(module, "OVERRIDE_CONFIG", None),
                tracker=pattern_tracker.PatternTracker(),
            )

    def _fallback(self, role: RoleRuntime, state: dict, team_id: int,
                  player_id: int) -> list[dict]:
        commands = role.fallback(state, team_id, player_id)
        commands, _ = self._overrides.apply_overrides(
            commands, state, team_id, player_id, role.position, role.override
        )
        return commands

    def _adapt(self, command: dict, role: RoleRuntime, state: dict,
               team_id: int, player_id: int) -> tuple[dict, str | None]:
        kind = command.get("commandType")
        if kind in LOCAL_COMMANDS:
            return command, None
        if kind == "FOLLOW_PLAYER":
            params = command.get("parameters") or {}
            mapped = dict(command)
            mapped["commandType"] = "MARK"
            mapped["parameters"] = {
                "target_player_id": params.get("target_player_id", 0),
                "tightness": "TIGHT" if float(params.get("distance", 4) or 4) <= 3 else "LOOSE",
            }
            return mapped, "FOLLOW_PLAYER->MARK"
        if kind in {"SET_STANCE", "CLEAR_OVERRIDE", "RESET"}:
            fallback = self._fallback(role, state, team_id, player_id)
            if fallback and fallback[0].get("commandType") in LOCAL_COMMANDS:
                return fallback[0], f"{kind}->upstream-role-fallback"
        return {
            "commandType": "MOVE_TO", "teamId": team_id, "playerId": player_id,
            "parameters": {"target_x": 0.0, "target_y": 0.0, "sprint": False},
            "duration": 0,
        }, f"{kind or 'missing'}->adapter-safe-center"

    def decide(self, payload: dict) -> InvocationResult:
        player_id = int(payload["myPlayers"][0])
        team_id = int(payload["teamId"])
        state = payload.get("gameState", {})
        role = self.roles[player_id]
        summary = self._state.summarize_state(state, team_id, player_id, role.position)
        role.tracker.update(state, team_id)
        scout = role.tracker.report(state, team_id, role.position)
        if scout:
            summary += f"\n\n{scout}"
        tactics = self._tactics.tactics_report(state, team_id, player_id, role.position)
        if tactics:
            summary += f"\n\n{tactics}"

        started = time.perf_counter()
        source = "upstream-llm"
        error = None
        try:
            if getattr(role.agent, "_session_manager", None) is None:
                role.agent.messages = []
            response = role.agent(summary)
            commands = self._parsing.parse_commands(str(response), team_id, player_id)
            if not commands:
                source = "upstream-parse-fallback"
                commands = self._fallback(role, state, team_id, player_id)
            else:
                commands, override = self._overrides.apply_overrides(
                    commands, state, team_id, player_id, role.position, role.override
                )
                if override:
                    source = f"upstream-llm+override:{override}"
        except Exception as caught:
            source = "upstream-error-fallback"
            error = f"{type(caught).__name__}: {caught}"
            commands = self._fallback(role, state, team_id, player_id)

        command = commands[0] if commands else {}
        command, mapping = self._adapt(command, role, state, team_id, player_id)
        command["teamId"] = team_id
        command["playerId"] = player_id
        rationale = None
        if mapping:
            source += "+local-adapter"
            rationale = f"Frozen-Arena compatibility mapping: {mapping}."
        return InvocationResult(
            wire=command,
            source=source,
            rationale=rationale,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            error=error,
            model_prompt=summary,
        )

