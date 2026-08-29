#!/usr/bin/env python3
"""Run the fixed side-swapped workshop-baseline comparison and package replays."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

from live_match_server import ARENA_PATH, ROOT, LiveMatch
from workshop_baseline_adapter import UPSTREAM_COMMIT


BASELINES = (
    "workshop-balanced-baseline",
    "workshop-aggressive-baseline",
    "workshop-defensive-baseline",
)
OURS = ("release-deep-denial-g4", "simple-four-modes")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=120.0)
    args = parser.parse_args()
    source = args.source_root.resolve()
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != UPSTREAM_COMMIT:
        raise SystemExit(f"upstream commit must be {UPSTREAM_COMMIT}, got {commit}")
    os.environ["AFC_WORKSHOP_BASELINES_ROOT"] = str(source)

    output = args.output.resolve()
    audit_dir = output / "audit-replays"
    frame_dir = output / "visual-replays"
    audit_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)
    schedule = []
    seed = 24001
    for ours in OURS:
        for baseline in BASELINES:
            schedule.extend(((ours, baseline, seed), (baseline, ours, seed)))
            seed += 1

    results = []
    for index, (home, away, match_seed) in enumerate(schedule, 1):
        print(f"[{index:02d}/{len(schedule)}] {home} vs {away} seed={match_seed}", flush=True)
        match = LiveMatch(home, away, seed=match_seed, realtime=False,
                          duration_seconds=args.duration)
        match.start()
        match.thread.join()
        ended = next((row for row in reversed(match.messages)
                      if row.get("type") in {"match_ended", "match_failed"}), None)
        if not ended or ended.get("type") == "match_failed":
            raise RuntimeError(f"match failed: {home} vs {away}: {ended or match.error}")
        replay = ROOT / ended["replay"].lstrip("/")
        recording = ROOT / ended["recording"].lstrip("/")
        stem = f"{index:02d}-seed-{match_seed}-{home}-vs-{away}"
        audit = audit_dir / f"{stem}.ndjson"
        frames = frame_dir / f"{stem}.frames.ndjson"
        shutil.copy2(replay, audit)
        shutil.copy2(recording, frames)
        results.append({
            "index": index, "matchId": match.id, "home": home, "away": away,
            "seed": match_seed, "durationSeconds": args.duration,
            "score": {"home": ended["score"][0], "away": ended["score"][1]},
            "metrics": ended["metrics"],
            "auditReplay": str(audit.relative_to(output)), "auditSha256": sha256(audit),
            "visualReplay": str(frames.relative_to(output)), "visualSha256": sha256(frames),
        })
        (output / "manifest.json").write_text(json.dumps({"status": "running", "results": results}, indent=2) + "\n")

    provenance = {
        "schemaVersion": "afc-workshop-comparison/v1",
        "status": "complete",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "upstream": {
            "repository": "https://github.com/peterpanstechland/sample-ai-possibilities",
            "branch": "football-workshop", "commit": commit,
            "sourceSubdirectory": "agentic-football-sample-agents",
            "teams": list(BASELINES),
        },
        "arenaPath": str(ARENA_PATH.relative_to(ROOT)),
        "arenaSha256": sha256(ARENA_PATH),
        "arenaVersion": "nova-baseline-v2",
        "ourTeams": list(OURS),
        "schedule": "six paired matchups; same seed with home/away reversed",
        "commandCompatibility": {
            "FOLLOW_PLAYER": "MARK",
            "SET_STANCE/CLEAR_OVERRIDE/RESET": "upstream role fallback",
        },
        "results": results,
    }
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(provenance, indent=2) + "\n")
    archive = output / "workshop-comparison-replays.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(manifest, arcname="manifest.json")
        bundle.add(audit_dir, arcname="audit-replays")
        bundle.add(frame_dir, arcname="visual-replays")
    print(f"complete: {manifest}\narchive: {archive}", flush=True)


if __name__ == "__main__":
    main()
