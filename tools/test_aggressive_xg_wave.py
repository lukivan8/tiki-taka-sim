from __future__ import annotations

import unittest

from live_match_server import discover_teams, load_strategy


class AggressiveXGWaveTests(unittest.TestCase):
    def test_team_is_discoverable_and_uses_high_start(self):
        team = discover_teams()["aggressive-xg-wave-g1"]
        self.assertEqual(team["formationPreset"], "1-1-1-2-high")

    def test_close_finish_threshold_and_crossover_prompt_are_installed(self):
        team = load_strategy(
            discover_teams()["aggressive-xg-wave-g1"],
            "aggressive-xg-wave-test",
        )
        self.assertEqual(team.perception_module.ATTACK_TWO_THIRDS_X, 32.0)
        for agent in team.agents.values():
            prompt = agent.afc_system_prompt
            self.assertIn("Aggressive xG Wave G1", prompt)
            self.assertIn("far-side switch", prompt)
            self.assertIn("passer immediately runs beyond", prompt)

    def test_g2_installs_inner_channel_geometry_and_quality_gate(self):
        team = load_strategy(
            discover_teams()["aggressive-xg-wave-g2"],
            "aggressive-xg-wave-g2-test",
        )
        self.assertIn("chance-quality repair", team.agents[3].afc_system_prompt)
        self.assertEqual(team.perception_module.dynamic_anchor.__name__, "attacking_anchor")
        self.assertEqual(
            team.perception_module.allowed_commands.__name__,
            "quality_allowed_commands",
        )

    def test_g3_uses_nova_parent_with_wave_geometry(self):
        team = load_strategy(
            discover_teams()["aggressive-xg-wave-g3"],
            "aggressive-xg-wave-g3-test",
        )
        self.assertIn("Aggressive xG Wave G3", team.agents[3].afc_system_prompt)
        self.assertEqual(team.perception_module.dynamic_anchor.__name__, "wave_anchor")
        self.assertEqual(
            team.perception_module.allowed_commands.__name__,
            "aggressive_allowed_commands",
        )

    def test_g4_installs_penetration_guard(self):
        team = load_strategy(
            discover_teams()["aggressive-xg-wave-g4"],
            "aggressive-xg-wave-g4-test",
        )
        self.assertIn("break the safe-pass loop", team.agents[2].afc_system_prompt)
        self.assertEqual(
            team.perception_module.allowed_commands.__name__,
            "penetration_allowed_commands",
        )

    def test_g5_installs_quality_filter_and_recovery(self):
        team = load_strategy(
            discover_teams()["aggressive-xg-wave-g5"],
            "aggressive-xg-wave-g5-test",
        )
        self.assertIn("quality and reliability repair", team.agents[4].afc_system_prompt)
        self.assertEqual(
            team.perception_module.allowed_commands.__name__,
            "quality_allowed_commands",
        )
        self.assertTrue(callable(team._recover_move))


if __name__ == "__main__":
    unittest.main()
