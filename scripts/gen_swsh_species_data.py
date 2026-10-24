#!/usr/bin/env python3
"""Builds pokeldn/swsh/data/species.json: the personal entry of every Sword/Shield species and form the
game holds, every move's PP and the English species names, from a PKHeX checkout [docs/swsh_raid.md,
Event raids]. An event raid's boss is made from these.

    ./.venv/bin/python scripts/gen_swsh_species_data.py --pkhex DIR

An entry is [base stats HP Atk Def Spe SpA SpD, gender ratio, growth, abilities 1, 2 and hidden].
"""

import argparse
import json
import pathlib
import re
import struct
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "pokeldn" / "swsh" / "data" / "species.json"
SIZE = 0xB0                       # PersonalInfo8SWSH.SIZE
FORM_INDEX, FORM_COUNT, PRESENT = 0x1E, 0x20, 0x21


def personal(path):
    """-> {"species/form": entry} of every entry PersonalInfo8SWSH.IsPresentInGame marks."""
    raw = path.read_bytes()
    entries = [raw[offset:offset + SIZE] for offset in range(0, len(raw), SIZE)]
    firsts = [struct.unpack_from("<H", e, FORM_INDEX)[0] for e in entries]
    out = {}
    # The form entries follow the species', so the first of them closes the species range.
    for species in range(1, min(f for f in firsts if f)):
        first, forms = firsts[species], entries[species][FORM_COUNT]
        for form in range(max(forms, 1)):
            e = entries[first + form - 1 if 0 < form < forms and first else species]
            if (e[PRESENT] >> 6) & 1:
                out[f"{species}/{form}"] = [*e[:6], e[0x12], e[0x15], *struct.unpack_from("<3H", e, 0x18)]
    return out


def move_pp(path):
    text = path.read_text(encoding="utf-8-sig")
    start = text.index("[", text.index("public static ReadOnlySpan<byte> PP"))
    return [int(v) for v in re.findall(r"\b\d+\b", text[start + 1:text.index("];", start)])]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pkhex", required=True, type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args()
    core = args.pkhex / "PKHeX.Core"
    table = personal(core / "Resources" / "byte" / "personal" / "personal_swsh")
    pp = move_pp(core / "Moves" / "MoveInfo8.cs")
    names = (core / "Resources" / "text" / "other" / "en" / "text_Species_en.txt").read_text(
        encoding="utf-8-sig").splitlines()
    species = sorted({int(k.split("/")[0]) for k in table})
    result = {
        "source": {"pkhex": subprocess.check_output(["git", "-C", str(args.pkhex), "rev-parse", "HEAD"],
                                                    text=True).strip(), "license": "GPL-3.0"},
        "personal": table,
        "move_pp": {str(move): value for move, value in enumerate(pp)},
        "species_names": {str(s): names[s] for s in species},
    }
    args.out.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(table)} species and forms, {len(pp)} moves")


if __name__ == "__main__":
    main()
