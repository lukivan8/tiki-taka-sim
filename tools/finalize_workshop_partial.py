#!/usr/bin/env python3
"""Seal an intentionally stopped workshop comparison and curate useful replays."""
from __future__ import annotations

import collections
import json
import math
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs/workshop-baseline-comparison-20260829"
SELECTED = (4, 5, 7)


def analyze(path: Path) -> dict:
    shots = {0: [], 1: []}
    sources = collections.Counter()
    errors = collections.Counter()
    for row in map(json.loads, path.open(encoding="utf-8")):
        if row.get("type") != "decision":
            continue
        players = row["worldBefore"]["players"]
        for result in row["agentResults"]:
            sources[f"{result['teamId']}:{result['decisionSource']}"] += 1
            if result.get("error"):
                errors[f"{result['teamId']}:{result['error']}"] += 1
        for event in row.get("events", []):
            if event.get("type") != "BALL_KICKED" or event.get("kind") != "SHOOT":
                continue
            team_id = event["player"]["team_id"]
            player_id = event["player"]["player_id"]
            code = "home" if team_id == 0 else "away"
            player = next(p for p in players if p["teamCode"] == code and
                          int(p["agentId"].rsplit("_", 1)[1]) == player_id)
            position = player["position"]
            goal_x = 55.0 if team_id == 0 else -55.0
            shots[team_id].append(round(math.hypot(position["x"] - goal_x,
                                                   position["y"]), 1))
    return {
        "appliedShots": {"home": len(shots[0]), "away": len(shots[1])},
        "shotDistancesMetres": {"home": shots[0], "away": shots[1]},
        "decisionSources": dict(sources),
        "decisionErrors": dict(errors),
        "operationallyClean": not errors,
    }


def main() -> None:
    manifest_path = RUN / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = manifest["results"]
    for result in results:
        result["replayAudit"] = analyze(RUN / result["auditReplay"])
    manifest.update({
        "schemaVersion": "afc-workshop-comparison/v1",
        "status": "user-stopped-partial",
        "completedMatches": len(results),
        "plannedMatches": 12,
        "selection": {
            "indexes": list(SELECTED),
            "reason": "clean aggressive behavior, only goal, and strongest close-range creation",
            "warning": "match 5 is operationally impaired by rejected upstream MOVE_TO commands",
        },
    })
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    all_archive = RUN / "completed-seven-replays.tar.gz"
    with tarfile.open(all_archive, "w:gz") as bundle:
        bundle.add(manifest_path, arcname="manifest.json")
        bundle.add(RUN / "audit-replays", arcname="audit-replays")
        bundle.add(RUN / "visual-replays", arcname="visual-replays")
    selected_archive = RUN / "valuable-three-replays.tar.gz"
    with tarfile.open(selected_archive, "w:gz") as bundle:
        bundle.add(manifest_path, arcname="manifest.json")
        for result in results:
            if result["index"] in SELECTED:
                bundle.add(RUN / result["auditReplay"], arcname=result["auditReplay"])
                bundle.add(RUN / result["visualReplay"], arcname=result["visualReplay"])
    print(manifest_path)
    print(all_archive)
    print(selected_archive)


if __name__ == "__main__":
    main()
