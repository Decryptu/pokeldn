#!/usr/bin/env python3
"""Generate Scarlet/Violet fight and reward profiles directly from raid seeds."""

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.sv import raid_generation
from sv_raid_bootstrap_codec import (
    build_application,
    build_raid_boss_pk9,
    build_seed_bootstrap_raw,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed", type=lambda value: int(value, 16) & 0xFFFFFFFF,
                        help="eight-digit hexadecimal fight/catch seed")
    parser.add_argument("--reward-seed", type=lambda value: int(value, 16) & 0xFFFFFFFF,
                        help="independent reward seed; defaults to the fight seed")
    parser.add_argument("--context", type=Path,
                        help="legacy explicit encounter context instead of the bundled tables")
    parser.add_argument("--version", choices=("scarlet", "violet"), default="violet")
    parser.add_argument("--progress", choices=("beginning", "tera", "3star", "4star",
                                                "5star", "6star"), default="4star")
    parser.add_argument("--map", dest="map_name",
                        choices=("paldea", "kitakami", "blueberry"), default="paldea")
    parser.add_argument("--content", choices=("standard", "black"), default="standard")
    parser.add_argument("--pk9", type=Path, help="write the generated encrypted 344-byte boss PK9")
    parser.add_argument("--bootstrap", type=Path,
                        help="write the generated 0xAA0 bootstrap plaintext")
    parser.add_argument("--application", type=Path,
                        help="write the generated LZ4-compressed 0x012F application")
    parser.add_argument("--point-name", default="RaidPoint_POKELDN_0",
                        help="synthetic RaidPoint identity for bootstrap generation")
    parser.add_argument("--player-pk9", action="append", type=Path, default=[], metavar="FILE",
                        help="participant party PK9; repeat up to four times")
    parser.add_argument("--message-value", type=lambda value: int(value, 0), default=0,
                        help="opaque 16-bit 0x012F header value at offset 4 (default: 0)")
    args = parser.parse_args()

    context = dict(version=args.version, progress=args.progress,
                   map_name=args.map_name, content=args.content)
    raid = (raid_generation.generate_raid(args.seed, raid_generation.load_context(args.context))
            if args.context else raid_generation.generate_seed_raid(args.seed, **context))
    reward_seed = args.seed if args.reward_seed is None else args.reward_seed
    reward_raid = (raid if reward_seed == args.seed else
                   raid_generation.generate_seed_raid(reward_seed, **context))
    if args.player_pk9 and not (args.bootstrap or args.application):
        parser.error("--player-pk9 requires --bootstrap or --application")
    if (args.bootstrap or args.application) and reward_seed != args.seed:
        parser.error("bootstrap generation currently uses one fight/reward seed")
    if (args.bootstrap or args.application) and args.context:
        parser.error("--bootstrap/--application require the bundled retail tables")
    if args.pk9:
        args.pk9.write_bytes(build_raid_boss_pk9(raid["profile"]))
    if args.bootstrap or args.application:
        try:
            players = [path.read_bytes() for path in args.player_pk9]
            raw = build_seed_bootstrap_raw(
                args.seed, **context, point_name=args.point_name, players=players)
            if args.bootstrap:
                args.bootstrap.write_bytes(raw)
            if args.application:
                args.application.write_bytes(build_application(
                    raw, message_value=args.message_value))
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    output = raid_generation.json_ready(raid)
    if reward_seed != args.seed:
        output = {"fight": output, "reward": raid_generation.json_ready(reward_raid)}
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
