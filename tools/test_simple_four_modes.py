#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEAM_ROOT = ROOT / "teams/simple-four-modes"
PACKAGE = "simple_four_modes_test"

package = types.ModuleType(PACKAGE)
package.__path__ = [str(TEAM_ROOT)]
package.__package__ = PACKAGE
sys.modules[PACKAGE] = package
shared = types.ModuleType(f"{PACKAGE}.shared")
shared.__path__ = [str(TEAM_ROOT / "shared")]
shared.__package__ = f"{PACKAGE}.shared"
sys.modules[shared.__package__] = shared

commands_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.shared.commands", TEAM_ROOT / "shared/commands.py")
assert commands_spec and commands_spec.loader
commands = importlib.util.module_from_spec(commands_spec)
sys.modules[commands_spec.name] = commands
commands_spec.loader.exec_module(commands)

perception_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.shared.perception", TEAM_ROOT / "shared/perception.py")
assert perception_spec and perception_spec.loader
perception = importlib.util.module_from_spec(perception_spec)
sys.modules[perception_spec.name] = perception
perception_spec.loader.exec_module(perception)

prompting_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.shared.prompting", TEAM_ROOT / "shared/prompting.py")
assert prompting_spec and prompting_spec.loader
prompting = importlib.util.module_from_spec(prompting_spec)
sys.modules[prompting_spec.name] = prompting
prompting_spec.loader.exec_module(prompting)

runtime_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.shared.runtime", TEAM_ROOT / "shared/runtime.py")
assert runtime_spec and runtime_spec.loader
runtime = importlib.util.module_from_spec(runtime_spec)
sys.modules[runtime_spec.name] = runtime
runtime_spec.loader.exec_module(runtime)


