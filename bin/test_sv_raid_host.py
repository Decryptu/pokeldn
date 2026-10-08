"""Offline checks for the production Scarlet/Violet raid host entry point."""

from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sv_raid_host import build_parser, host_arguments, main, _profile_value
from pokeldn.app.command import accepted


class RaidHostTests(unittest.TestCase):
    def test_parser_accepts_ordered_rewards(self):
        args = build_parser().parse_args([
            "--raid-seed", "000F34C3", "--raid-player-pokemon", "host.pk9",
            "--reward", "1:1", "--reward", "50:10", "--capture", "run.jsonl"])
        self.assertEqual(args.raid_seed, 0x000F34C3)
        self.assertEqual(args.raid_player_pokemon, "host.pk9")
        self.assertEqual(args.reward, [(1, 1), (50, 10)])
        self.assertEqual(args.capture, "run.jsonl")

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
            player_pokemon="host.pk9", capture="run.jsonl")
        self.assertEqual(args[args.index("--raid-seed") + 1], "000F34C3")
        self.assertEqual(args[args.index("--raid-reward-profile") + 1], "profile.json")
        self.assertEqual(args[args.index("--raid-player-pokemon") + 1], "host.pk9")
        self.assertEqual(args[args.index("--capture") + 1], "run.jsonl")
        self.assertIn("--preserve-records", args)
        self.assertNotIn("--raid-replay-client-gated", args)

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
                "--reward", "1:1",
                "--reward", "50:10",
                "--keys", "keys",
            ]), 0)
        self.assertEqual(called["profile"]["rewards"], [
            {"item_id": 1, "quantity": 1},
            {"item_id": 50, "quantity": 10},
        ])

    def test_product_replay_accepts_compact_donor_before_opening_radio(self):
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


if __name__ == "__main__":
    unittest.main()
