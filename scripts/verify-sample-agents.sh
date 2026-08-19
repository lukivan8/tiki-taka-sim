#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
sample_checkout=${SAMPLE_AGENTS_DIR:-"$repo_root/.cache/sample-ai-possibilities"}
sample_root="$sample_checkout/agentic-football-sample-agents"
log_path="$repo_root/logs/sample-agents.ndjson"
sample_ref=${SAMPLE_AGENTS_REF:-cc2dbacf5fe3b5f6b3f640ebf0cd142f9603185a}

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
elif [[ ! -d "$sample_checkout/.git" ]]; then
  echo "SAMPLE_AGENTS_DIR is not a Git checkout: $sample_checkout" >&2
  exit 1
fi
echo "sample agents commit: $(git -C "$sample_checkout" rev-parse HEAD)"

python3 "$repo_root/tools/sample_agent_bridge.py" --sample-root "$sample_root" --port 8100 &
bridge_pid=$!
cleanup() { kill "$bridge_pid" 2>/dev/null || true; }
trap cleanup EXIT

for _ in {1..50}; do
  if curl --silent --fail http://127.0.0.1:8100/health >/dev/null; then break; fi
  sleep 0.1
done
curl --silent --fail http://127.0.0.1:8100/health >/dev/null

cargo run -p football-runner --bin football-match -- run \
  --agents "$repo_root/agents.example.yaml" \
  --log "$log_path" \
  --decisions 6 \
  --deadline-ms 1000

python3 - "$log_path" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
decisions = [row for row in rows if row["type"] == "decision"]
assert len(decisions) == 6, len(decisions)
results = [result for row in decisions for result in row["agentResults"]]
assert len(results) == 60, len(results)
bad = [result for result in results if result["status"] != "valid"]
assert not bad, bad[:3]
commands = {result["wireCommand"]["commandType"] for result in results}
assert commands, commands
assert decisions[0]["worldBeforeHash"] != decisions[-1]["worldAfterHash"], "world did not advance"
applied = [event for row in decisions for event in row["events"] if event["type"] == "COMMAND_APPLIED"]
assert applied, "commands validated but none reached the world"
before = decisions[0]["worldBefore"]
after = decisions[-1]["worldAfter"]
assert before["players"] != after["players"] or before["ball"] != after["ball"], "physics state did not change"
print(f"verified: {len(results)} real sample fallback decisions; commands={sorted(commands)}")
print(f"world effects: {len(applied)} commands applied")
print(f"simulation log: {sys.argv[1]}")
PY
