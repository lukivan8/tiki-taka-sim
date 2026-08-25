#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

from simulator import SimulationParameters, World


ARENA = Path(__file__).resolve().parents[1] / "arena/arena.yaml"


class SimulationV2Tests(unittest.TestCase):
    def world(self) -> World:
        return World(SimulationParameters.load_arena(ARENA)[1])

    def test_every_parameter_lives_in_one_strict_object(self):
        parameters = SimulationParameters.load_arena(ARENA)[1]
        self.assertEqual(set(parameters.values), SimulationParameters.REQUIRED_SECTIONS)
        broken = {section: dict(values) if isinstance(values, dict) else values
                  for section, values in parameters.values.items()}
        del broken["ball"]["controlRadius"]
        with self.assertRaisesRegex(ValueError, "controlRadius"):
            SimulationParameters(broken)

    def test_pass_leaves_kicker_and_reaches_teammate(self):
        world = self.world()
        kicker, receiver = (0, 2), (0, 3)
        world.players[kicker].position = [0.0, 0.0]
        world.players[receiver].position = [14.0, 0.0]
        for key, player in world.players.items():
            if key not in {kicker, receiver}:
                player.position = [-40.0 + key[1], 25.0 if key[0] else -25.0]
        world.ball.owner = kicker
        world.ball.position = world.players[kicker].position.copy()
        world.apply_commands({kicker: {"type": "PASS", "targetPlayerId": 3, "passType": "NORMAL"}})
        owners = []
        for _ in range(world.hz * 3):
            world.advance_one()
            owners.append(world.ball.owner)
            if world.ball.owner is not None:
                break
        self.assertNotIn(kicker, owners)
        self.assertEqual(world.ball.owner, receiver)
        self.assertEqual(world.metrics["completedPasses"], 1)

    def test_player_bodies_do_not_collapse_to_same_point(self):
        world = self.world()
        world.players[(0, 2)].position = [0.0, 0.0]
        world.players[(1, 2)].position = [0.0, 0.0]
        for _ in range(20):
            world.advance_one()
        left = world.players[(0, 2)].position
        right = world.players[(1, 2)].position
        self.assertGreaterEqual(((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5, 1.15)

    def test_every_formation_starts_in_its_own_half(self):
        parameters = SimulationParameters.load_arena(ARENA)[1]
        self.assertEqual(list(parameters.formation["presets"]), [
            "1-1-2", "1-2-1", "2-1-1", "2-2-0", "3-1", "1-3",
            "1-1-1-2-high",
        ])
        for home_preset in parameters.formation["presets"]:
            for away_preset in parameters.formation["presets"]:
                world = World(parameters, formation_presets=(home_preset, away_preset))
                self.assertTrue(all(player.position[0] <= 0.0
                                    for key, player in world.players.items() if key[0] == 0))
                self.assertTrue(all(player.position[0] >= 0.0
                                    for key, player in world.players.items() if key[0] == 1))

    def test_selected_formations_survive_goal_reset(self):
        parameters = SimulationParameters.load_arena(ARENA)[1]
        world = World(parameters, formation_presets=("3-1", "1-3"))
        world.ball.owner = None
        world.ball.position = [parameters.field["halfLength"] + 0.1, 0.0]
        world.ball.velocity = [1.0, 0.0]
        world.advance_one()
        self.assertEqual(world.score, [1, 0])
        self.assertEqual(world.players[(0, 1)].position, [-32.0, -15.0])
        self.assertEqual(world.players[(0, 4)].position, [-7.0, 0.0])
        self.assertEqual(world.players[(1, 1)].position, [31.0, 0.0])
        self.assertEqual(world.players[(1, 4)].position, [10.0, -17.0])

    def test_goalkeeper_reacts_each_physics_tick_and_saves_long_shot(self):
        world = self.world()
        shooter = (0, 2)
        world.players[shooter].position = [16.6, 0.0]
        world.ball.owner = shooter
        world.ball.position = world.players[shooter].position.copy()
        world.apply_commands({shooter: {"type": "SHOOT", "power": 1.0, "aimLocation": "BR"}})

        events = []
        for _ in range(world.hz * 3):
            events.extend(world.advance_one())
            if world.ball.owner == (1, 0) or world.score != [0, 0]:
                break

        self.assertEqual(world.score, [0, 0])
        self.assertEqual(world.ball.owner, (1, 0))
        self.assertEqual(world.metrics["goalkeeperSaves"], 1)
        self.assertTrue(any(event["type"] == "GOALKEEPER_SAVE" for event in events))
        self.assertGreater(world.players[(1, 0)].position[1], 0.5)

    def test_goalkeeper_does_not_chase_a_shot_that_is_clearly_wide(self):
        world = self.world()
        goalkeeper = world.players[(1, 0)]
        world.ball.owner = None
        world.ball.position = [20.0, 12.0]
        world.ball.velocity = [24.0, 0.0]
        start = goalkeeper.position.copy()
        for _ in range(world.hz):
            world.advance_one()
        self.assertAlmostEqual(goalkeeper.position[1], start[1], places=6)

    def test_goalkeepers_intercept_at_their_plane_symmetrically(self):
        cases = (
            # Home shoots diagonally from the lower flank at the away goal.
            ((0, 3), [25.73, -28.66], "TR", (1, 0), -1),
            # Exact X/Y mirror: away shoots from the upper flank at home.
            ((1, 3), [-25.73, 28.66], "TL", (0, 0), 1),
        )
        for shooter, position, aim, goalkeeper, expected_direction in cases:
            with self.subTest(goalkeeper=goalkeeper):
                world = self.world()
                world.players[shooter].position = position.copy()
                world.ball.owner = shooter
                world.ball.position = position.copy()
                world.apply_commands({shooter: {"type": "SHOOT", "power": 1.0,
                                                "aimLocation": aim}})
                for _ in range(round(world.hz * 0.65)):
                    world.advance_one()
                self.assertGreater(expected_direction * world.players[goalkeeper].position[1], 0.25)
                for _ in range(round(world.hz * 2.5)):
                    world.advance_one()
                    if world.ball.owner == goalkeeper or world.score != [0, 0]:
                        break
                self.assertEqual(world.score, [0, 0])
                self.assertEqual(world.ball.owner, goalkeeper)

    def test_goalkeeper_strategic_position_is_clamped_to_goal_mouth(self):
        world = self.world()
        goalkeeper = (1, 0)
        world.apply_commands({goalkeeper: {"type": "MOVE_TO", "target": {"x": 50, "y": -20},
                                           "sprint": False}})
        for _ in range(world.hz * 2):
            world.advance_one()
        self.assertGreaterEqual(world.players[goalkeeper].position[1],
                                -world.p.goalkeeping["maximumLateralPosition"] - 0.01)


if __name__ == "__main__":
    unittest.main()
