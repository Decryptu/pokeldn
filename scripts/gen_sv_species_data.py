#!/usr/bin/env python3
"""Builds pokeldn/sv/data/species.json: the personal entry of every Scarlet/Violet species and form,
every move's PP and the English species names, from a PKHeX checkout [docs/sv_raid.md, Event raids].

raid_base.json carries these for the standard and black-crystal bosses only; an event raid's boss
can be any species the game holds, a starter or a legendary among them. The readers are
scripts/gen_sv_raid_data.py's, so an entry here equals that file's wherever both have one.

    ./.venv/bin/python scripts/gen_sv_species_data.py --pkhex DIR
"""

import argparse
import json
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_sv_raid_data as raid_data                        # noqa: E402

OUT = ROOT / "pokeldn" / "sv" / "data" / "species.json"
PRESENT = 0x1C                    # PersonalInfo9SV.IsPresentInGame


def present(path):
    """-> {(species, form)} of every entry the game holds."""
    raw = path.read_bytes()
    size = raid_data.PERSONAL_SIZE
    entries = [raw[offset:offset + size] for offset in range(0, len(raw), size)]
    firsts = [struct.unpack_from("<H", e, 0x18)[0] for e in entries]
    out = set()
    # The form entries follow the species', so the first of them closes the species range.
    for species in range(1, min(f for f in firsts if f)):
        first, forms = firsts[species], entries[species][0x1A]
        for form in range(max(forms, 1)):
            index = first + form - 1 if 0 < form < forms and first else species
            if entries[index][PRESENT]:
                out.add((species, form))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pkhex", required=True, type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args()
    core = args.pkhex / "PKHeX.Core"
    table = core / "Resources" / "byte" / "personal" / "personal_sv"
    wanted = present(table)
    species = sorted({s for s, _ in wanted})
    pp = raid_data.move_pp(core / "Moves" / "MoveInfo9.cs")
    names = (core / "Resources" / "text" / "other" / "en" / "text_Species_en.txt").read_text(
        encoding="utf-8-sig").splitlines()
    result = {
        "source": {"pkhex": raid_data.revision(args.pkhex), "license": "GPL-3.0"},
        "personal": raid_data.personal(table, wanted),
        "move_pp": {str(move): value for move, value in enumerate(pp)},
        "species_names": {str(s): names[s] for s in species},
    }
    args.out.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(wanted)} species and forms, {len(result['move_pp'])} moves")


if __name__ == "__main__":
    main()
