# Tiki-Taka Sim

Local, deterministic 5v5 football arena for testing HTTP and LLM agents against
the public Agentic Football workshop contract.

The project turns the browser game
[`wasm-peers/footballers`](https://github.com/wasm-peers/footballers) into a
developer-oriented training environment with a headless Rust simulation,
parallel agent orchestration, structured commands, NDJSON replays, adapters for
the public workshop examples, and a tiny local-model opponent.

> This is an independent compatibility project. It is not an official AWS
> tournament server and does not claim physics-level parity with the private
> competition runtime.

## What works

- deterministic 5v5 world with a fixed 60 Hz physics step;
- one immutable world snapshot for all ten players every two simulated seconds;
- ten concurrent HTTP requests followed by simultaneous command application;
- AgentCore-shaped `POST /invocations` request and response envelopes;
- timeout, HTTP failure, and schema failure fallback to `IDLE`;
- full NDJSON transition logs and browser replay without calling agents again;
- direct execution of the real rule-based policies from the public sample repo;
- five local Qwen 0.5B players versus five public sample players;
- preserved upstream WebRTC/WASM browser game.

The reference checks currently cover five Rust tests and a 60-response
integration run against the sample agents. A local 120-second Qwen exhibition
also completed with all 600 HTTP responses valid.

## Runtime model

```text
World snapshot S(t)
        |
        +--> home P0 HTTP request --+
        +--> home P1 HTTP request --+
        +--> ...                    +--> validate all responses
        +--> away P4 HTTP request --+        |
                                              v
                                  simultaneous command batch A(t)
                                              |
                                              v
                                  120 fixed physics steps
                                              |
                                              v
                                  World snapshot S(t + 2s)
                                              |
                                              v
                                          NDJSON log
```

The decision phase never exposes another player's current decision. Slow or
invalid agents cannot block the match indefinitely: the runner applies the
configured common deadline and substitutes `IDLE`.

## Repository layout

```text
crates/
  football-protocol/  AFC payloads, wire commands, parsing and validation
  football-core/      deterministic world, command effects and fixed-step physics
  football-runner/    concurrent HTTP orchestrator and NDJSON match logger
tools/
  sample_agent_bridge.py  adapter for the published fallback.py policies
  local_llm_agent.py      llama.cpp/OpenAI API to AFC bridge
scripts/
  verify-sample-agents.sh reproducible public-sample compatibility check
  play-local-model.sh     Qwen 0.5B versus sample team launcher
viewer/                   dependency-free NDJSON replay viewer
src/                      original Yew/WebRTC footballers browser game
agents.example.yaml       ten public-sample endpoint bindings
agents.local-model-vs-sample.yaml
AGENTIC.md                lower-level commands and runtime notes
```

## Requirements

Base simulator and sample verification:

- Rust and Cargo;
- Python 3.10 or newer;
- Git;
- `curl`.

Local-model match additionally requires
[`llama-server`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
On macOS:

```bash
brew install llama.cpp
```

No Python packages, AWS account, AWS credentials, or model API key are required
for the local workflows.

## Quick start

Run unit tests and static checks:

```bash
make check
```

Verify the public workshop sample agents:

```bash
make verify-sample-agents
```

This command checks out the pinned `football-workshop` sample revision into the
ignored `.cache/` directory, imports its real `lib/fallback.py`, starts an HTTP
bridge, and runs both five-player teams for six decision ticks. The test fails
unless all 60 responses validate and commands visibly affect the world.

Run a small local model against the sample team:

```bash
make play-local-model
```

The first run downloads the official Q4_K_M quantization of
[`Qwen2.5-0.5B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF).
The model is cached outside this repository. The launcher starts five concurrent
model slots, both bridges, a short match, prints latency and validity metrics,
and then stops its child processes.

Run the full 120-second simulation:

```bash
MATCH_DECISIONS=60 AGENT_DEADLINE_MS=30000 make play-local-model
```

Useful overrides:

```bash
LOCAL_MODEL_REPO='Qwen/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M' \
MATCH_DECISIONS=30 \
AGENT_DEADLINE_MS=30000 \
make play-local-model
```

## Inspect a replay

Start a static server from the repository root:

```bash
python3 -m http.server 8080
```

Then open:

```text
http://127.0.0.1:8080/viewer/?log=/logs/local-model-vs-sample.ndjson
```

Generated logs live under ignored `logs/`:

- `local-model-vs-sample.ndjson` contains complete match transitions;
- `local-model-decisions.ndjson` contains raw model output, latency, and bridge
  fallback status;
- `sample-agents.ndjson` contains the public-sample compatibility replay.

The viewer shows positions, score, clock, normalized commands, validation state,
and latency for each player.

## Agent HTTP contract

Each binding in an agents YAML file identifies exactly one `(teamId, playerId)`
pair. The runner posts an AgentCore-compatible envelope:

```json
{
  "prompt": "{\"gameState\":{...},\"teamId\":0,\"myPlayers\":[3]}"
}
```

An agent returns either a command array or the JSON-string envelope used by the
public samples:

```json
[
  {
    "commandType": "MOVE_TO",
    "playerId": 3,
    "teamId": 0,
    "parameters": {
      "target_x": 24.0,
      "target_y": -8.0,
      "sprint": true
    },
    "duration": 0
  }
]
```

Supported commands include `MOVE_TO`, `DRIBBLE`, `PASS`, `SHOOT`, `PRESS_BALL`,
`MARK`, `FOLLOW_PLAYER`, `INTERCEPT`, `SLIDE_TACKLE`, `TACKLE`, `CLEAR`,
`GK_DISTRIBUTE`, `SET_STANCE`, `CLEAR_OVERRIDE`, `RESET`, and `IDLE`.

The runner binds identity from YAML rather than trusting `teamId` or `playerId`
returned by an endpoint. Exactly one command is accepted per player and decision
tick.

## Running custom agents

Copy `agents.example.yaml`, change one or more endpoint URLs, and validate the
complete ten-player mapping:

```bash
cargo run -p football-runner --bin football-match -- \
  validate-agents --agents agents.custom.yaml
```

Run a match:

```bash
cargo run -p football-runner --bin football-match -- run \
  --agents agents.custom.yaml \
  --log logs/custom-match.ndjson \
  --seed 42 \
  --decisions 60 \
  --deadline-ms 30000
```

For deterministic comparisons, keep the seed, agents, decision count, and
endpoint implementations fixed. Each log includes hashes of the world before
and after every decision.

## Local model bridge

`tools/local_llm_agent.py` converts the full workshop observation into a compact
player-relative prompt and calls llama.cpp's OpenAI-compatible
`/v1/chat/completions` endpoint. A strict JSON Schema constrains the output to a
small object. The bridge then emits a workshop-shaped command.

There are two validation layers:

1. the bridge records whether the model itself produced usable JSON;
2. the Rust runner independently validates the AFC response.

If generation fails, the bridge emits `IDLE` and records the original exception.
This distinction prevents a protocol-valid fallback from being mistaken for a
capable model decision.

## Original browser game

The upstream Yew application remains available. It uses `wasm-peers` WebRTC
DataChannels with a host-authoritative browser state. To run it, install
[`trunk`](https://trunkrs.dev/) and start the wasm-peers signaling server, then:

```bash
SIGNALING_SERVER_URL='ws://127.0.0.1:9001' trunk serve
```

The headless Rust world is intentionally separate from this browser/WebRTC
runtime. The replay viewer reads the new headless logs and does not require the
signaling server.

## Design boundaries and known limitations

- The public tournament server and its exact physics are not available here.
- Compatibility is based on the public sample payloads and fallback policies.
- The headless physics prioritize determinism and experimentation over realistic
  football simulation.
- There is currently no offside, foul, card, substitution, or set-piece model.
- `possessionAgentId` follows the public sample's team-local agent naming, so
  consumers must combine it with team context.
- The replay is sufficient for visualization and analysis, but snapshot loading
  and arbitrary scenario parameter sweeps remain future work.
- Tiny models can be protocol-reliable while making very poor tactical choices;
  model JSON validity and football quality must be evaluated separately.

## Sources and attribution

The implementation and documentation were informed by these primary sources:

- [AWS Agentic Football Cup event description](https://aws.amazon.com/startups/events/agentic-football-cup-kuala-lumpur-build-ai-agents-that-play-football),
  which describes five autonomous agents per team making decisions every two
  seconds;
- [`peterpanstechland/sample-ai-possibilities`, `football-workshop` branch](https://github.com/peterpanstechland/sample-ai-possibilities/tree/football-workshop/agentic-football-sample-agents),
  used as the executable reference for request shapes, command vocabulary, and
  the rule-based fallback policies;
- [`wasm-peers/footballers`](https://github.com/wasm-peers/footballers), the
  original browser game and Git history retained by this repository;
- [`wasm-peers/wasm-peers`](https://github.com/wasm-peers/wasm-peers), the
  WebRTC DataChannel library used by the original browser game;
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md),
  used for local OpenAI-compatible inference and constrained JSON;
- [official Qwen2.5 0.5B Instruct GGUF repository](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF),
  used for the small local-model demonstration.

The sample repository is downloaded only for local verification and is not
vendored. Model weights, generated logs, build outputs, and caches are excluded
from Git.

## Security and reproducibility

- Agent URLs are explicit local configuration; never place credentials in YAML.
- The runner logs raw agent responses, so treat logs as sensitive when testing
  proprietary prompts or services.
- No generated model weight or Hugging Face cache is committed.
- The public sample verification defaults to pinned commit
  `cc2dbacf5fe3b5f6b3f640ebf0cd142f9603185a`. Override `SAMPLE_AGENTS_REF` only
  when intentionally testing a newer revision.

## License

The original `footballers` code and this derived work are dual-licensed under
Apache-2.0 or MIT. See [LICENSE-APACHE](LICENSE-APACHE) and
[LICENSE-MIT](LICENSE-MIT). Original authorship and history are preserved in Git.

External projects and model weights retain their own licenses; consult their
linked repositories before redistribution.
