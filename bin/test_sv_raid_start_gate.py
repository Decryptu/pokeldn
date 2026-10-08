"""Startup ordering checks for the retail Scarlet/Violet raid host."""

import unittest

from sv_raid_start_gate import RaidStartGate


class RaidStartGateTests(unittest.TestCase):
    def test_first_replay_waits_for_guest_lobby(self):
        gate = RaidStartGate()

        self.assertEqual(gate.requirement(1), "guest_lobby")
        self.assertFalse(gate.allowed(1, 10.0))

        self.assertEqual(
            gate.observe(0x80, 0, bytes.fromhex("80332e01"), 10.0),
            "guest_lobby",
        )
        self.assertFalse(gate.allowed(1, 10.049))
        self.assertTrue(gate.allowed(1, 10.05))

    def test_later_startup_requirements_are_unchanged(self):
        gate = RaidStartGate()

        self.assertEqual(gate.requirement(11), "session_ack")
        self.assertEqual(gate.requirement(13), "load_6e")
        self.assertEqual(gate.requirement(14), "load_73")
        self.assertEqual(gate.requirement(15), "battle_93")


if __name__ == "__main__":
    unittest.main()
