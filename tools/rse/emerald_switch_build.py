#!/usr/bin/env python3
"""Build Emerald for the Switch FireRed/LeafGreen application: pret/pokeemerald at BASE plus
pokeemerald_switch.patch, built with REVISION=10 for one cartridge [docs/rse_switch_build.md].

    ./.venv/bin/python tools/rse/emerald_switch_build.py --tree ~/pokeemerald_switch --cart BPRE
    ./.venv/bin/python tools/rse/emerald_switch_build.py --tree DIR --agbcc ~/agbcc --cart BPRF --compare

--tree is cloned when absent. --agbcc installs pret/agbcc into the tree first. --cpp names a C
preprocessor when arm-none-eabi-cpp is missing (Homebrew: /opt/homebrew/bin/cpp-16). --compare also
builds the unpatched ROM and checks it against pret's sha1, which proves the patch leaves REVISION 0 alone.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH = os.path.join(HERE, "pokeemerald_switch.patch")
UPSTREAM = "https://github.com/pret/pokeemerald.git"
BASE = "731ad5bfd6e6f265508d0efcca0ba42f9dcf5881"

# librfu_sio32id.o in each Switch cartridge; the application patches it and librfu_intr.o (+0x30C)
# there at load [docs/frlg_rom.md, The breakpoint hooks]. BPRJ/BPGJ (0x081C66EC/0x081C66C8) fall
# inside Emerald's .text and are not built.
CARTS = {"BPRD": 0x081E702C, "BPRE": 0x081E2814, "BPRF": 0x081E1568, "BPRI": 0x081E0200,
         "BPRS": 0x081E28C8, "BPGD": 0x081E7008, "BPGE": 0x081E27F0, "BPGF": 0x081E1544,
         "BPGI": 0x081E01DC, "BPGS": 0x081E28A4}


def run(cmd, cwd=None):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def git_ok(tree, *args):
    return subprocess.run(["git", *args], cwd=tree, capture_output=True).returncode == 0


def prepare(tree):
    if not os.path.isdir(tree):
        run(["git", "clone", UPSTREAM, tree])
    if git_ok(tree, "apply", "--reverse", "--check", PATCH):
        print("patch already applied", flush=True)
        return
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tree, capture_output=True, text=True).stdout.strip()
    if head != BASE:
        run(["git", "checkout", "-q", BASE], cwd=tree)
    run(["git", "apply", PATCH], cwd=tree)


def make(tree, cpp, jobs, *targets):
    cmd = ["make", f"-j{jobs}", *targets]
    if cpp:
        cmd.append(f"CPP={cpp}")
    run(cmd, cwd=tree)


def placed_at(map_path):
    """-> the address the linker gave src/librfu_sio32id.o's .text."""
    text = open(map_path).read()
    m = re.search(r"^ \.text\s+0x([0-9a-f]+)\s+0x[0-9a-f]+ src/librfu_sio32id\.o", text, re.M)
    return int(m.group(1), 16) if m else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True, help="pokeemerald checkout to patch and build (cloned if absent)")
    ap.add_argument("--cart", default="BPRE", choices=sorted(CARTS), help="the cartridge the ROM replaces")
    ap.add_argument("--agbcc", help="a pret/agbcc checkout built with build.sh; installed into the tree")
    ap.add_argument("--cpp", help="C preprocessor, when arm-none-eabi-cpp is not on PATH")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--compare", action="store_true", help="also build REVISION 0 and run pret's compare")
    args = ap.parse_args()

    tree = os.path.abspath(os.path.expanduser(args.tree))
    prepare(tree)
    if args.agbcc:
        run(["./install.sh", tree], cwd=os.path.expanduser(args.agbcc))
    if args.compare:
        make(tree, args.cpp, args.jobs, "compare")
    make(tree, args.cpp, args.jobs, "emerald_switch", f"SWITCH_CART={args.cart}")

    stem = os.path.join(tree, f"pokeemerald_switch_{args.cart}")
    at = placed_at(stem + ".map")
    if at != CARTS[args.cart]:
        sys.exit(f"the wireless driver landed at {at and hex(at)}, not {CARTS[args.cart]:#x}; do not use this ROM")
    rom = open(stem + ".gba", "rb").read()
    print(f"{stem}.gba  {len(rom)} bytes  sha1 {hashlib.sha1(rom).hexdigest()}  driver at {at:#x}")


if __name__ == "__main__":
    main()
