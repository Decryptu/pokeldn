"""Offline regression tests for the plaintext SV raid bootstrap codec."""

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
    AVALUGG_BONUS_RECORDS,
    AVALUGG_REWARD_RECORDS,
    AVALUGG_VISIBLE_REWARD_RECORDS,
    AVALUGG_RAIDPOINT,
    AVALUGG_RAIDPOINT_OFFSET,
    EXPECTED_RAW_SIZE,
    RAIDPOINT_OFFSET,
    RAIDPOINT_SIZE,
    build_application,
    build_raid_point,
    build_seed_bootstrap_raw,
    decode_application,
    encode_reward_profile_application,
    encode_application,
    extract_lobby_pokemon,
    extract_retail_bootstrap,
    parse_reward_profile,
    patch_avalugg_reward_profile,
    patch_bootstrap_participant,
    patch_host_player_pokemon,
    replace_bootstrap_raw,
)


RESEARCH = ROOT / "docs" / "research" / "sv" / "fixtures"
DONOR = RESEARCH / "sv_raid_reward_donor.bin"
GROWLITHE_CAPTURE = RESEARCH / "tera_raid_retail_victory_full.jsonl"


class RaidBootstrapCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = DONOR.read_bytes()
        cls.growlithe_raw = decode_application(extract_retail_bootstrap(GROWLITHE_CAPTURE))

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

    def test_donor_free_application_envelope_round_trip(self):
        raw = decode_application(self.application)
        application = build_application(
            raw, message_value=0x018B, header_tail=bytes.fromhex("01020304"))
        self.assertEqual(application[:18], bytes.fromhex(
            "80332f018b0102000000a00a000001020304"))
        self.assertEqual(decode_application(application), raw)

    def test_seed_build_reproduces_complete_retail_growlithe_boss(self):
        raw = build_seed_bootstrap_raw(
            0xBD13FB43, point_name="RaidPoint_12_1_11")
        self.assertEqual(len(raw), EXPECTED_RAW_SIZE)
        boss = slice(4 * gen9.SIZE_PARTY, 5 * gen9.SIZE_PARTY)
        self.assertEqual(raw[boss], self.growlithe_raw[boss])
        for slot in range(4):
            plain = gen9.load(raw[slot * gen9.SIZE_PARTY:(slot + 1) * gen9.SIZE_PARTY])
            self.assertEqual(gen9.read(plain)["species"], 0)

    def test_seed_build_uses_retail_empty_participant_records(self):
        generated = build_seed_bootstrap_raw(0xBD13FB43)
        donor = decode_application(self.application)
        retail_empty = donor[2 * gen9.SIZE_PARTY:3 * gen9.SIZE_PARTY]
        self.assertEqual(
            generated[2 * gen9.SIZE_PARTY:3 * gen9.SIZE_PARTY], retail_empty)
        self.assertEqual(
            generated[3 * gen9.SIZE_PARTY:4 * gen9.SIZE_PARTY], retail_empty)
        self.assertEqual(gen9.read(gen9.load(retail_empty))["level"], 1)

    def test_seed_build_reproduces_understood_growlithe_raidpoint_fields(self):
        raw = build_seed_bootstrap_raw(
            0xBD13FB43, point_name="RaidPoint_12_1_11")
        generated = raw[RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + RAIDPOINT_SIZE]
        captured = self.growlithe_raw[RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + RAIDPOINT_SIZE]
        self.assertEqual(generated[:0x30], captured[:0x30])
        self.assertEqual(struct.unpack_from("<I", generated, 0x4C)[0], 500)
        self.assertEqual(generated[0x50:0xE0], bytes(0x90))
        self.assertEqual(generated[0x3B8:0x3D4], captured[0x3B8:0x3D4])
        expected_rewards = (
            (1125, 3), (1961, 2), (566, 1), (1961, 1), (88, 1),
            (1961, 1), (155, 1), (566, 1), (88, 1),
        )
        for index, item_quantity in enumerate(expected_rewards):
            marker, item, quantity, reserved = struct.unpack_from(
                "<IIII", generated, 0xE0 + index * 16)
            self.assertEqual((item, quantity, reserved), (*item_quantity, 0))
            self.assertEqual(marker, 0)
        self.assertEqual(
            generated[0xE0 + len(expected_rewards) * 16:0x3B8],
            bytes(0x3B8 - 0xE0 - len(expected_rewards) * 16))

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

    def test_generated_bootstrap_accepts_an_exact_reward_profile(self):
        profile = parse_reward_profile({
            "format": "pokeldn.sv.raid-rewards.v1",
            "template": "violet-4.0.0-c72e1d7f-avalugg",
            "mode": "exact",
            "rewards": [
                {"item_id": 15, "quantity": 500},
                {"item_id": 1, "quantity": 7},
            ],
        })
        raw = build_seed_bootstrap_raw(0xFDAE7B7D, reward_profile=profile)
        point = raw[RAIDPOINT_OFFSET:RAIDPOINT_OFFSET + RAIDPOINT_SIZE]
        self.assertEqual(
            struct.unpack_from("<IIII", point, 0xE0), (0, 15, 500, 0))
        self.assertEqual(
            struct.unpack_from("<IIII", point, 0xF0), (0, 1, 7, 0))
        self.assertEqual(point[0x100:0x3B8], bytes(0x3B8 - 0x100))

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

    def test_generated_raw_replaces_every_plaintext_byte_but_keeps_envelope(self):
        original = self.application
        generated = build_seed_bootstrap_raw(
            0xBD13FB43, point_name="RaidPoint_12_1_11")
        boundary = 1395
        events = [
            (0, 11, 0x02, 0, original[:boundary]),
            (0, 12, 0x04, 0, original[boundary:]),
        ]
        changed = replace_bootstrap_raw(events, generated)
        rebuilt = b"".join(event[4] for event in changed)
        self.assertEqual(rebuilt[:18], original[:18])
        self.assertEqual(decode_application(rebuilt), generated)

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

    def test_custom_host_pokemon_replaces_lobby_and_bootstrap_slot_zero(self):
        original_raw = decode_application(self.application)
        custom = original_raw[gen9.SIZE_PARTY:2 * gen9.SIZE_PARTY]
        lobby_header = bytes.fromhex("80332e010701000000005801000000000000")
        lobby = lobby_header + original_raw[:gen9.SIZE_PARTY]
        boundary = 1395
        events = [
            (0.1, 3, 0x07, 1, lobby),
            (0.2, 11, 0x02, 11, self.application[:boundary]),
            (0.3, 12, 0x04, 11, self.application[boundary:]),
        ]

        changed = patch_host_player_pokemon(events, custom)
        self.assertEqual([event[:4] for event in changed],
                         [event[:4] for event in events])
        changed_lobby = changed[0][4]
        self.assertEqual(changed_lobby[:len(lobby_header)], lobby_header)
        lobby_plain = gen9.load(changed_lobby[len(lobby_header):])
        self.assertEqual(gen9.read(lobby_plain)["species"], 475)

        changed_application = changed[1][4] + changed[2][4]
        changed_raw = decode_application(changed_application)
        self.assertEqual(
            gen9.load(changed_raw[:gen9.SIZE_PARTY]), lobby_plain)
        # Guest slots, empty slots, boss, RaidPoint, and rewards are untouched.
        self.assertEqual(changed_raw[gen9.SIZE_PARTY:],
                         original_raw[gen9.SIZE_PARTY:])

    def test_custom_host_pokemon_requires_a_party_pk9(self):
        with self.assertRaisesRegex(ValueError, "344-byte party PK9"):
            patch_host_player_pokemon([], bytes(gen9.SIZE_STORED))

    def test_guest_lobby_pokemon_patches_bootstrap_slot_one(self):
        original_raw = decode_application(self.application)
        guest = original_raw[gen9.SIZE_PARTY:2 * gen9.SIZE_PARTY]
        lobby_header = bytes.fromhex("80332e010200000000005801000000000000")
        self.assertEqual(extract_lobby_pokemon(lobby_header + guest), guest)
        boundary = 1395
        events = [
            (0.2, 11, 0x02, 11, self.application[:boundary]),
            (0.3, 12, 0x04, 11, self.application[boundary:]),
        ]
        replacement = original_raw[:gen9.SIZE_PARTY]
        changed = patch_bootstrap_participant(events, 1, replacement)
        changed_raw = decode_application(changed[0][4] + changed[1][4])
        self.assertEqual(
            changed_raw[gen9.SIZE_PARTY:2 * gen9.SIZE_PARTY], replacement)
        self.assertEqual(changed_raw[:gen9.SIZE_PARTY], original_raw[:gen9.SIZE_PARTY])
        self.assertEqual(changed_raw[2 * gen9.SIZE_PARTY:],
                         original_raw[2 * gen9.SIZE_PARTY:])


if __name__ == "__main__":
    unittest.main()