def snapshot(ball=(0, 0), owner_team=None, owner_player=None) -> dict:
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
    owner = None if owner_team is None else f"{'home' if owner_team == 0 else 'away'}_{owner_player}"
    return {
        "gameTime": 86.45, "players": players,
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


class SimpleFourModesTests(unittest.TestCase):
    def test_system_prompt_has_one_policy_and_no_legacy_policy_sections(self):
        system = prompting.build_system_prompt(3)
        self.assertLess(len(system), 3500)
        self.assertIn("FINISH > PANIC > PROGRESS > SUPPORT", system)
        self.assertNotIn("Тактические ситуации роли", system)
        self.assertNotIn("Приоритеты роли", system)
        self.assertNotIn("Стратегический фокус", system)

    def test_8645_geometry_is_finish_even_when_panic_and_progress_are_true(self):
        state = snapshot(ball=(48.2, 16.2), owner_team=0, owner_player=3)
        for agent_id, point in {
            "home_3": (48.0, 15.4), "home_4": (42.6, 6.0),
            "away_0": (50.0, 2.3), "away_1": (47.0, 16.1),
            "away_2": (41.0, 4.2), "away_3": (39.0, -7.1), "away_4": (8.1, 3.6),
        }.items():
            place(state, agent_id, point)
        winger = view(3, state)
        self.assertFalse(perception.high_quality_shot(winger))
        self.assertTrue(perception.good_enough_shot(winger))
        self.assertTrue(perception.panic_pressure(winger)[0])
        self.assertEqual(perception.tactical_mode(winger), "FINISH")
        observation = perception.describe(winger, {})
        self.assertIn("SHOT_QUALITY: GOOD_ENOUGH", observation)
        self.assertIn("РЕШЕНИЕ FINISH: выбери SHOOT", observation)

    def test_panic_precedes_progress_when_shot_is_not_ready(self):
        state = snapshot(ball=(0, -12), owner_team=0, owner_player=1)
        place(state, "home_1", (0, -12))
        place(state, "away_4", (2.8, -12))
        winger = view(1, state)
        self.assertTrue(perception.executable_dribble_corridors(winger))
        self.assertEqual(perception.tactical_mode(winger), "PANIC")

    def test_open_space_owner_uses_progress_mode(self):
        state = snapshot(ball=(0, -12), owner_team=0, owner_player=1)
        place(state, "home_1", (0, -12))
        place(state, "away_4", (8, 20))
        self.assertEqual(perception.tactical_mode(view(1, state)), "PROGRESS")

    def test_progress_without_attacking_pass_names_dribble_not_backward_pass(self):
        state = snapshot(ball=(0, 0), owner_team=0, owner_player=2)
        place(state, "home_2", (-0.9, 0))
        defender = view(2, state)
        self.assertEqual(perception.tactical_mode(defender), "PROGRESS")
        self.assertFalse(perception.attacking_open_passes(defender))
        observation = perception.describe(defender, {})
        self.assertIn("открытого паса ВПЕРЁД/ПОПЕРЁК нет", observation)
        self.assertIn("Выбери указанный PROGRESS DRIBBLE", observation)
        self.assertIn("не выбирай PASS с пометкой НАЗАД", observation)

    def test_clear_is_not_available_from_midfield_or_attacking_third(self):
        for player_id, point in ((2, (0, -1)), (4, (38, -12))):
            with self.subTest(player_id=player_id):
                state = snapshot(ball=point, owner_team=0, owner_player=player_id)
                place(state, f"home_{player_id}", point)
                place(state, "away_4", (point[0]+1.5, point[1]))
                owner = view(player_id, state)
                self.assertEqual(perception.tactical_mode(owner), "PANIC")
                self.assertNotIn("CLEAR", perception.allowed_commands(owner))

    def test_panic_with_executable_carry_explicitly_rejects_random_clear(self):
        state = snapshot(ball=(0, -12), owner_team=0, owner_player=1)
        place(state, "home_1", (0, -12))
        place(state, "away_4", (2.8, -12))
        winger = view(1, state)
        self.assertTrue(perception.executable_dribble_corridors(winger))
        self.assertNotIn("CLEAR", perception.allowed_commands(winger))
        observation = perception.describe(winger, {})
        self.assertIn("Лучшее доступное действие", observation)
        self.assertIn("DRIBBLE", observation)

    def test_clear_remains_available_for_deep_defensive_emergency(self):
        state = snapshot(ball=(-42, 0), owner_team=0, owner_player=2)
        place(state, "home_2", (-42, 0))
        for agent_id, point in {
            "away_1": (-41, 0),
            "away_2": (-34, 0),
            "away_3": (-35, -6),
            "away_4": (-35, 6),
        }.items():
            place(state, agent_id, point)
        defender = view(2, state)
        self.assertTrue(perception.defensive_clearance_emergency(defender))
        self.assertIn("CLEAR", perception.allowed_commands(defender))
        self.assertIn("выбери CLEAR", perception.describe(defender, {}))

    def test_goalkeeper_off_ball_position_is_deterministic_and_closes_ball_angle(self):
        state = snapshot(ball=(-35, -8), owner_team=1, owner_player=3)

        class ModelMustNotRun:
            def structured_output(self, *_args, **_kwargs):
                raise AssertionError("goalkeeper positioning must not call the model")

        result = runtime.invoke_agent(ModelMustNotRun(), 0, {
            "prompt": {"gameState": state, "teamId": 0, "myPlayers": [0]},
        })
        self.assertEqual(result.source, "deterministic-goalkeeper")
        self.assertEqual(result.wire["commandType"], "MOVE_TO")
        self.assertEqual(result.latency_ms, 0)
        self.assertAlmostEqual(result.wire["parameters"]["target_x"], -50.0)
        self.assertAlmostEqual(result.wire["parameters"]["target_y"], -8 * 6 / 21)
        self.assertGreater(abs(result.wire["parameters"]["target_y"]), 0.8)

    def test_goalkeeper_with_ball_uses_model_only_for_distribution(self):
        state = snapshot(ball=(-50, 0), owner_team=0, owner_player=0)
        goalkeeper = view(0, state)
        self.assertEqual(perception.tactical_mode(goalkeeper), "PROGRESS")
        self.assertEqual(perception.allowed_commands(goalkeeper), ("GK_DISTRIBUTE", "CLEAR"))
        observation = perception.describe(goalkeeper, {})
        self.assertIn("РЕШЕНИЕ PROGRESS ВРАТАРЯ", observation)
        self.assertIn("GK_DISTRIBUTE", observation)
        self.assertIn("Не выбирай PASS или MOVE_TO", observation)
        self.assertNotIn("УДАР:", observation)

    def test_goalkeeper_under_pressure_uses_goalkeeper_command_names(self):
        state = snapshot(ball=(-50, 0), owner_team=0, owner_player=0)
        place(state, "away_4", (-48, 0))
        goalkeeper = view(0, state)
        self.assertEqual(perception.tactical_mode(goalkeeper), "PANIC")
        observation = perception.describe(goalkeeper, {})
        self.assertIn("РЕШЕНИЕ PANIC ВРАТАРЯ", observation)
        self.assertNotIn("Выбери лучший PASS", observation)

    def test_advanced_forward_gives_wingers_support_targets_near_the_ball(self):
        state = snapshot(ball=(33, 24), owner_team=0, owner_player=4)
        place(state, "home_4", (33, 24))
        place(state, "home_1", (-22, -12))
        place(state, "home_3", (-22, 16))
        for player_id in (1, 3):
            winger = view(player_id, state)
            self.assertEqual(perception.tactical_mode(winger), "SUPPORT")
            target = perception.winger_run_target(winger, player_id)
            self.assertIsNotNone(target)
            assert target is not None
            self.assertGreaterEqual(target.x, 29)
            self.assertIn("sprint=true", perception.describe(winger, {}))

    def test_unreachable_free_ball_is_not_described_or_allowed_as_intercept(self):
        for player_id, side, opponent_id in ((1, -1, 3), (3, 1, 1)):
            with self.subTest(player_id=player_id):
                state = snapshot(ball=(-34, side*35))
                state["ball"]["velocity"] = {"x": -8, "y": 0}
                place(state, f"home_{player_id}", (-10, side*15))
                place(state, f"away_{opponent_id}", (-36, side*32))
                wingback = view(player_id, state)
                race = perception.free_ball_race(wingback)
                self.assertEqual(race.player_id, player_id)
                self.assertFalse(race.should_intercept)
                self.assertNotIn("INTERCEPT", perception.allowed_commands(wingback))
                observation = perception.describe(wingback, {})
                self.assertIn("не иди к свободному мячу", observation)
                self.assertIn("INTERCEPT запрещён", observation)

    def test_won_reachable_free_ball_race_allows_intercept(self):
        for player_id, side, opponent_id in ((1, -1, 3), (3, 1, 1)):
            with self.subTest(player_id=player_id):
                state = snapshot(ball=(-24, side*15))
                place(state, f"home_{player_id}", (-27, side*15))
                place(state, f"away_{opponent_id}", (-32, side*15))
                wingback = view(player_id, state)
                race = perception.free_ball_race(wingback)
                self.assertEqual(race.player_id, player_id)
                self.assertTrue(race.should_intercept)
                self.assertIn("INTERCEPT", perception.allowed_commands(wingback))
                self.assertIn("гонка выиграна", perception.describe(wingback, {}))

    def test_opponent_owner_uses_press_not_intercept(self):
        for player_id, side, opponent_id in ((1, -1, 3), (3, 1, 1)):
            with self.subTest(player_id=player_id):
                state = snapshot(ball=(-25, side*15), owner_team=1,
                                 owner_player=opponent_id)
                place(state, f"home_{player_id}", (-27, side*15))
                place(state, f"away_{opponent_id}", (-25, side*15))
                wingback = view(player_id, state)
                self.assertIn("PRESS_BALL", perception.allowed_commands(wingback))
                self.assertNotIn("INTERCEPT", perception.allowed_commands(wingback))
                observation = perception.describe(wingback, {})
                self.assertIn("TACKLE_WINDOW", observation)
                self.assertIn(f"target_player_id={opponent_id}", observation)
                self.assertIn("Не выбирай PRESS_BALL", observation)

    def test_press_closes_distance_before_tackle_window(self):
        state = snapshot(ball=(-25, -15), owner_team=1, owner_player=3)
        place(state, "home_1", (-29, -15))
        place(state, "away_3", (-25, -15))
        wingback = view(1, state)
        self.assertIn("PRESS_BALL", perception.allowed_commands(wingback))
        self.assertNotIn("SLIDE_TACKLE", perception.allowed_commands(wingback))
        observation = perception.describe(wingback, {})
        self.assertIn("удерживай плотный контакт для standing challenge", observation)
        self.assertIn("не указывай target_x, target_y", observation)
        self.assertIn("INTERCEPT предназначен только для свободного мяча", observation)

    def test_centre_back_holds_rest_defence_until_possession_is_secured(self):
        state = snapshot(ball=(8, 0))
        place(state, "home_1", (7.5, 0))
        place(state, "away_4", (20, 20))
        centre_back = view(2, state)
        self.assertEqual(perception.control_phase(centre_back), "LIKELY_OURS")
        likely_anchor = perception.dynamic_anchor(centre_back, 2)
        self.assertEqual(likely_anchor.x, -24)

        state["ball"]["possessionTeamId"] = 0
        state["ball"]["possessionAgentId"] = "home_1"
        secured = view(2, state)
        self.assertEqual(perception.control_phase(secured), "OUR_CONTROL")
        self.assertGreater(perception.dynamic_anchor(secured, 2).x, likely_anchor.x)

    def test_non_primary_centre_back_is_told_teammate_wins_free_ball(self):
        state = snapshot(ball=(-13.15, 23.67))
        state["ball"]["velocity"] = {"x": -2.56, "y": -17.69}
        place(state, "home_1", (-22, -6.11))
        place(state, "home_2", (-24, 6.12))
        centre_back = view(2, state)
        race = perception.free_ball_race(centre_back)
        self.assertEqual(race.player_id, 1)
        self.assertTrue(race.should_intercept)
        self.assertNotIn("INTERCEPT", perception.allowed_commands(centre_back))
        observation = perception.describe(centre_back, {})
        self.assertIn("первичным назначен партнёр №1", observation)
        self.assertIn("Не дублируй его", observation)
        self.assertNotIn("нет требуемого преимущества", observation)

    def test_narrow_positive_free_ball_edge_remains_an_intercept(self):
        state = snapshot(ball=(10, 0))
        place(state, "home_4", (6, 0))
        place(state, "away_4", (14, 0))
        raw = next(item for item in state["players"] if item["agentId"] == "home_4")
        raw["lastAction"] = "INTERCEPT"
        forward = view(4, state)
        race = perception.free_ball_race(forward)
        self.assertGreater(race.margin, 0)
        self.assertLess(race.margin, 0.15)
        self.assertTrue(race.should_intercept)
        self.assertIn("INTERCEPT", perception.allowed_commands(forward))

    def test_open_forward_receiver_does_not_follow_ball_backward(self):
        state = snapshot(ball=(-17, 6), owner_team=0, owner_player=3)
        place(state, "home_3", (-18, 6))
        place(state, "home_4", (-3, 2))
        for player_id, point in {0: (50, 20), 1: (35, -25), 2: (35, 25),
                                 3: (20, -25), 4: (20, 25)}.items():
            place(state, f"away_{player_id}", point)
        forward = view(4, state)
        self.assertTrue(perception.open_forward_receiver(forward, 4))
        target = perception.dynamic_anchor(forward, 4)
        self.assertGreater(target.x, forward.self_player.position.x)
        observation = perception.describe(forward, {})
        self.assertIn("открытый центральный адресат", observation)
        self.assertIn("Не отступай за мячом", observation)

    def test_high_quality_shot_remains_the_only_hard_command_guard(self):
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
