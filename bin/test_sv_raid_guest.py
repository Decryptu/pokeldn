"""Offline checks for the bundled retail Scarlet/Violet raid guest fixture."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pokeldn.ldn import channel_table, pia_connect, reliable5
from pokeldn.sv import pokemon, raid_guest, reference, streams

from sv_join import (PROTO_BROADCAST_RELIABLE, RAID_HANDLER_KEYS,
                     apply_raid_disconnect_default, build_parser,
                     raid_disconnect_matches, split_raid_channel_table)


class RaidGuestFixtureTests(unittest.TestCase):
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
        args = build_parser().parse_args(["--raid-guest-replay"])
        apply_raid_disconnect_default(args)
        self.assertEqual(args.raid_disconnect_after_prefix, bytes.fromhex("80349301"))
        args = build_parser().parse_args([
            "--raid-guest-replay", "--raid-stay-after-battle-transition"])
        apply_raid_disconnect_default(args)
        self.assertIsNone(args.raid_disconnect_after_prefix)

    def test_session_identity_is_coherent(self):
        fixture = raid_guest.load_fixture()
        response = pia_connect.parse_session_join_response_v11(
            bytes.fromhex(fixture["session_join_response"]))
        self.assertEqual(response["status_name"], "accepted")
        mac = bytes.fromhex(fixture["station_mac"].replace(":", ""))
        self.assertEqual(response["console_constant_id"], pia_connect.ldn_constant_id(mac))
        self.assertEqual(len(raid_guest.player_id()), 16)

    def test_identity_is_complete_and_name_can_be_productized(self):
        records = raid_guest.identity_records()
        self.assertEqual([seq for seq, _ in records], list(range(1, 47)))
        first = streams.decompress(records[0][1])
        self.assertEqual(len(first), 1395)
        self.assertEqual(first[0], 1)
        self.assertEqual(reference.player_name(
            reference.named_record(records[0][1], "POKELDN")), "POKELDN")

    def test_lobby_and_ready_transition_match_the_capture(self):
        records = raid_guest.lobby_records()
        self.assertEqual([seq for seq, *_ in records], [1, 2])
        first = streams.decompress(records[0][2])
        self.assertEqual(first[:4], bytes.fromhex("80332d01"))
        self.assertEqual(records[1][2][:4], bytes.fromhex("80332e01"))
        ready = raid_guest.state_payload(1, records)
        captured = raid_guest.load_fixture()["ready"]
        captured_payload = bytes.fromhex(captured["payload"])
        captured_plain = (streams.decompress(captured_payload)
                          if captured["flags"] & reliable5.FLAG_ZLIB else captured_payload)
        self.assertEqual(ready, captured_plain)
        start = raid_guest.state_payload(
            0x0d, records, previous_counter=int.from_bytes(ready[4:8], "little"))
        self.assertEqual(int.from_bytes(start[4:8], "little"), 4)
        self.assertEqual(int.from_bytes(start[34:38], "little"), 0x0d)

    def test_lobby_pokemon_is_the_captured_gallade(self):
        fields = pokemon.read(raid_guest.lobby_pokemon())
        self.assertEqual(fields["species"], 475)
        self.assertEqual(fields["level"], 98)

    def test_custom_lobby_pokemon_replaces_only_the_pk9(self):
        records = raid_guest.lobby_records()
        original_message = records[1][2]
        custom = pokemon.write(raid_guest.lobby_pokemon(records), species=132,
                               nickname="RaidBot", current_hp=123)
        updated = raid_guest.with_lobby_pokemon(records, pokemon.encrypt(custom))

        self.assertEqual(updated[0], records[0])
        self.assertEqual(updated[1][:2], records[1][:2])
        self.assertEqual(updated[1][2][:raid_guest.LOBBY_POKEMON_HEADER_SIZE],
                         original_message[:raid_guest.LOBBY_POKEMON_HEADER_SIZE])
        fields = pokemon.read(raid_guest.lobby_pokemon(updated))
        self.assertEqual((fields["species"], fields["nickname"], fields["current_hp"]),
                         (132, "RaidBot", 123))
        self.assertEqual(raid_guest.state_payload(1, updated),
                         raid_guest.state_payload(1, records))

    def test_custom_lobby_pokemon_requires_a_party_pk9(self):
        with self.assertRaisesRegex(ValueError, "344-byte party PK9"):
            raid_guest.with_lobby_pokemon(raid_guest.lobby_records(), bytes(328))

    def test_captured_channel_table_splits_base_and_raid_keys(self):
        row = raid_guest.load_fixture()["channel_table"]
        base, update = split_raid_channel_table(
            bytes.fromhex(row["payload"]), row["flags"])
        self.assertEqual(len(channel_table.parse(base)), 4)
        parsed = channel_table.parse(update)
        self.assertEqual({key for key, opened in parsed if opened}, RAID_HANDLER_KEYS)


if __name__ == "__main__":
    unittest.main()
