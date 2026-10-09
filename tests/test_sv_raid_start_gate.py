"""Startup ordering checks for the retail Scarlet/Violet raid host."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

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
        self.assertEqual(gate.requirement(13), "load_6e/load_73")
        self.assertEqual(gate.requirement(14), "load_73")
        self.assertEqual(gate.requirement(15), "battle_93")

    def test_sequence_13_accepts_either_retail_load_marker(self):
        for marker in ("32016e00", "32017300"):
            with self.subTest(marker=marker):
                gate = RaidStartGate()
                gate.sent.add(12)
                self.assertEqual(gate.observe(0x80, 0, bytes.fromhex(marker), 20.0),
                                 "load_6e" if marker == "32016e00" else "load_73")
                self.assertFalse(gate.allowed(13, 20.049))
                self.assertTrue(gate.allowed(13, 20.05))


if __name__ == "__main__":
    unittest.main()
