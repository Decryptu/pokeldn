#!/usr/bin/env python3
"""Generate Scarlet/Violet fight and reward profiles directly from raid seeds."""

from pathlib import Path
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import gen9
from pokeldn.sv import raid_generation


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
    args = parser.parse_args()

    context = dict(version=args.version, progress=args.progress,
                   map_name=args.map_name, content=args.content)
    raid = (raid_generation.generate_raid(args.seed, raid_generation.load_context(args.context))
            if args.context else raid_generation.generate_seed_raid(args.seed, **context))
    reward_seed = args.seed if args.reward_seed is None else args.reward_seed
    reward_raid = (raid if reward_seed == args.seed else
                   raid_generation.generate_seed_raid(reward_seed, **context))
    if args.pk9:
        plain = gen9.write(bytes(gen9.SIZE_PARTY), **raid["profile"])
        args.pk9.write_bytes(gen9.encrypt(plain))
    output = raid_generation.json_ready(raid)
    if reward_seed != args.seed:
        output = {"fight": output, "reward": raid_generation.json_ready(reward_raid)}
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
