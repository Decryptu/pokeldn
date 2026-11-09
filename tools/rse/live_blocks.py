#!/usr/bin/env python3
"""Carry English FireRed's measured live blocks to another cartridge by matching its code.

    ./.venv/bin/python tools/rse/live_blocks.py --cart BPRF            # prints the set and the checks
    ./.venv/bin/python tools/rse/live_blocks.py --all --write          # every Latin cartridge, into the JSON

Every cartridge holds FireRed's code apart from `bl` offsets and pool pointers, so masked 32-byte
windows of BPRE's live blocks are found in the target; the target's set is the blocks they land in
plus one level of `bl` targets and pool pointers from them. docs/rse_switch_build.md, The live blocks.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.gift import rom_transfer
from pokeldn.frlg.rom import builds, thumb

ROMS = "scratchpad/frlg_languages"
LANG = {"E": "e", "F": "f", "D": "d", "I": "i", "S": "s"}
BLOCK, WINDOW, SEARCH = rom_transfer.BLOCK, 32, 0x80000
ROM = 0x08000000
JSON = "pokeldn/frlg/data/rom_live_blocks.json"


def rom_path(code):
    return os.path.join(ROMS, f"{'FireRed' if code[2] == 'R' else 'LeafGreen'}_{LANG[code[3]]}.gba")


def masked(data):
    """-> `data` with `bl` pairs and pointer-like aligned words zeroed."""
    out = bytearray(data)
    for at in range(0, len(out) - 3, 2):
        hi = out[at] | out[at + 1] << 8
        lo = out[at + 2] | out[at + 3] << 8
        if hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800:
            out[at:at + 4] = bytes(4)
    for at in range(0, len(out) - 3, 4):
        if out[at + 3] in (0x02, 0x03, 0x08, 0x09):
            out[at:at + 4] = bytes(4)
    return bytes(out)


def useful(window):
    return len(set(window)) >= 10


def match(source, target, blocks):
    """-> {source offset: target offset} for unique masked windows of `blocks`."""
    ms, mt = masked(source), masked(target)
    found, delta = {}, 0
    for block in blocks:
        for at in range(block * BLOCK, (block + 1) * BLOCK, WINDOW // 2):
            window = ms[at:at + WINDOW]
            if len(window) < WINDOW or not useful(window):
                continue
            guess = at + delta
            lo, hi = max(0, guess - SEARCH), min(len(mt), guess + SEARCH)
            hit = mt.find(window, lo, hi)
            if hit < 0 or mt.find(window, hit + 1, hi) >= 0:
                hit = mt.find(window)
                if hit < 0 or mt.find(window, hit + 1) >= 0:
                    continue
            found[at] = hit
            delta = hit - at
    # A lone match is a coincidence: keep a window only when a neighbour lands with the same shift.
    step = WINDOW // 2
    return {s: d for s, d in found.items()
            if any(found.get(s + k, -1) - (s + k) == d - s for k in (-step, step))}


def carried(blocks, found):
    """-> the target blocks each source block's bytes land in, by the deltas its matched windows
    give; a block with none (data whose text differs) takes its neighbours' deltas."""
    deltas = sorted((s, d - s) for s, d in found.items())
    keys = [s for s, _ in deltas]
    import bisect
    live = set()
    for block in blocks:
        lo, hi = block * BLOCK, (block + 1) * BLOCK
        inside = {d for s, d in deltas if lo <= s < hi}
        if not inside:
            i = bisect.bisect_left(keys, lo)
            inside = {deltas[j][1] for j in (i - 1, i) if 0 <= j < len(deltas)}
        for d in inside:
            live.update(range(max(0, (lo + d) // BLOCK), min(rom_transfer.BLOCKS, (hi - 1 + d) // BLOCK + 1)))
    return live


def oracle(code, found):
    """-> (agree, disagree, unchecked) for the build table's ROM addresses that BPRE's live blocks hold."""
    src, dst = builds.BUILDS["BPRE"], builds.BUILDS[code]
    pairs = []
    for name in vars(src) if hasattr(src, "__dict__") else src._fields:
        a, b = getattr(src, name), getattr(dst, name)
        if isinstance(a, int) and isinstance(b, int) and ROM <= a < ROM + 0x2000000:
            pairs.append((name, a & ~1, b & ~1))
    for name, a in src.callable.items():
        if name in dst.callable:
            pairs.append((name, a & ~1, dst.callable[name] & ~1))
    agree, disagree, unchecked = 0, [], 0
    for name, a, b in pairs:
        off = a - ROM
        near = [s for s in found if s <= off < s + WINDOW]
        if not near:
            unchecked += 1
            continue
        s = near[0]
        if found[s] + off - s == b - ROM:
            agree += 1
        else:
            disagree.append((name, hex(a), hex(b), hex(ROM + found[s] + off - s)))
    return agree, disagree, unchecked


def derive(code, verbose=True):
    with open(rom_path("BPRE"), "rb") as f:
        source = f.read()
    with open(rom_path(code), "rb") as f:
        target = f.read()
    blocks = rom_transfer.live_blocks()["BPRE"]
    found = match(source, target, blocks)
    total = sum(1 for b in blocks for at in range(b * BLOCK, (b + 1) * BLOCK, WINDOW // 2)
                if useful(masked(source[at:at + WINDOW])))
    live = carried(blocks, found)
    agree, disagree, unchecked = oracle(code, found)
    if verbose:
        print(f"{code}: {len(found)}/{total} windows matched, {len(live)} live blocks; "
              f"build table {agree} agree, {len(disagree)} disagree, {unchecked} outside", flush=True)
        for row in disagree:
            print("   disagree", *row)
    return sorted(live), disagree


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cart", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true", help=f"add the sets to {JSON}")
    args = ap.parse_args()
    codes = [c for c in builds.SIO32ID if not c.endswith("J") and c != "BPRE"] if args.all else args.cart
    with open(JSON, encoding="utf-8") as f:
        data = json.load(f)
    bad = False
    for code in codes:
        live, disagree = derive(code)
        bad |= bool(disagree)
        data[code] = live
    if args.write and not bad:
        with open(JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(", ", ": "))
            f.write("\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
