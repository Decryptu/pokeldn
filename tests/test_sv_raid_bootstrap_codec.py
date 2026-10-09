"""Offline regression tests for generated SV raid bootstraps."""

import hashlib
import struct
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BIN))

from pokeldn import gen9
from sv_raid_bootstrap_codec import (
    EXPECTED_RAW_SIZE,
    MAX_REWARD_ROWS,
    RAIDPOINT_OFFSET,
    RAIDPOINT_SIZE,
    build_application,
    build_raid_boss_pk9,
    build_raid_point,
    build_seed_bootstrap_raw,
    decode_application,
    encode_application,
    extract_lobby_pokemon,
    normalize_rewards,
    patch_bootstrap_participant,
)


class RaidBootstrapCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = build_seed_bootstrap_raw(0xFDAE7B7D)
        cls.application = build_application(
            cls.raw, message_value=0x018B, header_tail=bytes.fromhex("01020304"))

    def test_decode_matches_ghidra_layout(self):
        raw = decode_application(self.application)
        self.assertEqual(len(raw), EXPECTED_RAW_SIZE)
        self.assertEqual(raw[RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + 10], b"RaidPoint_")

    def test_recompression_round_trip(self):
        rebuilt = encode_application(self.application, self.raw)
        self.assertEqual(decode_application(rebuilt), self.raw)

    def test_generated_application_envelope_round_trip(self):
        application = build_application(
            self.raw, message_value=0x018B, header_tail=bytes.fromhex("01020304"))
        self.assertEqual(application[:18], bytes.fromhex(
            "80332f018b0102000000a00a000001020304"))
        self.assertEqual(decode_application(application), self.raw)

    def test_seed_build_reproduces_complete_retail_growlithe_boss(self):
        from pokeldn.sv import raid_generation

        raw = build_seed_bootstrap_raw(
            0xBD13FB43, point_name="RaidPoint_12_1_11")
        boss = slice(4 * gen9.SIZE_PARTY, 5 * gen9.SIZE_PARTY)
        generated = raid_generation.generate_seed_raid(0xBD13FB43)
        self.assertEqual(raw[boss], build_raid_boss_pk9(generated["profile"]))
        self.assertEqual(
            hashlib.sha256(raw[boss]).hexdigest(),
            "fa48396b91413a0e54b86a074b3b10dcf077d8633e9d5a45c7466830325f66c3")
        for slot in range(4):
            plain = gen9.load(raw[slot * gen9.SIZE_PARTY:(slot + 1) * gen9.SIZE_PARTY])
            self.assertEqual(gen9.read(plain)["species"], 0)

    def test_seed_build_uses_retail_empty_participant_records(self):
        generated = build_seed_bootstrap_raw(0xBD13FB43)
        retail_empty = generated[2 * gen9.SIZE_PARTY:3 * gen9.SIZE_PARTY]
        self.assertEqual(
            generated[3 * gen9.SIZE_PARTY:4 * gen9.SIZE_PARTY], retail_empty)
        self.assertEqual(
            hashlib.sha256(retail_empty).hexdigest(),
            "befa78ce3efc6035ef511bfab95dd962e1019612e7b9bef80c85fb7955e36ae4")
        self.assertEqual(gen9.read(gen9.load(retail_empty))["level"], 1)

    def test_seed_build_reproduces_understood_growlithe_raidpoint_fields(self):
        raw = build_seed_bootstrap_raw(
            0xBD13FB43, point_name="RaidPoint_12_1_11")
        generated = raw[RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + RAIDPOINT_SIZE]
        self.assertEqual(generated[:0x30], bytes.fromhex(
            "52616964506f696e745f31325f315f3131000000000000004000000000000000"
            "02000000000000000100000014000000"))
        self.assertEqual(struct.unpack_from("<I", generated, 0x4C)[0], 500)
        self.assertEqual(generated[0x50:0xE0], bytes(0x90))
        self.assertEqual(
            struct.unpack_from("<7I", generated, 0x3B8),
            (2, 58, 0, 0, 20, 0, 11))
        expected_rewards = (
            (1125, 3), (1961, 2), (566, 1), (1961, 1), (88, 1),
            (1961, 1), (155, 1), (566, 1), (88, 1),
        )
        for index, item_quantity in enumerate(expected_rewards):
            marker, item, quantity, reserved = struct.unpack_from(
                "<IIII", generated, 0xE0 + index * 16)
            self.assertEqual((item, quantity, reserved), (*item_quantity, 0))
            self.assertEqual(marker, 0)

    def test_four_star_action_profile_uses_generated_extra_moves(self):
        raw = build_seed_bootstrap_raw(
            0xFDAE7B7D, point_name="RaidPoint_10_01_07")
        point = raw[RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + RAIDPOINT_SIZE]
        self.assertEqual(struct.unpack_from("<IIII", point, 0x20), (4, 0, 1, 45))
        self.assertEqual(struct.unpack_from("<I", point, 0x4C)[0], 1200)
        self.assertEqual(struct.unpack_from("<4I", point, 0x50), (60, 40, 9999, 30))
        self.assertEqual(struct.unpack_from("<4I", point, 0x80), (106, 2, 2, 60))
        self.assertEqual(struct.unpack_from("<4I", point, 0x90), (0, 3, 1, 40))
        self.assertEqual(struct.unpack_from("<4I", point, 0xA0), (106, 0, 0, 0))
        self.assertEqual(struct.unpack_from("<4I", point, 0x210), (5, 0, 0, 0))
        self.assertEqual(
            struct.unpack_from("<7I", point, 0x3B8),
            (4, 205, 0, 0, 45, 0, 1))

    def test_generated_bootstrap_accepts_exact_rewards(self):
        rewards = normalize_rewards([(15, 500), (1, 7)])
        raw = build_seed_bootstrap_raw(0xFDAE7B7D, exact_rewards=rewards)
        point = raw[RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + RAIDPOINT_SIZE]
        self.assertEqual(struct.unpack_from("<IIII", point, 0xE0), (0, 15, 500, 0))
        self.assertEqual(struct.unpack_from("<IIII", point, 0xF0), (0, 1, 7, 0))
        self.assertEqual(point[0x100:0x3B8], bytes(0x3B8 - 0x100))

    def test_exact_rewards_use_the_full_generated_reward_region(self):
        rewards = [(index + 1, 1) for index in range(MAX_REWARD_ROWS)]
        point = build_seed_bootstrap_raw(
            0xFDAE7B7D, exact_rewards=rewards)[
                RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + RAIDPOINT_SIZE]
        self.assertEqual(
            struct.unpack_from("<IIII", point, 0xE0 + (MAX_REWARD_ROWS - 1) * 16),
            (0, MAX_REWARD_ROWS, 1, 0))
        with self.assertRaisesRegex(ValueError, f"at most {MAX_REWARD_ROWS}"):
            normalize_rewards(rewards + [(999, 1)])

    def test_exact_rewards_reject_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "quantity"):
            normalize_rewards([(15, 0)])
        with self.assertRaisesRegex(ValueError, "item_id"):
            normalize_rewards([(0, 1)])

    def test_all_standard_star_profiles_and_black_six_star_are_generated(self):
        from pokeldn.sv import raid_generation

        cases = (
            (9, "beginning", "standard", 1),
            (0, "beginning", "standard", 2),
            (0, "3star", "standard", 3),
            (0, "4star", "standard", 4),
            (0, "5star", "standard", 5),
            (0, "6star", "black", 6),
        )
        for seed, progress, content, stars in cases:
            with self.subTest(stars=stars):
                raid = raid_generation.generate_seed_raid(
                    seed, progress=progress, content=content)
                point = build_raid_point(raid)
                self.assertEqual(raid["metadata"]["stars"], stars)
                self.assertEqual(
                    struct.unpack_from("<37I", point, 0x4C),
                    tuple(raid["encounter"]["boss_desc"]))

    def test_missing_boss_description_is_rejected(self):
        from pokeldn.sv import raid_generation

        raid = raid_generation.generate_seed_raid(0xBD13FB43)
        del raid["encounter"]["boss_desc"]
        with self.assertRaisesRegex(ValueError, "missing its 37-word boss_desc"):
            build_raid_point(raid)

    def test_guest_lobby_pokemon_patches_bootstrap_slot_one(self):
        from pokeldn.sv import raid_generation

        guest = build_raid_boss_pk9(
            raid_generation.generate_seed_raid(0xBD13FB43)["profile"])
        lobby_header = bytes.fromhex("80332e010200000000005801000000000000")
        self.assertEqual(extract_lobby_pokemon(lobby_header + guest), guest)
        boundary = 1395
        events = [
            (0.2, 11, 0x02, 11, self.application[:boundary]),
            (0.3, 12, 0x04, 11, self.application[boundary:]),
        ]
        replacement = build_raid_boss_pk9(
            raid_generation.generate_seed_raid(0xFDAE7B7D)["profile"])
        changed = patch_bootstrap_participant(events, 1, replacement)
        changed_raw = decode_application(changed[0][4] + changed[1][4])
        self.assertEqual(
            changed_raw[gen9.SIZE_PARTY:2 * gen9.SIZE_PARTY], replacement)
        self.assertEqual(changed_raw[:gen9.SIZE_PARTY], self.raw[:gen9.SIZE_PARTY])
        self.assertEqual(changed_raw[2 * gen9.SIZE_PARTY:], self.raw[2 * gen9.SIZE_PARTY:])


if __name__ == "__main__":
    unittest.main()
