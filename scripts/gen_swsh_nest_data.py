#!/usr/bin/env python3
"""Builds pokeldn/swsh/data/nest_slots.json, the Max Raid den encounter slots of Sword and Shield
1.3.2 [docs/swsh_raid.md, The den record], from the game's own RomFS file
`bin/archive/field/resident/data_table.gfpak` (file 8, a FlatBuffer; its CRC16 is advert 0xE6).

    ./.venv/bin/python scripts/gen_swsh_nest_data.py --gfpak scratchpad/swsh_raid/nest/data_table_132.gfpak

Rows are [table, slot, species, form, gigantamax]; a table is counted among the tables of its version,
as a guest indexes advert 0xDE (`0x00ea51d0`).
"""

import argparse
import json
import pathlib
import struct
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "pokeldn" / "swsh" / "data" / "nest_slots.json"
NEST_FILE = 8


def lz4_block(src):
    out, i = bytearray(), 0
    while i < len(src):
        token = src[i]; i += 1
        n = token >> 4
        if n == 15:
            while True:
                b = src[i]; i += 1; n += b
                if b != 255:
                    break
        out += src[i:i + n]; i += n
        if i >= len(src):
            break
        back = src[i] | src[i + 1] << 8; i += 2
        m = token & 15
        if m == 15:
            while True:
                b = src[i]; i += 1; m += b
                if b != 255:
                    break
        for _ in range(m + 4):
            out.append(out[-back])
    return bytes(out)


def gfpak_file(data, index):
    """One file of a GFLXPACK: table at the u64 at 0x18, 24 bytes a file (0 stored, 1 zlib, 2 LZ4)."""
    table = struct.unpack_from("<Q", data, 0x18)[0]
    _, comp, size, csize, _, off = struct.unpack_from("<HHIIIQ", data, table + 24 * index)
    raw = data[off:off + csize]
    out = {0: lambda: raw, 1: lambda: zlib.decompress(raw), 2: lambda: lz4_block(raw)}[comp]()
    if len(out) != size:
        raise ValueError(f"file {index}: {len(out)} bytes, expected {size}")
    return out


def nest_rows(d):
    u32 = lambda o: struct.unpack_from("<I", d, o)[0]
    u16 = lambda o: struct.unpack_from("<H", d, o)[0]

    def field(t, idx):
        vt = t - struct.unpack_from("<i", d, t)[0]
        off = 4 + 2 * idx
        if off >= u16(vt):
            return None
        fo = u16(vt + off)
        return t + fo if fo else None

    def vec(t, idx):
        f = field(t, idx)
        if f is None:
            return []
        v = f + u32(f)
        return [v + 4 + 4 * k + u32(v + 4 + 4 * k) for k in range(u32(v))]

    def val(t, idx):
        f = field(t, idx)
        return 0 if f is None else u32(f)

    count, rows = {}, {}
    for t in vec(u32(0), 0):
        version = val(t, 1)
        k = count.get(version, 0)
        count[version] = k + 1
        for slot, e in enumerate(vec(t, 2)):
            rows.setdefault(str(version), []).append([k, slot, val(e, 1), val(e, 2), val(e, 5)])
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gfpak", required=True)
    args = ap.parse_args()
    rows = nest_rows(gfpak_file(pathlib.Path(args.gfpak).read_bytes(), NEST_FILE))
    OUT.write_text(json.dumps({"versions": {"1": "Sword", "2": "Shield"}, "slots": rows},
                              separators=(",", ":")) + "\n")
    print(f"{OUT}: " + ", ".join(f"version {v}: {len(r)} slots" for v, r in rows.items()))


if __name__ == "__main__":
    main()
