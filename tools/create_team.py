#!/usr/bin/env python3
"""Create a self-contained Nova team from an existing catalog team."""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TEAMS_ROOT = ROOT / "teams"
TEAM_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{1,47}")


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path} must contain a YAML object")
    return value


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def create_team(team_id: str, display_name: str | None = None,
                source_id: str = "nova-baseline", formation: str | None = None) -> Path:
    if not TEAM_ID_PATTERN.fullmatch(team_id):
        raise SystemExit("team id must be a 2-48 character lowercase slug: letters, digits, hyphens")
    if not TEAM_ID_PATTERN.fullmatch(source_id):
        raise SystemExit("source must be a valid team slug")
    source = TEAMS_ROOT / source_id
    target = TEAMS_ROOT / team_id
    if not (source / "team.yaml").is_file():
        raise SystemExit(f"source team {source_id!r} does not exist")
    if target.exists():
        raise SystemExit(f"team {team_id!r} already exists")

    source_manifest = load_yaml(source / "team.yaml")
    if source_manifest.get("backend") != "nova-micro":
        raise SystemExit("source team does not use the required nova-micro backend")
    selected_formation = formation or str(source_manifest["formationPreset"])
    arena = load_yaml(ROOT / "arena/arena.yaml")
    presets = arena["simulationParameters"]["formation"]["presets"]
    if selected_formation not in presets:
        raise SystemExit(
            f"unknown formation {selected_formation!r}; choose one of {', '.join(presets)}"
        )

    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    try:
        manifest = load_yaml(target / "team.yaml")
        manifest["teamId"] = team_id
        manifest["displayName"] = display_name or team_id.replace("-", " ").title()
        manifest["teamVersion"] = "v1"
        manifest["backend"] = "nova-micro"
        manifest["formationPreset"] = selected_formation
        manifest.pop("style", None)
        manifest["implementation"]["entrypoint"] = f"python3 teams/{team_id}/agent.py"
        write_yaml(target / "team.yaml", manifest)

        strategy = load_yaml(target / "strategy.yaml")
        strategy["name"] = manifest["displayName"]
        strategy["version"] = "v1"
        strategy["model"] = "us.amazon.nova-micro-v1:0"
        write_yaml(target / "strategy.yaml", strategy)
    except Exception:
        shutil.rmtree(target)
        raise
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("team_id")
    parser.add_argument("--display-name")
    parser.add_argument("--source", default="nova-baseline")
    parser.add_argument("--formation")
    args = parser.parse_args()
    target = create_team(args.team_id, args.display_name, args.source, args.formation)
    print(f"Created {target.relative_to(ROOT)}")
    print(f"Edit roles in {target.relative_to(ROOT)}/players, refresh the page, and start a new match")


if __name__ == "__main__":
    main()
