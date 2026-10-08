"""Offline regression tests for the plaintext SV raid bootstrap codec."""

import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sv_raid_bootstrap_codec import (
    AVALUGG_BONUS_RECORDS,
    AVALUGG_REWARD_RECORDS,
    AVALUGG_VISIBLE_REWARD_RECORDS,
    AVALUGG_RAIDPOINT,
    AVALUGG_RAIDPOINT_OFFSET,
    EXPECTED_RAW_SIZE,
    decode_application,
    encode_reward_profile_application,
    encode_application,
    parse_reward_profile,
    patch_avalugg_reward_profile,
)


DONOR = Path(__file__).with_name("sv_raid_reward_donor.bin")


class RaidBootstrapCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = DONOR.read_bytes()

    def test_decode_matches_ghidra_layout(self):
        raw = decode_application(self.application)
        self.assertEqual(len(raw), EXPECTED_RAW_SIZE)
        self.assertEqual(
            raw[AVALUGG_RAIDPOINT_OFFSET:
                AVALUGG_RAIDPOINT_OFFSET + len(AVALUGG_RAIDPOINT)],
            AVALUGG_RAIDPOINT)

    def test_recompression_round_trip(self):
        raw = decode_application(self.application)
        rebuilt = encode_application(self.application, raw)
        self.assertEqual(decode_application(rebuilt), raw)

    def test_product_profile_encodes_exact_quick_ball_list(self):
        profile = parse_reward_profile({
            "format": "pokeldn.sv.raid-rewards.v1",
            "template": "violet-4.0.0-c72e1d7f-avalugg",
            "mode": "exact",
            "name": "test",
            "rewards": [{"item_id": 15, "quantity": 500}],
        })
        changed = encode_reward_profile_application(self.application, profile)
        original_raw = decode_application(self.application)
        raw = decode_application(changed)
        first_offset = AVALUGG_VISIBLE_REWARD_RECORDS[0][0]
        self.assertEqual(
            struct.unpack_from("<IIII", raw, first_offset), (0, 15, 500, 0))
        cleared = (AVALUGG_VISIBLE_REWARD_RECORDS[1:]
                   + tuple(record for record in AVALUGG_REWARD_RECORDS
                           if record not in AVALUGG_VISIBLE_REWARD_RECORDS)
                   + AVALUGG_BONUS_RECORDS)
        for offset, *_ in cleared:
            self.assertEqual(struct.unpack_from("<IIII", raw, offset), (0, 0, 0, 0))
        editable = set()
        for offset, *_ in AVALUGG_REWARD_RECORDS + AVALUGG_BONUS_RECORDS:
            editable.update(range(offset, offset + 16))
        self.assertTrue(all(
            original == encoded
            for index, (original, encoded) in enumerate(zip(original_raw, raw))
            if index not in editable))

    def test_product_profile_replaces_replay_fragments(self):
        profile = parse_reward_profile({
            "format": "pokeldn.sv.raid-rewards.v1",
            "template": "violet-4.0.0-c72e1d7f-avalugg",
            "mode": "exact",
            "rewards": [{"item_id": 15, "quantity": 500}],
        })
        boundary = 1395
        events = [
            (0, 11, 0x02, 0, self.application[:boundary]),
            (0, 12, 0x04, 0, self.application[boundary:]),
        ]
        changed = patch_avalugg_reward_profile(events, profile)
        application = b"".join(event[4] for event in changed)
        raw = decode_application(application)
        self.assertEqual(
            struct.unpack_from("<IIII", raw, AVALUGG_VISIBLE_REWARD_RECORDS[0][0]),
            (0, 15, 500, 0))

    def test_product_profile_rejects_invalid_schema(self):
        with self.assertRaisesRegex(ValueError, "at most 16"):
            parse_reward_profile({
                "format": "pokeldn.sv.raid-rewards.v1",
                "template": "violet-4.0.0-c72e1d7f-avalugg",
                "mode": "exact",
                "rewards": [{"item_id": 15, "quantity": 1}] * 17,
            })
        with self.assertRaisesRegex(ValueError, "quantity"):
            parse_reward_profile({
                "format": "pokeldn.sv.raid-rewards.v1",
                "template": "violet-4.0.0-c72e1d7f-avalugg",
                "mode": "exact",
                "rewards": [{"item_id": 15, "quantity": 0}],
            })


if __name__ == "__main__":
    unittest.main()
