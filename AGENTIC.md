# Local Agentic Football arena

This fork keeps the original WebRTC browser game and adds a deterministic,
headless 5v5 runtime compatible with the public AWS Agentic Football workshop
examples.

## Verify the published sample agents

Requirements: Rust/Cargo, Python 3, Git, and curl. No AWS account or Python
packages are needed for this verification.

```bash
make verify-sample-agents
```

The command checks out the `football-workshop` branch of
`peterpanstechland/sample-ai-possibilities` under ignored `.cache/`, imports its
real `agentic-football-sample-agents/lib/fallback.py`, exposes the five position
policies through an AgentCore-shaped HTTP endpoint, and runs both teams for six
decision ticks. The assertion requires all 60 responses to validate and the
world state to advance. Its complete replay is written to
`logs/sample-agents.ndjson`.

The default verification ref is pinned to
`cc2dbacf5fe3b5f6b3f640ebf0cd142f9603185a`. Set `SAMPLE_AGENTS_REF` to test a
newer commit before updating the known-good ref.

To use an existing checkout instead of cloning:

```bash
SAMPLE_AGENTS_DIR=/absolute/path/to/sample-ai-possibilities \
  make verify-sample-agents
```

An explicitly supplied checkout is read as-is and is never fetched or switched
by the verification script.

This offline bridge tests the sample repository's rule-based fallback path.
The sample `main.py` LLM path still requires its documented Strands, AgentCore,
Bedrock model access, and AWS credentials. A deployed agent can be tested by
replacing the corresponding URL in `agents.example.yaml`; the simulator sends
the same `prompt.gameState`, `teamId`, and `myPlayers` shape.

## Run and inspect

Validate a ten-player config:

```bash
cargo run -p football-runner --bin football-match -- \
  validate-agents --agents agents.example.yaml
```

Run a full 120-second headless match against endpoints already listening at
the configured URLs:

```bash
cargo run -p football-runner --bin football-match -- run \
  --agents agents.example.yaml --log logs/match.ndjson
```

Serve the replay viewer and open `viewer/`:

```bash
python3 -m http.server 8080
```

Then visit `http://127.0.0.1:8080/viewer/` and choose an NDJSON log. Replays
show positions, score, clock, command type, validation state, and per-agent
latency without calling the agents again.

The generated sample replay can be opened directly at
`http://127.0.0.1:8080/viewer/?log=/logs/sample-agents.ndjson`.

## Runtime contract

- One immutable full-field snapshot is serialized for all ten agents every two seconds.
- All HTTP calls start concurrently with a configurable 1000 ms default deadline.
- Malformed, failed, or late responses become `IDLE`; there are no in-match retries.
- Commands are normalized to the configured `(teamId, playerId)` and applied as one batch.
- Physics advances at 60 fixed steps per second and logs every decision as NDJSON.
- Supported workshop commands include `MOVE_TO`, `PASS`, `SHOOT`, `PRESS_BALL`,
  `MARK`, `INTERCEPT`, `SLIDE_TACKLE`, `FOLLOW_PLAYER`, `GK_DISTRIBUTE`,
  `SET_STANCE`, `CLEAR_OVERRIDE`, and `RESET`; `DRIBBLE`, `CLEAR`, `TACKLE`, and
  `IDLE` cover the broader published command vocabulary.

The public tournament server is not open source, so compatibility is tested
against the published community sample repository rather than claimed as an
identity with the private tournament physics.

## Play with a tiny local model

On macOS, install llama.cpp once and run a short Qwen 0.5B exhibition against
the published sample fallback team:

```bash
brew install llama.cpp
make play-local-model
```

The first run downloads the official `Qwen2.5-0.5B-Instruct-GGUF` Q4_K_M file.
Five concurrent local-model players use the same AFC `/invocations` contract;
the other five use the real sample policies. The match replay is saved as
`logs/local-model-vs-sample.ndjson`, while `logs/local-model-decisions.ndjson`
records raw model output, generation latency, and whether the model produced a
usable command before the bridge's safe `IDLE` fallback.

Tune a run without editing files:

```bash
MATCH_DECISIONS=30 AGENT_DEADLINE_MS=30000 make play-local-model
```
