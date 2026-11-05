#!/usr/bin/env python3
"""Write the twelve FireRed and LeafGreen cartridge images out of their Switch packages.

    ./.venv/bin/python tools/frlg/extract_cartridges.py [--packages DIR] [--keys FILE] [--out DIR]

The offline tests read scratchpad/frlg_languages/ and skip what is absent. 16 MB each, 192 MB in all;
delete the folder to reclaim it, this rebuilds it.
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.switch import cartridge  # noqa: E402
from pokeldn.switch.container import load_keys  # noqa: E402

SWITCH = pathlib.Path.home() / "Documents/Switch"


def extract(package, keys, out):
    """-> the .gba written from one package's RomFS."""
    name, image = cartridge.from_package(package, keys)
    target = out / name
    target.write_bytes(image)
    return target


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packages", type=pathlib.Path, default=SWITCH / "Pokemon Fire Red and Leaf Green")
    ap.add_argument("--keys", default=str(SWITCH / "23.0.0 keys/prod.keys"))
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("scratchpad/frlg_languages"))
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    keys = load_keys(args.keys)
    packages = sorted(args.packages.glob("*.nsp"))
    if not packages:
        sys.exit(f"no .nsp in {args.packages}")
    for package in packages:
        print(extract(package, keys, args.out))


if __name__ == "__main__":
    main()
