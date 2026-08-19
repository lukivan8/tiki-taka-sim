#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
sample_checkout=${SAMPLE_AGENTS_DIR:-"$repo_root/.cache/sample-ai-possibilities"}
sample_root="$sample_checkout/agentic-football-sample-agents"
sample_ref=${SAMPLE_AGENTS_REF:-cc2dbacf5fe3b5f6b3f640ebf0cd142f9603185a}
model_repo=${LOCAL_MODEL_REPO:-Qwen/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M}
decisions=${MATCH_DECISIONS:-10}
deadline_ms=${AGENT_DEADLINE_MS:-30000}
log_path="$repo_root/logs/local-model-vs-sample.ndjson"
metrics_path="$repo_root/logs/local-model-decisions.ndjson"
mkdir -p "$repo_root/logs"

command -v llama-server >/dev/null || {
  echo "llama-server is required (macOS: brew install llama.cpp)" >&2
  exit 1
}

if [[ -z ${SAMPLE_AGENTS_DIR:-} ]]; then
  if [[ ! -d "$sample_checkout/.git" ]]; then
    mkdir -p "$(dirname "$sample_checkout")"
    git init --quiet "$sample_checkout"
    git -C "$sample_checkout" remote add origin https://github.com/peterpanstechland/sample-ai-possibilities.git
  fi
  if [[ $(git -C "$sample_checkout" rev-parse HEAD 2>/dev/null || true) != "$sample_ref" ]]; then
    git -C "$sample_checkout" fetch --quiet --depth 1 origin "$sample_ref"
    git -C "$sample_checkout" checkout --quiet --detach FETCH_HEAD
  fi
fi

pids=()
cleanup() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT

llama-server -hf "$model_repo" --alias local-qwen-0.5b \
  --host 127.0.0.1 --port 8090 -c 8192 -np 5 -ngl 99 >"$repo_root/logs/llama-server.log" 2>&1 &
pids+=("$!")

echo "waiting for local model (first run downloads the GGUF)..."
for _ in {1..6000}; do
  if curl --silent --fail http://127.0.0.1:8090/health >/dev/null; then break; fi
  sleep 0.1
done
curl --silent --fail http://127.0.0.1:8090/health >/dev/null

python3 "$repo_root/tools/sample_agent_bridge.py" --sample-root "$sample_root" --port 8100 &
pids+=("$!")
python3 "$repo_root/tools/local_llm_agent.py" --port 8200 \
  --model local-qwen-0.5b --metrics "$metrics_path" &
pids+=("$!")

for port in 8100 8200; do
  for _ in {1..100}; do
    if curl --silent --fail "http://127.0.0.1:$port/health" >/dev/null; then break; fi
    sleep 0.1
  done
  curl --silent --fail "http://127.0.0.1:$port/health" >/dev/null
done

cargo run -q -p football-runner --bin football-match -- run \
  --agents "$repo_root/agents.local-model-vs-sample.yaml" \
  --log "$log_path" --decisions "$decisions" --deadline-ms "$deadline_ms"

python3 - "$log_path" "$metrics_path" <<'PY'
import collections, json, statistics, sys

match_rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
metrics = [json.loads(line) for line in open(sys.argv[2], encoding="utf-8")]
decisions = [row for row in match_rows if row["type"] == "decision"]
results = [r for row in decisions for r in row["agentResults"]]
home = [r for r in results if r["teamId"] == 0]
away = [r for r in results if r["teamId"] == 1]
ended = next(row for row in match_rows if row["type"] == "match_ended")
valid_model = sum(row["modelValid"] for row in metrics)
latencies = [row["latencyMs"] for row in metrics]
print(f"score: Qwen {ended['score']['home']}-{ended['score']['away']} sample ({ended['gameTime']:.0f}s)")
print(f"AFC responses: Qwen {sum(r['status'] == 'valid' for r in home)}/{len(home)}, "
      f"sample {sum(r['status'] == 'valid' for r in away)}/{len(away)}")
print(f"model JSON: {valid_model}/{len(metrics)} valid before bridge fallback")
print(f"model latency: median={statistics.median(latencies):.0f}ms "
      f"p95={sorted(latencies)[max(0, int(len(latencies) * .95) - 1)]:.0f}ms max={max(latencies):.0f}ms")
print("model actions:", dict(sorted(collections.Counter(row["action"] for row in metrics).items())))
print(f"replay: {sys.argv[1]}")
PY
