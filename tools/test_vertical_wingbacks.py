#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TEAM_ROOT = ROOT / "teams/vertical-wingbacks"
MODULE_NAME = "vertical_wingbacks_perception"
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


def view(player_id: int, state: dict):
    return perception.build_perception({"gameState": state, "teamId": 0, "myPlayers": [player_id]})


class VerticalWingbacksTests(unittest.TestCase):
    def test_manifest_and_five_role_files_are_consistent(self):
        manifest = yaml.safe_load((TEAM_ROOT / "team.yaml").read_text(encoding="utf-8"))
        strategy = yaml.safe_load((TEAM_ROOT / "strategy.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["formationPreset"], "3-1")
        self.assertEqual(set(strategy["players"]), set(range(5)))
        for player_id, relative in strategy["players"].items():
            folder = TEAM_ROOT / relative
            config = yaml.safe_load((folder / "player.yaml").read_text(encoding="utf-8"))
            self.assertEqual(config["player_id"], player_id)
            self.assertTrue(config["strategic_focus"]["priorities"])
            self.assertGreater(len((folder / "role.md").read_text(encoding="utf-8")), 80)
            self.assertGreater(len((folder / "situations.md").read_text(encoding="utf-8")), 120)

    def test_formation_morphs_from_three_one_to_one_three(self):
        theirs = snapshot(ball=(-20, -18), owner_team=1, owner_player=4)
        ours = snapshot(ball=(-20, -18), owner_team=0, owner_player=2)
        defensive = {pid: perception.dynamic_anchor(view(pid, theirs), pid) for pid in range(1, 5)}
        attacking = {pid: perception.dynamic_anchor(view(pid, ours), pid) for pid in range(1, 5)}
        self.assertLess(abs(defensive[1].x-defensive[2].x), 3.0)
        self.assertLess(abs(defensive[3].x-defensive[2].x), 3.0)
        self.assertGreater(defensive[4].x-defensive[2].x, 10.0)
        self.assertGreater(attacking[1].x-attacking[2].x, 20.0)
        self.assertGreater(attacking[3].x-attacking[2].x, 20.0)
        self.assertGreater(attacking[4].x-attacking[2].x, 20.0)

    def test_role_aware_responsibility_keeps_centre_back_out_of_left_touchline(self):
        state = snapshot(ball=(-30, -20))
        ranks = perception.responsibility(view(2, state))[0]
        self.assertEqual(ranks[0][1], 1)

    def test_centre_back_owns_central_danger_and_forward_never_chases_deep(self):
        state = snapshot(ball=(-28, 0))
        ranks = perception.responsibility(view(2, state))[0]
        self.assertEqual(ranks[0][1], 2)
        self.assertNotEqual(ranks[0][1], 4)

    def test_free_ball_phase_uses_arrival_margin_not_binary_possession(self):
        likely_ours = snapshot(ball=(-30, -18))
        likely_theirs = snapshot(ball=(5, 0))
        for raw in likely_theirs["players"]:
            if raw["teamCode"] == "away" and raw["agentId"] == "away_4":
                raw["position"] = {"x": 5.2, "y": 0}
        self.assertEqual(perception.control_phase(view(1, likely_ours)), "LIKELY_OURS")
        self.assertEqual(perception.control_phase(view(4, likely_theirs)), "LIKELY_THEIRS")

    def test_semantics_rejects_role_breaking_targets(self):
        centre_back = view(2, snapshot(ball=(-30, 0), owner_team=0, owner_player=2))
        with self.assertRaisesRegex(ValueError, "ролевого коридора"):
            perception.validate_semantics(centre_back, "MOVE_TO", target_x=-25, target_y=20)
        forward = view(4, snapshot(ball=(0, 0), owner_team=0, owner_player=4))
        with self.assertRaisesRegex(ValueError, "ролевого коридора"):
            perception.validate_semantics(forward, "DRIBBLE", target_x=1, target_y=12.1)

    def test_opening_cannot_collapse_onto_a_teammate(self):
        state = snapshot(ball=(0, 0), owner_team=0, owner_player=2)
        next(raw for raw in state["players"] if raw["agentId"] == "home_2")["position"] = {"x": 0, "y": 0}
        forward = view(4, state)
        with self.assertRaisesRegex(ValueError, "сближение менее 5 м"):
            perception.validate_semantics(forward, "MOVE_TO", target_x=0, target_y=0)

    def test_recommended_wing_anchor_never_collapses_onto_owner(self):
        state = snapshot(ball=(43.7, 15.2), owner_team=0, owner_player=4)
        next(raw for raw in state["players"] if raw["agentId"] == "home_4")["position"] = {"x": 43, "y": 14.8}
        right = view(3, state)
        anchor = perception.dynamic_anchor(right, 3)
        self.assertGreaterEqual(anchor.distance_to(right.teammates[4].position), 6)

    def test_zonal_non_primary_players_are_never_offered_mark(self):
        state = snapshot(ball=(-25, 0), owner_team=1, owner_player=4)
        views = [view(pid, state) for pid in range(5)]
        self.assertTrue(all("MARK" not in perception.allowed_commands(item) for item in views))

    def test_forward_receives_ranked_shooting_candidates(self):
        state = snapshot(ball=(24, -15), owner_team=0, owner_player=1)
        forward = view(4, state)
        candidates = perception.striker_candidates(forward)
        self.assertGreaterEqual(len(candidates), 6)
        self.assertTrue(all(-12 <= item[2].y <= 12 for item in candidates))
        self.assertTrue(any("ударная" in item[1] for item in candidates[:4]))

    def test_forward_candidate_ranking_penalizes_a_teammates_position(self):
        state = snapshot(ball=(-26, 0), owner_team=0, owner_player=2)
        next(raw for raw in state["players"] if raw["agentId"] == "home_3")["position"] = {"x": -4, "y": 0}
        forward = view(4, state)
        best = perception.striker_candidates(forward)[0][2]
        self.assertGreaterEqual(best.distance_to(forward.teammates[3].position), 5)

    def test_central_forward_gets_three_distinct_dribble_corridors(self):
        forward = view(4, snapshot(ball=(36, 0), owner_team=0, owner_player=4))
        corridors = perception.dribble_corridors(forward)
        self.assertEqual({round(item[1].y) for item in corridors}, {-6, 0, 6})

    def test_late_wing_anchors_enter_shooting_half_spaces(self):
        state = snapshot(ball=(36, 0), owner_team=0, owner_player=4)
        next(raw for raw in state["players"] if raw["agentId"] == "home_4")["position"] = {"x": 36, "y": 0}
        left = perception.dynamic_anchor(view(1, state), 1)
        right = perception.dynamic_anchor(view(3, state), 3)
        self.assertAlmostEqual(left.y, -9)
        self.assertAlmostEqual(right.y, 9)
        self.assertGreaterEqual(left.x, 38)

    def test_blocked_dribble_is_unavailable_and_rejected(self):
        state = snapshot(ball=(36, 0), owner_team=0, owner_player=4)
        next(raw for raw in state["players"] if raw["agentId"] == "home_4")["position"] = {"x": 36, "y": 0}
        for player_id, point in {1: (39, -3), 2: (39, 0), 3: (39, 3)}.items():
            next(raw for raw in state["players"] if raw["agentId"] == f"away_{player_id}")["position"] = {
                "x": point[0], "y": point[1]}
        forward = view(4, state)
        self.assertNotIn("DRIBBLE", perception.allowed_commands(forward))
        with self.assertRaisesRegex(ValueError, "DRIBBLE недоступна|DRIBBLE заблокирован"):
            perception.validate_semantics(forward, "DRIBBLE", target_x=44, target_y=0)

    def test_winger_dribble_corridors_stay_inside_role_zone_at_touchline(self):
        state = snapshot(ball=(-54, 34), owner_team=0, owner_player=3)
        next(raw for raw in state["players"] if raw["agentId"] == "home_3")["position"] = {"x": -54, "y": 34}
        right = view(3, state)
        self.assertTrue(perception.executable_dribble_corridors(right))
        self.assertTrue(all(-45 <= item[1].x <= 50 and 4 <= item[1].y <= 27
                            for item in perception.executable_dribble_corridors(right)))

    def test_risky_pass_is_vetoed_when_an_open_alternative_exists(self):
        state = snapshot(ball=(0, 0), owner_team=0, owner_player=2)
        replacements = {"home_2": (0, 0), "home_4": (10, 0), "home_3": (8, 15),
                        "away_1": (5, 0), "away_2": (30, -20), "away_3": (30, 20),
                        "away_4": (25, 25)}
        for raw in state["players"]:
            if raw["agentId"] in replacements:
                x, y = replacements[raw["agentId"]]
                raw["position"] = {"x": x, "y": y}
        defender = view(2, state)
        with self.assertRaisesRegex(ValueError, "рискованный PASS запрещён"):
            perception.validate_semantics(defender, "PASS", target_player_id=4)

    def test_finishing_observation_prioritizes_wings_and_receiver_shot_value(self):
        state = snapshot(ball=(36, 0), owner_team=0, owner_player=4)
        replacements = {"home_4": (36, 0), "home_1": (40, -9), "home_3": (40, 9),
                        "away_1": (46, -2), "away_2": (46, 0), "away_3": (46, 2),
                        "away_4": (0, 30)}
        for raw in state["players"]:
            if raw["agentId"] in replacements:
                x, y = replacements[raw["agentId"]]
                raw["position"] = {"x": x, "y": y}
        config = yaml.safe_load((TEAM_ROOT / "players/4-central-forward/player.yaml").read_text())
        observation = perception.describe(view(4, state), config)
        self.assertIn("FINISHING OVERRIDE", observation)
        self.assertIn("Открытые вингеры для завершения", observation)
        self.assertIn("после приёма: до ворот", observation)

    def test_observation_names_phase_corridors_and_goal_coverage(self):
        defender_state = snapshot(ball=(-25, 0), owner_team=1, owner_player=4)
        config = yaml.safe_load((TEAM_ROOT / "players/2-central-defender/player.yaml").read_text())
        observation = perception.describe(view(2, defender_state), config)
        self.assertIn("ФАЗА THEIR_CONTROL", observation)
        self.assertIn("Разделение с вратарём", observation)
        winger_state = snapshot(ball=(-20, -15), owner_team=0, owner_player=1)
        config = yaml.safe_load((TEAM_ROOT / "players/1-left-wingback/player.yaml").read_text())
        observation = perception.describe(view(1, winger_state), config)
        self.assertIn("Передние коридоры дриблинга", observation)


if __name__ == "__main__":
    unittest.main()
