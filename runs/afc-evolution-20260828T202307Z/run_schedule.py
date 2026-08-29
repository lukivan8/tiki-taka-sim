#!/usr/bin/env python3
"""Execute a campaign CSV schedule sequentially with durable per-match writes."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from campaign import run_match


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("schedule", type=Path)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    rows = list(csv.DictReader(args.schedule.open(encoding="utf-8")))
    for index, row in enumerate(rows, 1):
        record = run_match(row["home"], row["away"], int(row["seed"]), True, args.phase)
        print(json.dumps({
            "progress": f"{index}/{len(rows)}", "match_id": record["match_id"],
            "home": record["home_team"], "away": record["away_team"],
            "score": record["score"], "rated": record["rated"],
            "fallbacks": record["fallback_count"], "latency": record["latency_ms"],
            "replay": record["replay_path"],
        }), flush=True)


if __name__ == "__main__":
    main()
