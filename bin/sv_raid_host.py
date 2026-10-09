#!/usr/bin/env python3
"""Host an SV Tera Raid with a generated boss and seed-derived or exact rewards."""

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


def mac_address(value: str) -> str:
    try:
        raw = bytes.fromhex(value.replace(":", ""))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("MAC must contain six hexadecimal bytes") from exc
    if len(raw) != 6:
        raise argparse.ArgumentTypeError("MAC must contain six hexadecimal bytes")
    if raw[0] & 1:
        raise argparse.ArgumentTypeError("MAC must be unicast (the multicast bit must be clear)")
    return ":".join(f"{octet:02x}" for octet in raw)


def player_id(value: str) -> str:
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("player ID must be 16 hexadecimal bytes") from exc
    if len(raw) != 16:
        raise argparse.ArgumentTypeError("player ID must be 16 hexadecimal bytes")
    return raw.hex()


def synthetic_mac(random_bytes=os.urandom) -> str:
    """Return a standards-valid, locally administered unicast MAC."""
    raw = bytearray(random_bytes(6))
    if len(raw) != 6:
        raise ValueError("MAC entropy source must return six bytes")
    raw[0] = (raw[0] & 0xFC) | 0x02
    return ":".join(f"{octet:02x}" for octet in raw)


def synthetic_player_id() -> str:
    """Return Pia's anonymous/local player ID, accepted by retail Scarlet/Violet."""
    return "00000000000000010000000000000000"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raid-seed", required=True, type=raid_seed, metavar="8-HEX-DIGITS",
                        help="seed that determines the raid boss, Tera type, stats, and moves")
    parser.add_argument("--raid-player-pokemon", metavar="FILE",
                        help="a legal party PK9 for POKELDN to bring as the raid host; required "
                             "by --generated-bootstrap")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--reward", action="append", type=reward, metavar="ITEM_ID:QUANTITY",
                        help="reward row in display order; repeat up to 16 times")
    source.add_argument("--profile", type=Path, metavar="JSON",
                        help="an existing versioned exact-list reward profile")
    parser.add_argument("--generated-bootstrap", action="store_true",
                        help="generate the complete raid application opening through sequence "
                             "20, including RaidPoint and seed rewards, without the victory "
                             "replay; optional --reward rows replace the seed rewards; requires "
                             "--raid-player-pokemon and supports standard 1-5-star and black "
                             "6-star raids")
    parser.add_argument("--raid-version", choices=("scarlet", "violet"), default="violet",
                        help="game version used to select the generated encounter")
    parser.add_argument("--raid-map", choices=("paldea", "kitakami", "blueberry"),
                        default="paldea",
                        help="region used to select the generated encounter")
    parser.add_argument("--raid-progress",
                        choices=("beginning", "tera", "3star", "4star", "5star", "6star"),
                        default="4star",
                        help="story progress used to select the generated raid level")
    parser.add_argument("--raid-content", choices=("standard", "black"), default="standard",
                        help="standard selects 1-5-star raids; black selects 6-star raids")
    parser.add_argument("--keys", default="~/.switch/prod.keys")
    parser.add_argument("--capture", metavar="JSONL",
                        help="write the host's machine-readable packet trace here")
    parser.add_argument("--mac", type=mac_address,
                        help="host AP MAC; the default is a fresh locally administered unicast MAC")
    parser.add_argument("--host-player-id", type=player_id, metavar="32-HEX-DIGITS",
                        help="16-byte Pia Session player ID; the default is Pia's "
                             "retail-validated anonymous/local ID")
    parser.add_argument("--host-player-name", default="POKELDN",
                        help="host name in Pia PlayerInfo (default: POKELDN)")
    parser.add_argument("--seconds", type=float, default=600.0,
                        help="maximum time to keep the raid host running")
    return parser


def host_arguments(seed: int, profile: Path | None, keys: str, seconds: float,
                   player_pokemon: str | None = None,
                   capture: str | None = None,
                   generated_bootstrap: bool = True,
                   mac: str | None = None,
                   host_player_id: str | None = None,
                   host_player_name: str = "POKELDN",
                   raid_version: str = "violet",
                   raid_map: str = "paldea",
                   raid_progress: str = "4star",
                   raid_content: str = "standard") -> list[str]:
    """The validated retail-session configuration shared by CLI and GUI hosting."""
    arguments = [
        "--keys", os.path.expanduser(keys),
        "--channel", "1",
        "--scene-id", "7",
        "--max-participants", "4",
        "--ssid", "75db0fb3342cee600d3549e90d88b56f",
        "--mac", mac or synthetic_mac(),
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
        "--trainer-name", host_player_name,
        "--host-player-id", host_player_id or synthetic_player_id(),
        "--host-player-name", host_player_name,
        "--raid-seed", f"{seed:08X}",
        "--raid-version", raid_version,
        "--raid-map", raid_map,
        "--raid-progress", raid_progress,
        "--raid-content", raid_content,
        "--seconds", str(seconds),
    ]
    if profile is not None:
        arguments += ["--raid-reward-profile", str(profile)]
    if not generated_bootstrap:
        raise ValueError("donor-backed raid hosting was removed")
    arguments.append("--raid-generated-bootstrap")
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
    if not args.raid_player_pokemon:
        parser.error("raid hosting requires --raid-player-pokemon")
    args.generated_bootstrap = True
    try:
        if args.profile is not None:
            from sv_raid_bootstrap_codec import load_reward_profile
            load_reward_profile(args.profile)
            profile_path = args.profile.resolve()
            temporary = None
        elif args.reward:
            value = _profile_value(args.reward)
            temporary = tempfile.TemporaryDirectory(prefix="pokeldn-sv-raid-")
            profile_path = Path(temporary.name) / "rewards.json"
            profile_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        else:
            profile_path = None
            temporary = None
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    from sv_host import main as host
    try:
        arguments = host_arguments(
            args.raid_seed, profile_path, args.keys, args.seconds,
            player_pokemon=args.raid_player_pokemon, capture=args.capture,
            generated_bootstrap=args.generated_bootstrap,
            mac=args.mac, host_player_id=args.host_player_id,
            host_player_name=args.host_player_name,
            raid_version=args.raid_version, raid_map=args.raid_map,
            raid_progress=args.raid_progress, raid_content=args.raid_content)
        chosen_mac = arguments[arguments.index("--mac") + 1]
        chosen_player_id = arguments[arguments.index("--host-player-id") + 1]
        print(f"[sv-raid] synthetic host identity: mac={chosen_mac} "
              f"player_id={chosen_player_id}")
        result = host(arguments)
        return int(result or 0)
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
