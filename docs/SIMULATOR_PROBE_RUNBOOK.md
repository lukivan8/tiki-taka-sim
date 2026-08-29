# Simulator Probe Runbook

Budget: 30 minutes. The custom probe is deterministic and makes no LLM calls. Its opponent is the built-in sample team.

## Temporary workshop AWS CLI credentials

Never paste workshop credentials into repository files, command arguments, `.env`, or an AWS profile. Enter them without shell echo, verify the temporary role, and clear them when finished:

```bash
read -rp "AWS region [us-east-1]: " AWS_DEFAULT_REGION
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
read -rp "AWS access key ID: " AWS_ACCESS_KEY_ID
read -rsp "AWS secret access key: " AWS_SECRET_ACCESS_KEY; echo
read -rsp "AWS session token: " AWS_SESSION_TOKEN; echo
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws sts get-caller-identity

# Run workshop AWS CLI commands in this same shell, then clear credentials:
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION AWS_REGION
```

1. From the repository root, verify `arena/arena.yaml` is the intended simulator and start/connect to AFC. Run the local reference command exactly as shown (normally already done):

   ```bash
   PYTHONPATH=tools .venv-afc/bin/python - <<'PY'
   from pathlib import Path
   import shutil
   from live_match_server import LiveMatch, ROOT
   match = LiveMatch("simulator-probe", "nova-baseline", seed=260829, realtime=False, duration_seconds=120.0)
   match.start(); match.thread.join()
   ended = next(x for x in reversed(match.messages) if x["type"] == "match_ended")
   target = Path("probe-reference/local-probe-replay.ndjson")
   target.parent.mkdir(parents=True, exist_ok=True)
   shutil.copy2(ROOT / ended["replay"].lstrip("/"), target)
   print(target, ROOT / ended["recording"].lstrip("/"))
   PY
   ```

2. Tournament adapter: register five player endpoints which call `teams/simulator-probe/live_team.py:create_team().decide(payload)`, then start a 120-second match with **simulator-probe as HOME** against the built-in sample team. Use seed `260829` if AFC exposes seeds. No model credentials are needed for the probe. Use the AFC portal/API’s normal registration command; that external command is not present in this repository.
3. Save the authoritative tournament replay as `probe-reference/tournament-probe-replay.ndjson`. Also save its recording if AFC provides one.
4. Confirm the replay contains `decisionSource` values beginning `probe:` and rationales beginning `PROBE`; decisions 0–5 are movement, 6–23 passing/recovery, 24–35 pressure/reach, and 36–59 shooting/recovery. The sample opponent is uncontrolled: naturally occupied passing lanes and keeper positions are evidence, not prescribed geometry.
5. Attach `probe-reference/local-probe-replay.ndjson`, the tournament replay, `teams/simulator-probe/live_team.py`, and current perception source/configuration to a fresh Codex task.
6. Paste `docs/COMPARE_PROBE_REPLAYS_PROMPT.md`.
7. Apply only the resulting perception calibration, then run one smoke match with the selected real team.

If the probe cannot be HOME, still run it AWAY. Retain movement, bounds, orientation, timing, and any successfully executed ball actions. Mark missed possession-dependent phases `UNRESOLVED`; never restart repeatedly to force a desired interaction.
