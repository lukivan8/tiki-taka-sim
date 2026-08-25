#!/usr/bin/env python3
"""Authenticated, quota-limited Nova inference for remote developer clones."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


from nova_backend import MODEL_ID, ModelDecision, create_bedrock_agent


ROOT = Path(__file__).resolve().parents[1]


MAX_BODY_BYTES = 64 * 1024
MAX_SYSTEM_PROMPT_CHARS = 32_000
MAX_OBSERVATION_CHARS = 32_000


class GatewayError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Identity:
    name: str
    token_digest: str
    daily_limit: int
    requests_per_minute: int
    max_concurrent: int


class GatewayAccess:
    """Token authentication plus persistent daily and in-memory burst limits."""

    def __init__(self, token_file: Path, database_path: Path,
                 inline_token: str | None = None):
        self.token_file = token_file
        self.database_path = database_path
        self.inline_token = inline_token
        self.lock = threading.Lock()
        self.request_times: dict[str, deque[float]] = defaultdict(deque)
        self.active: dict[str, int] = defaultdict(int)
        self._identities: tuple[tuple[str, Identity], ...] = ()
        self._token_mtime_ns = -1
        self._initialize_database()
        self._reload_tokens()

    @classmethod
    def from_environment(cls) -> "GatewayAccess":
        token_file = Path(os.environ.get(
            "AFC_GATEWAY_TOKENS_FILE",
            str(Path.home() / ".config/tiki-taka-sim/gateway-tokens.json"),
        ))
        database_path = Path(os.environ.get(
            "AFC_GATEWAY_USAGE_DB", str(ROOT / "var/gateway-usage.sqlite3")
        ))
        inline_token = None
        if os.environ.get("AFC_NOVA_GATEWAY_URL"):
            inline_token = os.environ.get("AFC_GATEWAY_TOKEN")
        return cls(token_file, database_path, inline_token)

    def _initialize_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS daily_usage ("
                "identity TEXT NOT NULL, day TEXT NOT NULL, calls INTEGER NOT NULL, "
                "PRIMARY KEY(identity, day))"
            )
        os.chmod(self.database_path, 0o600)

    def _reload_tokens(self) -> None:
        loaded = []
        if self.inline_token:
            digest = hashlib.sha256(self.inline_token.encode()).hexdigest()
            loaded.append((self.inline_token, Identity(
                name="local-developer",
                token_digest=digest,
                daily_limit=1_000_000,
                requests_per_minute=1_000,
                max_concurrent=20,
            )))
        try:
            stat = self.token_file.stat()
        except FileNotFoundError:
            self._identities = tuple(loaded)
            self._token_mtime_ns = -1
            return
        if stat.st_mtime_ns == self._token_mtime_ns:
            return
        data = json.loads(self.token_file.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != "afc-gateway-tokens/v1":
            raise RuntimeError("gateway token file has an unsupported schemaVersion")
        for entry in data.get("tokens", []):
            name = str(entry["name"])
            token = str(entry["token"])
            if len(token) < 32:
                raise RuntimeError(f"gateway token for {name!r} is too short")
            digest = hashlib.sha256(token.encode()).hexdigest()
            loaded.append((token, Identity(
                name=name,
                token_digest=digest,
                daily_limit=int(entry.get("dailyCallLimit", 3000)),
                requests_per_minute=int(entry.get("requestsPerMinute", 600)),
                max_concurrent=int(entry.get("maxConcurrent", 10)),
            )))
        self._identities = tuple(loaded)
        self._token_mtime_ns = stat.st_mtime_ns

    def authenticate(self, authorization: str | None) -> Identity:
        self._reload_tokens()
        if not self._identities:
            raise GatewayError(503, "Nova gateway has no configured invite tokens")
        if not authorization or not authorization.startswith("Bearer "):
            raise GatewayError(401, "AFC invite token required")
        supplied = authorization[7:]
        for token, identity in self._identities:
            if hmac.compare_digest(supplied, token):
                return identity
        raise GatewayError(401, "invalid AFC invite token")

    def _charge_daily(self, identity: Identity, units: int) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        with sqlite3.connect(self.database_path) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT calls FROM daily_usage WHERE identity=? AND day=?",
                (identity.token_digest, day),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used + units > identity.daily_limit:
                raise GatewayError(429, "daily Nova call quota exhausted")
            updated = used + units
            database.execute(
                "INSERT INTO daily_usage(identity, day, calls) VALUES(?,?,?) "
                "ON CONFLICT(identity, day) DO UPDATE SET calls=excluded.calls",
                (identity.token_digest, day, updated),
            )
            return identity.daily_limit - updated

    def reserve_match(self, identity: Identity, expected_calls: int) -> int:
        with self.lock:
            return self._charge_daily(identity, expected_calls)

    @contextlib.contextmanager
    def inference_slot(self, identity: Identity) -> Iterator[int]:
        now = time.monotonic()
        with self.lock:
            recent = self.request_times[identity.token_digest]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= identity.requests_per_minute:
                raise GatewayError(429, "Nova gateway requests-per-minute limit reached")
            if self.active[identity.token_digest] >= identity.max_concurrent:
                raise GatewayError(429, "Nova gateway concurrency limit reached")
            remaining = self._charge_daily(identity, 1)
            recent.append(now)
            self.active[identity.token_digest] += 1
        try:
            yield remaining
        finally:
            with self.lock:
                self.active[identity.token_digest] = max(
                    0, self.active[identity.token_digest] - 1
                )


def validate_inference_payload(payload: dict[str, Any]) -> tuple[int, str, str]:
    if set(payload) != {"schemaVersion", "playerId", "systemPrompt", "observation"}:
        raise GatewayError(400, "inference request contains unknown or missing fields")
    if payload["schemaVersion"] != "afc-nova-decision/v1":
        raise GatewayError(400, "unsupported inference schemaVersion")
    player_id = int(payload["playerId"])
    if player_id not in range(5):
        raise GatewayError(400, "playerId must be between 0 and 4")
    system_prompt = str(payload["systemPrompt"])
    observation = str(payload["observation"])
    if not system_prompt or len(system_prompt) > MAX_SYSTEM_PROMPT_CHARS:
        raise GatewayError(400, "systemPrompt is empty or too large")
    if not observation or len(observation) > MAX_OBSERVATION_CHARS:
        raise GatewayError(400, "observation is empty or too large")
    return player_id, system_prompt, observation


def invoke_fixed_nova(player_id: int, system_prompt: str, observation: str) -> ModelDecision:
    """Invoke the only server-side model. Client requests cannot select a model."""
    agent = create_bedrock_agent(system_prompt)
    result = agent.structured_output(ModelDecision, observation)
    decision = getattr(result, "structured_output", result)
    return decision if isinstance(decision, ModelDecision) else ModelDecision.model_validate(decision)


class NovaGateway:
    def __init__(self, access: GatewayAccess):
        self.access = access

    def authenticate(self, authorization: str | None) -> Identity:
        return self.access.authenticate(authorization)

    def infer(self, authorization: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        identity = self.authenticate(authorization)
        player_id, system_prompt, observation = validate_inference_payload(payload)
        started = time.perf_counter()
        with self.access.inference_slot(identity) as remaining:
            decision = invoke_fixed_nova(player_id, system_prompt, observation)
        return {
            "schemaVersion": "afc-nova-decision/v1",
            "decision": decision.model_dump(by_alias=True),
            "model": MODEL_ID,
            "latencyMs": round((time.perf_counter() - started) * 1000, 3),
            "callsRemainingToday": remaining,
        }
