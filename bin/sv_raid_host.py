#!/usr/bin/env python3
"""Host a Scarlet/Violet Tera Raid with a generated boss and exact rewards."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

# The GUI imports this file to inspect its argparse parser.  In that case Python
# does not automatically put the script's directory on sys.path as it does for
# `python bin/sv_raid_host.py`, so make both sibling helpers and pokeldn importable.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, SCRIPT_DIR)

from sv_raid_bootstrap_codec import (
    REWARD_PROFILE_FORMAT,
    REWARD_PROFILE_TEMPLATE,
    parse_reward_profile,
)


def raid_seed(value: str) -> int:
    if len(value) != 8:
        raise argparse.ArgumentTypeError("raid seed must be exactly eight hexadecimal digits")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "raid seed must be exactly eight hexadecimal digits") from exc


def reward(value: str) -> tuple[int, int]:
    try:
        item_text, quantity_text = value.split(":", 1)
        item_id, quantity = int(item_text, 0), int(quantity_text, 0)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("reward must be ITEM_ID:QUANTITY") from exc
    try:
        profile = parse_reward_profile({
            "format": REWARD_PROFILE_FORMAT,
            "template": REWARD_PROFILE_TEMPLATE,
            "mode": "exact",
            "rewards": [{"item_id": item_id, "quantity": quantity}],
        })
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    entry = profile.rewards[0]
    return entry.item_id, entry.quantity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raid-seed", required=True, type=raid_seed, metavar="8-HEX-DIGITS",
                        help="seed that determines the raid boss, Tera type, stats, and moves")
    parser.add_argument("--raid-player-pokemon", metavar="FILE",
                        help="a legal party PK9 for POKELDN to bring as the raid host; "
                             "the existing capture-backed behavior is used when omitted")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--reward", action="append", type=reward, metavar="ITEM_ID:QUANTITY",
                        help="reward row in display order; repeat up to 16 times")
    source.add_argument("--profile", type=Path, metavar="JSON",
                        help="an existing versioned exact-list reward profile")
    parser.add_argument("--keys", default="~/.switch/prod.keys")
    parser.add_argument("--capture", metavar="JSONL",
                        help="write the host's machine-readable packet trace here")
    parser.add_argument("--seconds", type=float, default=600.0,
                        help="maximum time to keep the raid host running")
    return parser


def host_arguments(seed: int, profile: Path, keys: str, seconds: float,
                   player_pokemon: str | None = None,
                   capture: str | None = None) -> list[str]:
    """The validated retail-session configuration shared by CLI and GUI hosting."""
    arguments = [
        "--keys", os.path.expanduser(keys),
        "--channel", "1",
        "--scene-id", "7",
        "--max-participants", "4",
        "--ssid", "75db0fb3342cee600d3549e90d88b56f",
        "--mac", "a4:38:cc:eb:6d:5a",
        "--host-var", "0x7727",
        "--code", "4970",
        "--game-data", ("3439373000000000000000000000000000000000000000000000000000000000"
                        "00aa281104000000"),
        "--net-unicast",
        "--scarlet-response",
        "--session-flags", "0",
        "--session-packet-id", "1",
        "--no-session-ack",
        "--join-seq", "0",
        "--update-seq", "0",
        "--update-delay", "0.02",
        "--rtt-probe",
        "--clock",
        "--net-stations", "4",
        "--record-delay", "0.100",
        "--record-spacing", "0.003",
        "--record-set", str(Path(__file__).with_name("tera_raid_retail_victory_full_records")),
        "--preserve-records",
        "--host-player-id", "100036df3a8d57687a5361855a6377a1",
        "--host-player-name", " ",
        "--raid-seed", f"{seed:08X}",
        "--raid-reward-profile", str(profile),
        "--seconds", str(seconds),
    ]
    if player_pokemon:
        arguments += ["--raid-player-pokemon", player_pokemon]
    if capture:
        arguments += ["--capture", capture]
    return arguments


def _profile_value(rows: list[tuple[int, int]]) -> dict:
    profile = parse_reward_profile({
        "format": REWARD_PROFILE_FORMAT,
        "template": REWARD_PROFILE_TEMPLATE,
        "mode": "exact",
        "name": "PokeLDN custom raid rewards",
        "rewards": [{"item_id": item_id, "quantity": quantity}
                    for item_id, quantity in rows],
    })
    return {
        "format": profile.format,
        "template": profile.template,
        "mode": profile.mode,
        "name": profile.name,
        "rewards": [{"item_id": row.item_id, "quantity": row.quantity}
                    for row in profile.rewards],
    }


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    if args.profile is None and not args.reward:
        parser.error("add at least one --reward or use --profile")
    try:
        if args.profile is not None:
            from sv_raid_bootstrap_codec import load_reward_profile
            load_reward_profile(args.profile)
            profile_path = args.profile.resolve()
            temporary = None
        else:
            value = _profile_value(args.reward)
            temporary = tempfile.TemporaryDirectory(prefix="pokeldn-sv-raid-")
            profile_path = Path(temporary.name) / "rewards.json"
            profile_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    from sv_host import main as host
    try:
        result = host(host_arguments(
            args.raid_seed, profile_path, args.keys, args.seconds,
            player_pokemon=args.raid_player_pokemon, capture=args.capture))
        return int(result or 0)
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
