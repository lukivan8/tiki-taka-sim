#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TEAM_ROOT = ROOT / "teams/release-and-run"
MODULE_NAME = "release_and_run_perception"
SPEC = importlib.util.spec_from_file_location(MODULE_NAME, TEAM_ROOT / "shared/perception.py")
assert SPEC and SPEC.loader
perception = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = perception
SPEC.loader.exec_module(perception)


def snapshot(ball=(-20, 0), owner_team=None, owner_player=None) -> dict:
    positions = {
        0: [(-50, 0), (-31, -15), (-33, 0), (-31, 15), (-5, 0)],
        1: [(50, 0), (31, 15), (33, 0), (31, -15), (5, 0)],
    }
    players = []
    for team_id in (0, 1):
        code = "home" if team_id == 0 else "away"
        for player_id, (x, y) in enumerate(positions[team_id]):
            players.append({
                "agentId": f"{code}_{player_id}", "teamCode": code,
                "position": {"x": x, "y": y}, "velocity": {"x": 0, "y": 0},
                "speed": 0, "stamina": 1, "lastAction": "IDLE",
            })
    owner = None
    if owner_team is not None:
        owner = f"{'home' if owner_team == 0 else 'away'}_{owner_player}"
    return {
        "gameTime": 10, "players": players,
        "ball": {
            "position": {"x": ball[0], "y": ball[1]},
            "velocity": {"x": 0, "y": 0},
            "possessionTeamId": owner_team, "possessionAgentId": owner,
        },
    }


def place(state: dict, agent_id: str, point: tuple[float, float]) -> None:
    raw = next(item for item in state["players"] if item["agentId"] == agent_id)
    raw["position"] = {"x": point[0], "y": point[1]}


def view(player_id: int, state: dict):
    return perception.build_perception({"gameState": state, "teamId": 0, "myPlayers": [player_id]})


