"""Offline checks for the production Scarlet/Violet raid host entry point."""

import argparse
from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bin"))

from sv_raid_host import (
    _profile_value, build_parser, host_arguments, mac_address, main, player_id,
    synthetic_mac, synthetic_player_id,
)
from pokeldn.app.command import accepted


class RaidHostTests(unittest.TestCase):
    def test_synthetic_network_identity_has_retail_shape(self):
        mac = synthetic_mac(lambda count: bytes.fromhex("ff1122334455"))
        pid = synthetic_player_id()
        self.assertEqual(mac, "fe:11:22:33:44:55")
        self.assertEqual(pid, "00000000000000010000000000000000")
        self.assertEqual(mac_address(mac), mac)
        self.assertEqual(player_id(pid), pid)

    def test_identity_parser_rejects_multicast_mac_and_wrong_id_size(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            mac_address("01:00:00:00:00:00")
        with self.assertRaises(argparse.ArgumentTypeError):
            player_id("1000")
        with self.assertRaises(ValueError):
            synthetic_mac(lambda count: b"\0")

    def test_parser_accepts_ordered_rewards(self):
        args = build_parser().parse_args([
            "--raid-seed", "000F34C3", "--raid-player-pokemon", "host.pk9",
            "--reward", "1:1", "--reward", "50:10", "--capture", "run.jsonl"])
        self.assertEqual(args.raid_seed, 0x000F34C3)
        self.assertEqual(args.raid_player_pokemon, "host.pk9")
        self.assertEqual(args.reward, [(1, 1), (50, 10)])
        self.assertEqual(args.capture, "run.jsonl")

    def test_parser_accepts_generated_bootstrap_mode(self):
        args = build_parser().parse_args([
            "--raid-seed", "BD13FB43", "--raid-player-pokemon", "host.pk9",
            "--generated-bootstrap", "--raid-version", "scarlet",
            "--raid-map", "kitakami", "--raid-progress", "6star",
            "--raid-content", "black"])
        self.assertTrue(args.generated_bootstrap)
        self.assertEqual(
            (args.raid_version, args.raid_map, args.raid_progress, args.raid_content),
            ("scarlet", "kitakami", "6star", "black"))

    def test_gui_can_discover_capture_support(self):
        self.assertIn("--capture", accepted("bin/sv_raid_host.py"))

    def test_profile_preserves_order_and_quantities(self):
        value = _profile_value([(1, 1), (50, 10)])
        self.assertEqual(value["rewards"], [
            {"item_id": 1, "quantity": 1},
            {"item_id": 50, "quantity": 10},
        ])

    def test_host_configuration_uses_product_defaults(self):
        args = host_arguments(
            0x000F34C3, Path("profile.json"), "keys", 600,
            player_pokemon="host.pk9", capture="run.jsonl",
            mac="02:11:22:33:44:55",
            host_player_id="1000000102030405060708090a0b0c0d")
        self.assertEqual(args[args.index("--raid-seed") + 1], "000F34C3")
        self.assertEqual(args[args.index("--raid-reward-profile") + 1], "profile.json")
        self.assertEqual(args[args.index("--raid-player-pokemon") + 1], "host.pk9")
        self.assertEqual(args[args.index("--capture") + 1], "run.jsonl")
        self.assertEqual(args[args.index("--mac") + 1], "02:11:22:33:44:55")
        self.assertEqual(
            args[args.index("--host-player-id") + 1],
            "1000000102030405060708090a0b0c0d")
        self.assertEqual(args[args.index("--host-player-name") + 1], "POKELDN")
        self.assertEqual(args[args.index("--trainer-name") + 1], "POKELDN")
        self.assertNotIn("--record-set", args)
        self.assertNotIn("--preserve-records", args)
        self.assertNotIn("--raid-replay-client-gated", args)

    def test_generated_host_configuration_uses_no_reward_profile(self):
        args = host_arguments(
            0xBD13FB43, None, "keys", 600,
            player_pokemon="host.pk9", generated_bootstrap=True,
            raid_version="scarlet", raid_map="blueberry",
            raid_progress="6star", raid_content="black")
        self.assertIn("--raid-generated-bootstrap", args)
        self.assertNotIn("--raid-reward-profile", args)
        self.assertEqual(args[args.index("--raid-version") + 1], "scarlet")
        self.assertEqual(args[args.index("--raid-map") + 1], "blueberry")
        self.assertEqual(args[args.index("--raid-progress") + 1], "6star")
        self.assertEqual(args[args.index("--raid-content") + 1], "black")

    def test_generated_host_configuration_accepts_exact_reward_profile(self):
        args = host_arguments(
            0xFDAE7B7D, Path("profile.json"), "keys", 600,
            player_pokemon="host.pk9", generated_bootstrap=True)
        self.assertIn("--raid-generated-bootstrap", args)
        self.assertEqual(
            args[args.index("--raid-reward-profile") + 1], "profile.json")

    def test_inline_rewards_create_a_temporary_profile_for_the_host(self):
        called = {}
        fake = ModuleType("sv_host")

        def host(args):
            called["args"] = args
            path = Path(args[args.index("--raid-reward-profile") + 1])
            called["profile"] = json.loads(path.read_text())
            return 0

        fake.main = host
        with patch.dict(sys.modules, {"sv_host": fake}):
            self.assertEqual(main([
                "--raid-seed", "000F34C3",
                "--raid-player-pokemon", "host.pk9",
                "--reward", "1:1",
                "--reward", "50:10",
                "--keys", "keys",
            ]), 0)
        self.assertEqual(called["profile"]["rewards"], [
            {"item_id": 1, "quantity": 1},
            {"item_id": 50, "quantity": 10},
        ])

    def test_generated_inline_rewards_reach_the_host_as_a_profile(self):
        called = {}
        fake = ModuleType("sv_host")

        def host(args):
            called["args"] = args
            path = Path(args[args.index("--raid-reward-profile") + 1])
            called["profile"] = json.loads(path.read_text())
            return 0

        fake.main = host
        with patch.dict(sys.modules, {"sv_host": fake}):
            self.assertEqual(main([
                "--raid-seed", "FDAE7B7D",
                "--raid-player-pokemon", "host.pk9",
                "--generated-bootstrap",
                "--reward", "15:500",
                "--keys", "keys",
            ]), 0)
        self.assertIn("--raid-generated-bootstrap", called["args"])
        self.assertEqual(called["profile"]["rewards"], [
            {"item_id": 15, "quantity": 500},
        ])

    def test_product_profile_uses_generated_path_before_opening_radio(self):
        import sv_host
        from pokeldn.sv import pokemon, raid_guest
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "profile.json"
            profile.write_text(json.dumps(_profile_value([(1, 1), (50, 10)])))
            player = Path(folder) / "player.pk9"
            player.write_bytes(pokemon.encrypt(raid_guest.lobby_pokemon()))
            args = host_arguments(
                0x000F34C3, profile, "keys", 600, player_pokemon=str(player))
            with (patch.object(sv_host, "needs_root", return_value=False),
                  patch.object(sv_host, "find_ap_phy", return_value=None),
                  patch.object(sv_host.pokemon_service, "prepare_file",
                               return_value=str(player)),
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(sv_host.main(args), 1)

    def test_generated_bootstrap_is_prepared_before_opening_radio(self):
        import sv_host
        from pokeldn.sv import pokemon, raid_guest
        with tempfile.TemporaryDirectory() as folder:
            player = Path(folder) / "player.pk9"
            player.write_bytes(pokemon.encrypt(raid_guest.lobby_pokemon()))
            args = host_arguments(
                0xBD13FB43, None, "keys", 600, player_pokemon=str(player),
                generated_bootstrap=True)
            output = io.StringIO()
            with (patch.object(sv_host, "needs_root", return_value=False),
                  patch.object(sv_host, "find_ap_phy", return_value=None),
                  patch.object(sv_host.pokemon_service, "prepare_file",
                               return_value=str(player)),
                  contextlib.redirect_stdout(output)):
                self.assertEqual(sv_host.main(args), 1)
            self.assertIn("generated bootstrap: complete 0xaa0-byte", output.getvalue())
            self.assertIn(
                "raid handoff: stopping raid application stream after sequence 20",
                output.getvalue())

    def test_generated_exact_rewards_use_no_bootstrap_donor(self):
        import sv_host
        from pokeldn.sv import pokemon, raid_guest
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "profile.json"
            profile.write_text(json.dumps(_profile_value([(15, 500)])))
            player = Path(folder) / "player.pk9"
            player.write_bytes(pokemon.encrypt(raid_guest.lobby_pokemon()))
            args = host_arguments(
                0xFDAE7B7D, profile, "keys", 600, player_pokemon=str(player),
                generated_bootstrap=True)
            output = io.StringIO()
            with (patch.object(sv_host, "needs_root", return_value=False),
                  patch.object(sv_host, "find_ap_phy", return_value=None),
                  patch.object(sv_host.pokemon_service, "prepare_file",
                               return_value=str(player)),
                  contextlib.redirect_stdout(output)):
                self.assertEqual(sv_host.main(args), 1)
            self.assertIn("with 1 exact reward(s)", output.getvalue())
            self.assertNotIn("reward donor", output.getvalue())


if __name__ == "__main__":
    unittest.main()
