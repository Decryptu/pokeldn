#!/usr/bin/env python3
"""Builds pokeldn/swsh/data/lair_pokemon.json, the Dynamax Adventure's Pokemon of Sword and Shield
1.3.2 in the game's order [docs/swsh_raid.md, The adventure seed], from the RomFS files
`bin/appli/chika/data_table/underground_exploration_poke.bin` (a FlatBuffer, one table per row) and
`bin/pml/personal/personal_total.bin` (each row's two types).

    ./.venv/bin/python scripts/gen_swsh_lair_data.py --poke underground_exploration_poke.bin \
        --personal personal_total.bin

A row is [species, form, legendary, level, type 1, type 2, move 1, 2, 3, 4].
"""

import argparse
import json
import pathlib
import struct

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "pokeldn" / "swsh" / "data" / "lair_pokemon.json"
# FlatBuffer field numbers of a row, read against the rows' species and levels.
BOSS, FORM, LEVEL, SPECIES, MOVES = 0, 3, 7, 8, (21, 22, 23, 24)
PERSONAL_SIZE, TYPES, FORM_INDEX, FORM_COUNT = 0xB0, 0x06, 0x1E, 0x20


def rows(data):
    u32 = lambda at: struct.unpack_from("<I", data, at)[0]

    def fields(table):
        vtable = table - struct.unpack_from("<i", data, table)[0]
        size, inline = struct.unpack_from("<HH", data, vtable)
        offsets = struct.unpack_from(f"<{(size - 4) // 2}H", data, vtable + 4)
        present = sorted(o for o in offsets if o) + [inline]

        def value(number, default=0):
            if number >= len(offsets) or not offsets[number]:
                return default
            at = offsets[number]
            width = min(next(o for o in present if o > at) - at, 4)
            return int.from_bytes(data[table + at:table + at + width], "little")
        return value

    root = u32(0)
    vtable = root - struct.unpack_from("<i", data, root)[0]
    at = root + struct.unpack_from("<H", data, vtable + 4)[0]
    vector = at + u32(at)
    for i in range(u32(vector)):
        slot = vector + 4 + 4 * i
        yield fields(slot + u32(slot))


def types(personal, species, form):
    entry = lambda n: personal[n * PERSONAL_SIZE:(n + 1) * PERSONAL_SIZE]
    base = entry(species)
    first, count = struct.unpack_from("<H", base, FORM_INDEX)[0], base[FORM_COUNT]
    row = entry(first + form - 1) if 0 < form < count and first else base
    return row[TYPES], row[TYPES + 1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--poke", required=True)
    ap.add_argument("--personal", required=True)
    args = ap.parse_args()
    personal = pathlib.Path(args.personal).read_bytes()
    out = []
    for value in rows(pathlib.Path(args.poke).read_bytes()):
        species, form = value(SPECIES), value(FORM)
        out.append([species, form, bool(value(BOSS)), value(LEVEL), *types(personal, species, form),
                    *(value(m) for m in MOVES)])
    OUT.write_text(json.dumps({"source": "Sword/Shield 1.3.2 RomFS", "rows": out}, separators=(",", ":")) + "\n")
    print(f"{len(out)} rows, {sum(r[2] for r in out)} legendary -> {OUT}")


if __name__ == "__main__":
    main()
