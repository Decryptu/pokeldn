#!/usr/bin/env python3
"""Regenerate pokeldn/frlg/rom/english_names.py: French addresses named by the English rev10 build.

    ./.venv/bin/python scripts/gen_english_names.py [--check] [--report]

Method and control: docs/frlg_leafgreen.md. A name here is a deduction; one about to be called is
checked by the call.
"""
from pathlib import Path
import argparse
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "frlg"))

import english_build                                                          # noqa: E402
from pokeldn.frlg.rom import thumb, worker_names                              # noqa: E402
from script_read import every_dump                                            # noqa: E402

OUT = os.path.join(ROOT, "pokeldn", "frlg", "rom", "english_names.py")


def call_targets():
    """-> every address the console's own code is seen to call, off the FireRed dumps."""
    out = set()
    for base, data in every_dump(os.path.join(ROOT, "scratchpad"), "firered"):
        for _site, target in thumb.bl_targets(data, base, base, base + len(data)):
            out.add(target & ~1)
    return out


def bracketed(runs, rom, named):
    """-> {address: (name, offset)} for a call target between two runs. Weaker than NAMES: the offset
    from either side must land exactly on a function start, and only one may."""
    out = {}
    for address in sorted(call_targets()):
        if address in named or english_build.offset_at(runs, address)[0] is not None:
            continue
        below = [r for r in runs if r[1] < address]
        above = [r for r in runs if r[0] > address]
        candidates = set()
        if below:
            candidates.add(max(below, key=lambda r: r[1])[2])
        if above:
            candidates.add(min(above, key=lambda r: r[0])[2])
        hits = [(offset, rom.names_at(address + offset)[0])
                for offset in sorted(candidates)
                if (address + offset) in rom.code and rom.names_at(address + offset)]
        if len(hits) == 1:
            out[address] = (hits[0][1], hits[0][0])
    return out

HEADER = '''"""What the ENGLISH rev10 build calls a FRENCH address. Generated; do not edit by hand.

`scripts/gen_english_names.py`, whose docstring carries the method and the control. The short of it:
the decomp builds the same revision the Switch runs, byte-exactly, for both cartridges; our dumps
and our four tables place French addresses inside that build; the English ELF names what is there,
static functions included, which no link map carries.

THE CONTROL: {control} of the {control} names the console's own bodies proved come back the same, and
none comes back different. A name here is still a DEDUCTION - `worker_names` is a reading of the
console, `rom_map.CALLABLE` is a call that did something, and this is neither.

OFFSETS is the measurement underneath: (low, high, offset, points), French + offset = English, one
run per region where nothing changed size. An address outside every run is not named and is not
guessed at. docs/frlg_leafgreen.md.
"""

# (low, high, offset, points) - French + offset = English, measured, never interpolated.
OFFSETS = (
{offsets}
)

# French address -> what the English build calls the FUNCTION that starts there. Data
# symbols are left out: a name here is something a `bl` can land on.
NAMES = {{
{names}
}}

# WEAKER, and kept apart: a call target that falls BETWEEN two measured runs, named with one of the
# two offsets either side of it. What stands in for the missing measurement is that the offset must
# land exactly on a function start and only one of the two may - an offset wrong by two bytes lands
# mid-instruction. {{address: (name, the offset used)}}.
BRACKETED = {{
{bracketed}
}}


def offset(address):
    """-> how far the English build is from this French address, or None outside every run."""
    for low, high, value, _points in OFFSETS:
        if low <= address <= high:
            return value
    return None


def name(address):
    """-> the English build's name for a French address, THUMB bit ignored, or None."""
    return NAMES.get(address & ~1)


def bracketed_name(address):
    """-> the weaker reading for an address between two runs, or None. See BRACKETED."""
    entry = BRACKETED.get(address & ~1)
    return entry[0] if entry else None
'''


def build():
    """-> (offset runs, {French address: name}). Where an address carries several names
    (`GetBoxMonData2` aliases `GetBoxMonData3` [decomp:src/pokemon.c:3332]), ours wins."""
    runs = english_build.merged_runs("firered")
    rom = english_build.english("firered")
    ours = dict(worker_names.WORKERS)
    names = {}
    for low, high, value, _points, _source in runs:
        for address in rom.code:
            french = address - value
            if low <= french <= high:
                symbols = rom.symbols[address]
                preferred = next((s for s in symbols if s == ours.get(french)), symbols[0])
                names.setdefault(french, preferred)
    return runs, names


def render(runs, names, control, weak):
    offsets = "\n".join(f"    (0x{low:08X}, 0x{high:08X}, {value:#x}, {points}),"
                        for low, high, value, points, _source in runs)
    lines = []
    for french, symbol in sorted(names.items()):
        lines.append(f"    0x{french:08X}: {symbol!r},")
    weak_lines = "\n".join(f"    0x{address:08X}: ({symbol!r}, {offset:#x}),"
                            for address, (symbol, offset) in sorted(weak.items()))
    return HEADER.format(control=control, offsets=offsets, names="\n".join(lines),
                         bracketed=weak_lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="fail if the file on disk is not what this would write")
    parser.add_argument("--report", action="store_true", help="what the control said")
    args = parser.parse_args()

    for console in ("firered", "leafgreen"):
        problem = english_build.check_build(console)
        if problem:
            print(f"{console}: {problem}")
            return 1

    agreed, disagreed, silent, uncovered = english_build.check()
    if disagreed:
        print(f"REFUSING: the control disagrees on {len(disagreed)} of the names the console proved")
        for address, ours, theirs in disagreed:
            print(f"  0x{address:08X}  ours {ours}  English {theirs}")
        return 1
    runs, names = build()
    weak = bracketed(runs, english_build.english("firered"), names)
    text = render(runs, names, len(agreed), weak)
    if args.report:
        print(f"control: {len(agreed)} agree, 0 disagree, {len(silent)} with no English symbol, "
              f"{len(uncovered)} outside the offset map")
        print(f"{len(runs)} offset runs, {len(names)} French addresses named, "
              f"{len(weak)} more bracketed between two runs")
    if args.check:
        current = Path(OUT).read_text(encoding='utf-8') if os.path.exists(OUT) else ""
        if current != text:
            print(f"{OUT} is not what the build would write")
            return 1
        print(f"{OUT} is current")
        return 0
    with open(OUT, "w") as handle:
        handle.write(text)
    print(f"wrote {OUT}: {len(names)} names from {len(runs)} measured offset runs, "
          f"{len(weak)} bracketed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
