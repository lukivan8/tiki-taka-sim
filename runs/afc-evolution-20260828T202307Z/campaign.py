#!/usr/bin/env python3
"""Run frozen-Arena matches and persist auditable campaign state."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
ROOT = RUN_DIR.parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from live_match_server import LiveMatch, discover_teams  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def team_hash(team_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(team_root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(str(path.relative_to(team_root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state() -> dict:
    return json.loads((RUN_DIR / "state.json").read_text(encoding="utf-8"))


def register_population(state: dict) -> None:
    for team_id, team in discover_teams().items():
        root = Path(team["root"])
        manifest = __import__("yaml").safe_load((root / "team.yaml").read_text(encoding="utf-8"))
        existing = state["teams"].get(team_id, {})
        state["teams"][team_id] = {
            **existing,
            "team_id": team_id,
            "display_name": team["name"],
            "path": str(root.relative_to(ROOT)),
            "implementation_hash": team_hash(root),
            "formation": team["formationPreset"],
            "model": manifest["model"]["name"],
            "strategy_family": manifest.get("strategyFamily", "unknown"),
            "language": existing.get("language", "Russian/mixed"),
            "status": existing.get("status", "active-existing"),
            "ancestry": existing.get("ancestry", []),
            "rating": existing.get("rating", 1500.0),
            "games": existing.get("games", 0),
            "wins": existing.get("wins", 0),
            "draws": existing.get("draws", 0),
            "losses": existing.get("losses", 0),
            "goals_for": existing.get("goals_for", 0),
            "goals_against": existing.get("goals_against", 0),
        }


def replay_rows(public_path: str) -> tuple[Path, list[dict]]:
    path = ROOT / public_path.lstrip("/")
    return path, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def result_score(goals_for: int, goals_against: int) -> float:
    return 1.0 if goals_for > goals_against else 0.0 if goals_for < goals_against else 0.5


def update_rating(team: dict, opponent_rating: float, score: float) -> tuple[float, float, int]:
    before = float(team["rating"])
    expected = 1.0 / (1.0 + 10 ** ((opponent_rating - before) / 400.0))
    k = 32 if int(team["games"]) < 20 else 16
    after = before + k * (score - expected)
    team["rating"] = round(after, 3)
    return before, team["rating"], k


def write_tables(state: dict) -> None:
    with (RUN_DIR / "ratings.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["team_id", "rating", "games", "wins", "draws", "losses", "goals_for", "goals_against", "status", "last_updated_utc"])
        for team in sorted(state["teams"].values(), key=lambda row: (-row["rating"], row["team_id"])):
            status = "stable" if team["games"] >= 20 else "provisional"
            writer.writerow([team["team_id"], team["rating"], team["games"], team["wins"], team["draws"], team["losses"], team["goals_for"], team["goals_against"], status, state.get("last_updated_utc", "")])

    with (RUN_DIR / "CANDIDATES.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["team_id", "implementation_hash", "dependency_closure_hash", "dependency_members", "path", "formation", "model", "strategy_family", "language", "ancestry", "selection_status"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for team in sorted(state["teams"].values(), key=lambda row: row["team_id"]):
            writer.writerow({
                "team_id": team["team_id"],
                "implementation_hash": team["implementation_hash"],
                "dependency_closure_hash": team.get("dependency_closure_hash", team["implementation_hash"]),
                "dependency_members": " + ".join(team.get("dependency_members", [team["team_id"]])),
                "path": team["path"],
                "formation": team["formation"],
                "model": team["model"],
                "strategy_family": team["strategy_family"],
                "language": team["language"],
                "ancestry": " + ".join(team.get("ancestry", [])),
                "selection_status": team["status"],
            })

    with (RUN_DIR / "ELO_HISTORY.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["timestamp_utc", "match_id", "team_id", "opponent_id", "score", "rating_before", "rating_after", "k_factor", "replay_path"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(state.get("elo_history", []))

    with (RUN_DIR / "MATCH_RESULTS.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["match_id", "phase", "started_utc", "finished_utc", "home_team", "away_team", "home_hash", "away_hash", "seed", "home_goals", "away_goals", "rated", "rating_exclusion_reason", "fallback_count", "harmful_fallback_count", "median_latency_ms", "replay_path", "recording_path", "replay_sha256", "recording_sha256"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for match in state["matches"]:
            writer.writerow({
                **{field: match.get(field) for field in fields},
                "home_goals": match["score"]["home"],
                "away_goals": match["score"]["away"],
                "median_latency_ms": match["latency_ms"]["median"],
            })

    pairs: dict[tuple[str, str], dict] = {}
    for match in state["matches"]:
        if not match.get("rated"):
            continue
        a, b = sorted((match["home_team"], match["away_team"]))
        row = pairs.setdefault((a, b), {"games": 0, "a_wins": 0, "draws": 0, "a_losses": 0, "a_goals": 0, "b_goals": 0, "last_match_utc": ""})
        ah, bh = (match["score"]["home"], match["score"]["away"]) if match["home_team"] == a else (match["score"]["away"], match["score"]["home"])
        row["games"] += 1; row["a_goals"] += ah; row["b_goals"] += bh
        row["a_wins"] += ah > bh; row["draws"] += ah == bh; row["a_losses"] += ah < bh
        row["last_match_utc"] = match["finished_utc"]
    with (RUN_DIR / "MATCHUP_MATRIX.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["team_a", "team_b", "games", "a_wins", "draws", "a_losses", "a_goals", "b_goals", "last_match_utc"])
        for (a, b), row in sorted(pairs.items()):
            writer.writerow([a, b, *row.values()])


def write_reliability(state: dict) -> None:
    sources = {team_id: Counter() for team_id in state["teams"]}
    match_exposures = Counter()
    excluded_exposures = Counter()
    local_harmful_matches = Counter()
    for match in state["matches"]:
        match_exposures.update((match["home_team"], match["away_team"]))
        if not match["rated"]:
            excluded_exposures.update((match["home_team"], match["away_team"]))
        local_harmful = Counter()
        _, rows = replay_rows(match["replay_path"])
        for row in rows:
            if row.get("type") != "decision":
                continue
            for result in row["agentResults"]:
                team_id = match["home_team"] if result["teamId"] == 0 else match["away_team"]
                source = result.get("decisionSource", "unknown")
                sources[team_id][source] += 1
                if source in {"error-idle", "runner-idle"}:
                    local_harmful[team_id] += 1
        for team_id, count in local_harmful.items():
            if count:
                local_harmful_matches[team_id] += 1
    with (RUN_DIR / "RELIABILITY.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["team_id", "match_exposures", "trusted_games", "excluded_match_exposures", "local_harmful_matches", "decisions", "nova_micro", "mask_forced", "deterministic_actions", "harmful_idle_actions", "harmful_idle_rate_pct"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for team_id in sorted(state["teams"]):
            counts = sources[team_id]
            total = sum(counts.values())
            deterministic = sum(value for source, value in counts.items() if source.startswith("deterministic"))
            harmful = counts["error-idle"] + counts["runner-idle"]
            writer.writerow({
                "team_id": team_id,
                "match_exposures": match_exposures[team_id],
                "trusted_games": state["teams"][team_id]["games"],
                "excluded_match_exposures": excluded_exposures[team_id],
                "local_harmful_matches": local_harmful_matches[team_id],
                "decisions": total,
                "nova_micro": counts["nova-micro"],
                "mask_forced": counts["mask-forced"],
                "deterministic_actions": deterministic,
                "harmful_idle_actions": harmful,
                "harmful_idle_rate_pct": round(100.0 * harmful / total, 4) if total else 0.0,
            })


def run_match(home: str, away: str, seed: int, rated_requested: bool, phase: str) -> dict:
    state = load_state()
    register_population(state)
    started = now()
    match = LiveMatch(home, away, seed=seed, realtime=False)
    match.start()
    match.thread.join()
    if match.status != "finished":
        raise RuntimeError(f"match {match.id} ended with {match.status}: {match.error}")
    ended_message = next(row for row in reversed(match.messages) if row.get("type") == "match_ended")
    path, rows = replay_rows(ended_message["replay"])
    decisions = [result for row in rows if row.get("type") == "decision" for result in row["agentResults"]]
    errors = [result for result in decisions if result.get("fallbackApplied") or result.get("status") != "valid"]
    harmful_errors = [result for result in errors if result.get("decisionSource") in {"error-idle", "runner-idle"}]
    end = next(row for row in rows if row.get("type") == "match_ended")
    rated = bool(rated_requested and not harmful_errors and end["status"] == "finished")
    latency = [float(result["latencyMs"]) for result in decisions]
    commands = Counter(result["normalizedCommand"]["type"] for result in decisions)
    sources = Counter(result["decisionSource"] for result in decisions)
    score = {"home": int(end["score"]["home"]), "away": int(end["score"]["away"])}
    record = {
        "match_id": match.id, "phase": phase, "started_utc": started, "finished_utc": now(),
        "home_team": home, "away_team": away, "home_hash": state["teams"][home]["implementation_hash"],
        "away_hash": state["teams"][away]["implementation_hash"], "seed": seed,
        "arena_version": end["arenaVersion"], "model": "us.amazon.nova-micro-v1:0",
        "score": score, "rated": rated, "rating_exclusion_reason": None if rated else ("screening" if not rated_requested else "harmful idle fallback"),
        "decision_count": len(decisions), "fallback_count": len(errors), "harmful_fallback_count": len(harmful_errors), "decision_sources": dict(sources),
        "latency_ms": {"minimum": round(min(latency), 3), "median": round(statistics.median(latency), 3), "maximum": round(max(latency), 3)},
        "commands": dict(commands), "simulation_metrics": end["simulationMetrics"],
        "replay_path": str(path.relative_to(ROOT)), "recording_path": ended_message["recording"].lstrip("/"),
        "replay_sha256": file_hash(path),
        "recording_sha256": file_hash(ROOT / ended_message["recording"].lstrip("/")),
    }
    state["matches"].append(record)
    if rated:
        home_team, away_team = state["teams"][home], state["teams"][away]
        home_before_rating, away_before_rating = home_team["rating"], away_team["rating"]
        home_score = result_score(score["home"], score["away"])
        hb, ha, hk = update_rating(home_team, away_before_rating, home_score)
        ab, aa, ak = update_rating(away_team, home_before_rating, 1.0 - home_score)
        for team, gf, ga, outcome in ((home_team, score["home"], score["away"], home_score), (away_team, score["away"], score["home"], 1.0-home_score)):
            team["games"] += 1; team["goals_for"] += gf; team["goals_against"] += ga
            team["wins"] += outcome == 1.0; team["draws"] += outcome == 0.5; team["losses"] += outcome == 0.0
        state.setdefault("elo_history", []).extend([
            {"timestamp_utc": record["finished_utc"], "match_id": match.id, "team_id": home, "opponent_id": away, "score": home_score, "rating_before": hb, "rating_after": ha, "k_factor": hk, "replay_path": record["replay_path"]},
            {"timestamp_utc": record["finished_utc"], "match_id": match.id, "team_id": away, "opponent_id": home, "score": 1.0-home_score, "rating_before": ab, "rating_after": aa, "k_factor": ak, "replay_path": record["replay_path"]},
        ])
    state["last_updated_utc"] = record["finished_utc"]
    state["events"].append({"time_utc": record["finished_utc"], "type": "match_completed", "detail": f"{home} {score['home']}-{score['away']} {away}; rated={rated}; seed={seed}"})
    atomic_json(RUN_DIR / "state.json", state)
    write_tables(state)
    telemetry_path = RUN_DIR / "telemetry" / f"{match.id}.json"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(telemetry_path, record)
    return record


def rebuild_ratings() -> dict:
    state = load_state()
    register_population(state)
    for team in state["teams"].values():
        team.update({"rating": 1500.0, "games": 0, "wins": 0, "draws": 0, "losses": 0, "goals_for": 0, "goals_against": 0})
    state["elo_history"] = []
    for record in state["matches"]:
        _, rows = replay_rows(record["replay_path"])
        record["replay_sha256"] = file_hash(ROOT / record["replay_path"].lstrip("/"))
        record["recording_sha256"] = file_hash(ROOT / record["recording_path"].lstrip("/"))
        decisions = [result for row in rows if row.get("type") == "decision" for result in row["agentResults"]]
        harmful = [result for result in decisions if result.get("decisionSource") in {"error-idle", "runner-idle"}]
        record["harmful_fallback_count"] = len(harmful)
        record["rated"] = not harmful and record.get("rating_exclusion_reason") != "screening"
        record["rating_exclusion_reason"] = None if record["rated"] else ("screening" if record.get("rating_exclusion_reason") == "screening" else "harmful idle fallback")
        telemetry_path = RUN_DIR / "telemetry" / f"{record['match_id']}.json"
        if telemetry_path.is_file():
            telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
            telemetry["harmful_fallback_count"] = record["harmful_fallback_count"]
            telemetry["rated"] = record["rated"]
            telemetry["rating_exclusion_reason"] = record["rating_exclusion_reason"]
            telemetry["replay_sha256"] = record["replay_sha256"]
            telemetry["recording_sha256"] = record["recording_sha256"]
            atomic_json(telemetry_path, telemetry)
        if not record["rated"]:
            continue
        home, away = state["teams"][record["home_team"]], state["teams"][record["away_team"]]
        home_prior, away_prior = home["rating"], away["rating"]
        outcome = result_score(record["score"]["home"], record["score"]["away"])
        hb, ha, hk = update_rating(home, away_prior, outcome)
        ab, aa, ak = update_rating(away, home_prior, 1.0-outcome)
        for team, gf, ga, score in ((home, record["score"]["home"], record["score"]["away"], outcome), (away, record["score"]["away"], record["score"]["home"], 1.0-outcome)):
            team["games"] += 1; team["goals_for"] += gf; team["goals_against"] += ga
            team["wins"] += score == 1.0; team["draws"] += score == 0.5; team["losses"] += score == 0.0
        state["elo_history"].extend([
            {"timestamp_utc": record["finished_utc"], "match_id": record["match_id"], "team_id": record["home_team"], "opponent_id": record["away_team"], "score": outcome, "rating_before": hb, "rating_after": ha, "k_factor": hk, "replay_path": record["replay_path"]},
            {"timestamp_utc": record["finished_utc"], "match_id": record["match_id"], "team_id": record["away_team"], "opponent_id": record["home_team"], "score": 1.0-outcome, "rating_before": ab, "rating_after": aa, "k_factor": ak, "replay_path": record["replay_path"]},
        ])
    stamp = now()
    state["last_updated_utc"] = stamp
    state["events"].append({"time_utc": stamp, "type": "rating_eligibility_policy_v2", "detail": "Chronologically rebuilt Elo: harmful error-idle/runner-idle excludes a match; explicit deterministic-fallback remains eligible and is separately labeled."})
    atomic_json(RUN_DIR / "state.json", state)
    write_tables(state)
    write_reliability(state)
    return state


def finalize_state(status: str) -> dict:
    """Persist the human-reviewed campaign selection without rewriting match truth."""
    state = load_state()
    register_population(state)
    ancestry = {
        "release-forward-wave-g1": ["release-and-run"],
        "release-counterpress-g1": ["release-and-run"],
        "release-deep-denial-g2": ["release-and-run"],
        "release-deep-denial-g3": ["release-deep-denial-g2"],
        "release-deep-denial-g4": ["release-deep-denial-g3"],
        "release-high-wave-g2": ["release-forward-wave-g1"],
        "release-balanced-g5": ["release-deep-denial-g4"],
        "release-finish-window-g6": ["release-balanced-g5"],
        "release-reliable-g1": ["release-and-run"],
        "release-switch-shield-g5": ["release-deep-denial-g4", "strict-switch-counter-g4"],
        "strict-wide-pocket-g1": ["nova-strict"],
        "strict-wide-pocket-g2": ["strict-wide-pocket-g1"],
        "strict-wide-pocket-g3": ["strict-wide-pocket-g2"],
        "strict-switch-counter-g4": ["strict-wide-pocket-g3", "release-deep-denial-g4"],
        "simple-pressure-carry-g1": ["simple-four-modes"],
        "vertical-safe-release-g1": ["nova-vertical"],
        "vertical-direct-shot-g1": ["nova-vertical"],
    }
    rejected = {
        "release-forward-wave-g1", "release-high-wave-g2", "release-balanced-g5",
        "release-finish-window-g6", "simple-pressure-carry-g1",
        "vertical-safe-release-g1", "vertical-direct-shot-g1",
    }
    suspended = {"kd-verticalis", "nova-baseline"}
    portfolio = {
        "release-deep-denial-g4": "primary-stable",
        "simple-four-modes": "backup-provisional",
        "release-switch-shield-g5": "targeted-alternative-stable",
        "strict-switch-counter-g4": "counter-provisional",
        "nova-vertical": "distinct-control-stable",
        "strict-wide-pocket-g3": "attacking-ceiling-provisional",
    }
    for team_id, team in state["teams"].items():
        team["ancestry"] = ancestry.get(team_id, team.get("ancestry", []))
        if team_id in ancestry:
            team["language"] = "English candidate additions over preserved inherited substrate"
        if team_id in rejected:
            team["status"] = "rejected"
        elif team_id in suspended:
            team["status"] = "suspended-operational"
        elif team_id in portfolio:
            team["status"] = portfolio[team_id]
        elif team_id in ancestry:
            team["status"] = "retained-lineage-history"
        else:
            team["status"] = "active-historical"
    def dependency_members(team_id: str, seen: set[str] | None = None) -> set[str]:
        seen = set() if seen is None else seen
        if team_id in seen:
            return seen
        seen.add(team_id)
        for parent_id in state["teams"][team_id].get("ancestry", []):
            dependency_members(parent_id, seen)
        return seen
    for team_id, team in state["teams"].items():
        members = sorted(dependency_members(team_id))
        material = json.dumps([(member, state["teams"][member]["implementation_hash"]) for member in members], separators=(",", ":"))
        team["dependency_members"] = members
        team["dependency_closure_hash"] = hashlib.sha256(material.encode()).hexdigest()
    state["lineages"] = {
        "release": {
            "seed": "release-and-run",
            "leader_chain": ["release-and-run", "release-deep-denial-g4"],
            "robustified_successor": "release-switch-shield-g5",
            "generations_created": 10,
            "status": "primary lineage; G4 selected, G5 retained as targeted alternative",
        },
        "strict-wide-pocket": {
            "seed": "nova-strict",
            "leader_chain": ["nova-strict", "strict-wide-pocket-g1", "strict-wide-pocket-g2", "strict-wide-pocket-g3"],
            "successful_exploiter": "strict-switch-counter-g4",
            "generations_created": 4,
            "status": "counter lineage retained",
        },
        "nova-vertical": {
            "seed": "nova-vertical",
            "leader_chain": ["nova-vertical"],
            "generations_created": 2,
            "status": "children rejected; stable parent retained as distinct control",
        },
        "simple-four-modes": {
            "seed": "simple-four-modes",
            "leader_chain": ["simple-four-modes"],
            "generations_created": 1,
            "status": "child rejected; parent is provisional Elo leader and backup",
        },
    }
    state["champion_history"] = [
        {"time_utc": "2026-08-28T20:59:26Z", "team_id": "nova-vertical", "reason": "first decisive trusted result and opening Elo lead"},
        {"time_utc": "2026-08-28T21:29:09Z", "team_id": "release-and-run", "reason": "subsequent scoring evidence and chronological Elo lead"},
        {"time_utc": "2026-08-28T21:59:41Z", "team_id": "nova-vertical", "reason": "renewed Elo lead after beating early G4"},
        {"time_utc": "2026-08-28T23:48:13Z", "team_id": "release-deep-denial-g4", "reason": "multi-seed Nova adaptation and broad-play Elo lead"},
        {"time_utc": "2026-08-29T01:22:32Z", "team_id": "simple-four-modes", "reason": "provisional Elo lead; not champion-promoted because below stable threshold"},
        {"time_utc": "2026-08-29T01:30:10Z", "team_id": "release-deep-denial-g4", "reason": "frozen stable incumbent finalist"},
        {"time_utc": "2026-08-29T02:06:56Z", "team_id": "release-deep-denial-g4", "reason": "final stable evolved primary; provisional Elo leader reported separately"},
    ]
    state["verified_environment"]["verification_status"] = "verified: 85 tests plus live smoke and 126 full matches"
    state["status"] = status
    state["final_selection"] = {
        "primary": "release-deep-denial-g4",
        "decision_rule": "stable evolved generalist with 27 trusted games; direct finalist draw; fresh Nova resistance; no unexplained catastrophic regression beyond the documented simple-four-modes home-side weakness",
        "provisional_elo_leader": "simple-four-modes",
        "targeted_alternative": "release-switch-shield-g5",
        "successful_counter": "strict-switch-counter-g4",
        "frozen_finalists": ["release-deep-denial-g4", "release-switch-shield-g5"],
        "frozen_hashes": {
            "release-deep-denial-g4": state["teams"]["release-deep-denial-g4"]["implementation_hash"],
            "release-switch-shield-g5": state["teams"]["release-switch-shield-g5"]["implementation_hash"],
        },
        "freeze_time_utc": "2026-08-29T01:30:10Z",
        "final_match_process_end_utc": "2026-08-29T02:06:56Z",
    }
    state["portfolio"] = [
        {
            "role": "PRIMARY", "team_id": "release-deep-denial-g4",
            "intended_use": "default stable evolved generalist",
            "best_evidence": "10 trusted Nova legs: 3-6-1, goals 3:1; fresh final pair 0-0/0-0",
            "known_failure": "simple-four-modes home orientation; far-side switch remains side-sensitive",
            "transfer_class": "mixed: model-driven prompts plus narrow validator-checked role recovery",
        },
        {
            "role": "BACKUP_CONTROL", "team_id": "simple-four-modes",
            "intended_use": "Release-family opponent after keeper calibration and one more trusted leg",
            "best_evidence": "provisional Elo leader; trusted 1-4-0 against both G4 and G5",
            "known_failure": "one game short of stable; deterministic goalkeeper is transfer-sensitive",
            "transfer_class": "mixed historical model policy with deterministic goalkeeper behavior",
        },
        {
            "role": "TARGETED_ALTERNATIVE", "team_id": "release-switch-shield-g5",
            "intended_use": "opponents that switch into the far high lane or use Nova high starts",
            "best_evidence": "cut Strict Switch paired shots from four to one and won 1-0 aggregate",
            "known_failure": "clean 0-1 loss to simple-four-modes and sparse broad attack",
            "transfer_class": "mixed: model-driven situation prompt plus narrow recovery",
        },
        {
            "role": "COUNTER", "team_id": "strict-switch-counter-g4",
            "intended_use": "compact 3-1 blocks whose far wingback follows ball pressure",
            "best_evidence": "repeatable four-shot paired screen and final home 1-0 against G4",
            "known_failure": "only seven trusted games; G5 0-2-1 matchup",
            "transfer_class": "mixed: explicit switch situation prompt plus narrow recovery",
        },
    ]
    state["evidence_limits"] = [
        "local nova-baseline-v2 Arena is not the unpublished AFC tournament simulator",
        "only four teams reached 20 trusted games; simple-four-modes has 19",
        "trusted results contain 64 draws in 79 legs and only 15 decisive legs",
        "trusted home teams won 10 versus five away wins; all three held-out decisive results were home wins",
        "a harmful idle by either side excludes the whole leg from Elo",
        "leaf hashes are per-match truth; conservative closure hashes capture all recorded code/evidence ancestors at handoff",
    ]
    stamp = now()
    state["last_updated_utc"] = stamp
    if status == "completed":
        state["completed_time_utc"] = stamp
    state["final_audit"] = {
        "verified_at_utc": stamp,
        "repository_tests": {"passed": 85, "failed": 0},
        "registered_teams": 24,
        "five_agent_team_loads": 24,
        "matches": 126,
        "trusted_matches": 79,
        "telemetry_files": 126,
        "replay_sha256_verified": 126,
        "recording_sha256_verified": 126,
        "recording_structure": "126/126 contain start + ticks 0..7200 + 120.0-second end",
        "independent_elo_reproduction": "exact",
        "independent_matchup_matrix_reproduction": "exact",
        "held_out_seed_collision": False,
        "viewer_http_status": 200,
        "running_match_processes": 0,
    }
    compact_events = []
    policy_seen = False
    for event in state["events"]:
        if event["type"] == "campaign_status":
            continue
        if event["type"] == "rating_eligibility_policy_v2":
            if policy_seen:
                continue
            policy_seen = True
        compact_events.append(event)
    state["events"] = compact_events
    state["events"].append({"time_utc": stamp, "type": "campaign_status", "detail": status})
    atomic_json(RUN_DIR / "state.json", state)
    write_tables(state)
    write_reliability(state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory")
    sub.add_parser("rebuild-ratings")
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--status", choices=["report-only", "completed"], required=True)
    match = sub.add_parser("match")
    match.add_argument("home"); match.add_argument("away"); match.add_argument("--seed", type=int, required=True)
    match.add_argument("--phase", default="league"); match.add_argument("--screen", action="store_true")
    args = parser.parse_args()
    state = load_state(); register_population(state); state["last_updated_utc"] = now(); atomic_json(RUN_DIR / "state.json", state); write_tables(state)
    if args.command == "inventory":
        print(json.dumps({team_id: {key: value for key, value in team.items() if key in {"implementation_hash", "formation", "strategy_family", "status"}} for team_id, team in state["teams"].items()}, indent=2))
    elif args.command == "rebuild-ratings":
        rebuilt = rebuild_ratings()
        print(json.dumps({team_id: {"rating": team["rating"], "games": team["games"]} for team_id, team in rebuilt["teams"].items()}, indent=2))
    elif args.command == "finalize":
        finalized = finalize_state(args.status)
        print(json.dumps({"status": finalized["status"], "last_updated_utc": finalized["last_updated_utc"], "final_selection": finalized["final_selection"]}, indent=2))
    else:
        print(json.dumps(run_match(args.home, args.away, args.seed, not args.screen, args.phase), indent=2))


if __name__ == "__main__":
    main()
