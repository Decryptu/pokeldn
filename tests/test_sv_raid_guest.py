"""Offline checks for the generated Scarlet/Violet raid guest path."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bin"))

from pokeldn.ldn import channel_table, reliable5
from pokeldn.sv import reference, streams

from sv_join import (PROTO_BROADCAST_RELIABLE, RAID_HANDLER_KEYS,
                     ANONYMOUS_PLAYER_ID, apply_raid_disconnect_default,
                     apply_raid_guest_identity, build_parser,
                     raid_disconnect_matches, split_raid_channel_table)


class RaidGuestTests(unittest.TestCase):
    def test_raid_guest_uses_generated_session_and_shared_application_identity(self):
        args = build_parser().parse_args([
            "--raid-guest", "--trainer-name", "POKELDN"])
        apply_raid_guest_identity(
            args, lambda count: bytes.fromhex("ff1122334455"))
        self.assertEqual(args.mac, "fe:11:22:33:44:55")
        self.assertEqual(args.join_player_id, ANONYMOUS_PLAYER_ID)
        self.assertEqual(args.join_player_name, "POKELDN")
        self.assertEqual(args.record_set, reference.RECORDS)

    def test_generated_raid_guest_selects_the_mode(self):
        generated = build_parser().parse_args(["--raid-guest"])
        self.assertTrue(generated.raid_guest)

    def test_raid_disconnect_option_defaults_off_and_accepts_sequence(self):
        defaults = build_parser().parse_args([])
        self.assertIsNone(defaults.raid_disconnect_after_seq)
        self.assertIsNone(defaults.raid_disconnect_after_prefix)
        self.assertFalse(defaults.raid_stay_after_battle_transition)
        self.assertEqual(defaults.raid_disconnect_delay, 0.0)
        configured = build_parser().parse_args([
            "--raid-disconnect-after-seq", "20", "--raid-disconnect-delay", "5"])
        self.assertEqual(configured.raid_disconnect_after_seq, 20)
        self.assertEqual(configured.raid_disconnect_delay, 5.0)
        by_type = build_parser().parse_args([
            "--raid-disconnect-after-prefix", "80349301"])
        self.assertEqual(by_type.raid_disconnect_after_prefix, bytes.fromhex("80349301"))

    def test_raid_disconnect_only_matches_host_raid_application_record(self):
        message = {"flags": reliable5.FLAG_APPLICATION_DATA, "sequence_id": 12}
        self.assertTrue(raid_disconnect_matches(
            12, None, PROTO_BROADCAST_RELIABLE, 0, message))
        self.assertFalse(raid_disconnect_matches(
            20, None, PROTO_BROADCAST_RELIABLE, 0, message))
        self.assertTrue(raid_disconnect_matches(
            None, bytes.fromhex("80349301"), PROTO_BROADCAST_RELIABLE, 0, message,
            bytes.fromhex("8034930101")))
        self.assertFalse(raid_disconnect_matches(12, None, 0x81, 0, message))
        self.assertFalse(raid_disconnect_matches(
            12, None, PROTO_BROADCAST_RELIABLE, 1, message))
        self.assertFalse(raid_disconnect_matches(
            12, None, PROTO_BROADCAST_RELIABLE, 0,
            {"flags": 0, "sequence_id": 12}))

    def test_raid_guest_defaults_to_stable_battle_transition_cutoff(self):
        args = build_parser().parse_args(["--raid-guest"])
        apply_raid_disconnect_default(args)
        self.assertEqual(args.raid_disconnect_after_prefix, bytes.fromhex("80349301"))
        args = build_parser().parse_args([
            "--raid-guest", "--raid-stay-after-battle-transition"])
        apply_raid_disconnect_default(args)
        self.assertIsNone(args.raid_disconnect_after_prefix)

    def test_shared_identity_name_can_be_productized(self):
        first_record = Path(reference.RECORDS, "001.bin").read_bytes()
        first = streams.decompress(first_record)
        self.assertEqual(len(first), 1395)
        self.assertEqual(first[0], 1)
        self.assertEqual(reference.player_name(
            reference.named_record(first_record, "POKELDN")), "POKELDN")

    def test_combined_channel_table_splits_base_and_raid_keys(self):
        base_keys = [(bytes([index]) * 8, True) for index in range(1, 5)]
        combined = channel_table.build(base_keys + [(key, True) for key in RAID_HANDLER_KEYS])
        base, update = split_raid_channel_table(
            streams.compress(combined), reliable5.FLAG_ZLIB)
        self.assertEqual(len(channel_table.parse(base)), 4)
        parsed = channel_table.parse(update)
        self.assertEqual({key for key, opened in parsed if opened}, RAID_HANDLER_KEYS)


if __name__ == "__main__":
    unittest.main()
