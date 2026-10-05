#!/usr/bin/env python3
"""Generate a seed-derived Scarlet/Violet raid profile from an explicit encounter context."""

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
                        help="eight-digit hexadecimal raid seed")
    parser.add_argument("--context", required=True, type=Path,
                        help="JSON encounter context for the game's version/map/progress")
    parser.add_argument("--pk9", type=Path, help="write the generated encrypted 344-byte boss PK9")
    args = parser.parse_args()

    raid = raid_generation.generate_raid(args.seed, raid_generation.load_context(args.context))
    if args.pk9:
        plain = gen9.write(bytes(gen9.SIZE_PARTY), **raid["profile"])
        args.pk9.write_bytes(gen9.encrypt(plain))
    print(json.dumps(raid_generation.json_ready(raid), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