class ReleaseAndRunTests(unittest.TestCase):
    def test_is_a_separate_team_variant(self):
        manifest = yaml.safe_load((TEAM_ROOT / "team.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["teamId"], "release-and-run")
        self.assertEqual(manifest["formationPreset"], "3-1")
        self.assertTrue((ROOT / "teams/vertical-wingbacks/team.yaml").is_file())

    def test_panic_zone_names_attacking_release_without_hiding_carry(self):
        state = snapshot(ball=(0, -12), owner_team=0, owner_player=1)
        place(state, "home_1", (0, -12))
        place(state, "home_2", (-8, 0))
        place(state, "home_4", (0, 5))
        place(state, "away_4", (2.8, -12))
        owner = view(1, state)
        self.assertTrue(perception.panic_pressure(owner)[0])
        self.assertTrue(perception.open_passes(owner))
        self.assertTrue(perception.attacking_open_passes(owner))
        self.assertIn("PASS", perception.allowed_commands(owner))
        self.assertIn("DRIBBLE", perception.allowed_commands(owner))
        config = yaml.safe_load((TEAM_ROOT / "players/1-left-wingback/player.yaml").read_text())
        self.assertIn("Есть OPEN-ВПЕРЁД/ПОПЕРЁК", perception.describe(owner, config))

    def test_backward_open_pass_does_not_cancel_an_open_carry(self):
        state = snapshot(ball=(0, -12), owner_team=0, owner_player=1)
        for agent_id, point in {
            "home_1": (0, -12), "home_2": (-12, 0), "home_3": (-10, 16),
            "home_4": (-8, 0), "away_4": (2.8, -12),
        }.items():
            place(state, agent_id, point)
        owner = view(1, state)
        self.assertTrue(perception.panic_pressure(owner)[0])
        self.assertTrue(perception.open_passes(owner))
        self.assertFalse(perception.attacking_open_passes(owner))
        self.assertIn("DRIBBLE", perception.allowed_commands(owner))
        config = yaml.safe_load((TEAM_ROOT / "players/1-left-wingback/player.yaml").read_text())
        observation = perception.describe(owner, config)
        self.assertIn("FORWARD CARRY PRIORITY ЭТОГО ТИКА", observation)
        self.assertIn("PASS НАЗАД не выбирай", observation)

    def test_backward_pass_is_explicitly_labeled_for_the_model(self):
        state = snapshot(ball=(-9, -11), owner_team=0, owner_player=1)
        for agent_id, point in {
            "home_1": (-9, -11), "home_2": (-27, 0), "home_3": (-3, 21),
            "home_4": (5, 0), "away_4": (-17, 6),
        }.items():
            place(state, agent_id, point)
        owner = view(1, state)
        config = yaml.safe_load((TEAM_ROOT / "players/1-left-wingback/player.yaml").read_text())
        observation = perception.describe(owner, config)
        self.assertIn("к №2: ОТКРЫТА-НАЗАД", observation)
        self.assertIn("продвижение -18.0", observation)

    def test_owner_prompt_distinguishes_anchor_from_dribble(self):
        state = snapshot(ball=(0, -12), owner_team=0, owner_player=1)
        place(state, "home_1", (0, -12))
        owner = view(1, state)
        self.assertIn("MOVE_TO", perception.allowed_commands(owner))
        strategy = (TEAM_ROOT / "strategy.md").read_text(encoding="utf-8")
        self.assertIn("Владелец мяча не выбирает `MOVE_TO`", strategy)

    def test_pressure_outside_panic_keeps_open_space_carry(self):
        state = snapshot(ball=(0, -12), owner_team=0, owner_player=1)
        place(state, "home_1", (0, -12))
        place(state, "away_4", (4.0, -12))
        owner = view(1, state)
        self.assertFalse(perception.panic_pressure(owner)[0])
        self.assertIn("DRIBBLE", perception.allowed_commands(owner))

    def test_winger_attacks_space_forward_and_inside_during_our_control(self):
        state = snapshot(ball=(0, 0), owner_team=0, owner_player=2)
        place(state, "home_2", (0, 0))
        place(state, "home_1", (-12, -18))
        winger = view(1, state)
        target = perception.winger_run_target(winger, 1)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertGreater(target.x, winger.self_player.position.x)
        self.assertGreater(target.y, winger.self_player.position.y)
        self.assertEqual(perception.dynamic_anchor(winger, 1), target)
        config = yaml.safe_load((TEAM_ROOT / "players/1-left-wingback/player.yaml").read_text())
        observation = perception.describe(winger, config)
        self.assertIn("WINGER PASS AND RUN", observation)
        self.assertIn("sprint=true", observation)

    def test_advanced_forward_pulls_both_wingers_to_ball_relative_targets(self):
        state = snapshot(ball=(33, 24), owner_team=0, owner_player=4)
        place(state, "home_4", (33, 24))
        place(state, "home_1", (-22, -12))
        place(state, "home_3", (-22, 16))
        for player_id in (1, 3):
            winger = view(player_id, state)
            target = perception.winger_run_target(winger, player_id)
            self.assertIsNotNone(target)
            assert target is not None
            self.assertGreaterEqual(target.x, 29)
            config = yaml.safe_load(
                (TEAM_ROOT / f"players/{player_id}-{'left' if player_id == 1 else 'right'}-wingback/player.yaml")
                .read_text())
            observation = perception.describe(winger, config)
            self.assertIn(f"Атакуй ({target.x:.1f},{target.y:.1f})", observation)
            self.assertIn("sprint=true", observation)

    def test_winger_prefers_straight_flank_corridor_when_it_is_really_open(self):
        state = snapshot(ball=(0, -15), owner_team=0, owner_player=1)
        place(state, "home_1", (0, -15))
        for player_id, point in {1: (20, 25), 2: (25, 0), 3: (25, -30), 4: (30, 20)}.items():
            place(state, f"away_{player_id}", point)
        self.assertEqual(perception.dribble_corridors(view(1, state))[0][0], "прямо")

    def test_good_enough_shot_prioritizes_shoot_over_dribble(self):
        state = snapshot(ball=(30, -10), owner_team=0, owner_player=1)
        place(state, "home_1", (30, -10))
        for player_id, point in {0: (50, 20), 1: (5, 25), 2: (8, 30),
                                 3: (10, -30), 4: (0, 25)}.items():
            place(state, f"away_{player_id}", point)
        winger = view(1, state)
        self.assertTrue(perception.good_enough_shot(winger))
        self.assertIn("SHOOT", perception.allowed_commands(winger))
        self.assertIn("DRIBBLE", perception.allowed_commands(winger))
        config = yaml.safe_load((TEAM_ROOT / "players/1-left-wingback/player.yaml").read_text())
        self.assertIn("GOOD_ENOUGH_SHOT", perception.describe(winger, config))

    def test_high_quality_shot_remains_the_hard_guard(self):
        state = snapshot(ball=(44, 0), owner_team=0, owner_player=3)
        place(state, "home_3", (44, 0))
        for player_id, point in {0: (50, 10), 1: (20, -25), 2: (20, 25),
                                 3: (5, -25), 4: (5, 25)}.items():
            place(state, f"away_{player_id}", point)
        winger = view(3, state)
        self.assertTrue(perception.high_quality_shot(winger))
        self.assertEqual(perception.allowed_commands(winger), ("SHOOT",))


if __name__ == "__main__":
    unittest.main()
