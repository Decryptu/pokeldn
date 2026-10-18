#!/usr/bin/env python3
"""Builds pokeldn/swsh/data/nest_slots.json, the Max Raid den encounter slots of Sword and Shield
1.3.2 [docs/swsh_raid.md, The den record], and nest_rewards.json, the game's own den drop and bonus
reward tables an event raid's encounters also name [docs/swsh_raid.md, Event raids], from the game's
RomFS file `bin/archive/field/resident/data_table.gfpak` (file 8 the slots, file 7 the drops, file 6
the bonus rewards, each a FlatBuffer; their CRC16s are advert 0xE6, 0xEA and 0xE8).

    ./.venv/bin/python scripts/gen_swsh_nest_data.py --gfpak scratchpad/swsh_raid/nest/data_table_132.gfpak

Rows are [table, slot, species, form, gigantamax, drop table id, bonus table id]; a table is counted
among the tables of its version, as a guest indexes advert 0xDE (`0x00ea51d0`); the ids key
nest_rewards.json (`0x01032570` reads them at vtable 0x10 and 0x12).
"""

import argparse
import json
import pathlib
import struct
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "pokeldn" / "swsh" / "data" / "nest_slots.json"
REWARDS_OUT = OUT.with_name("nest_rewards.json")
NEST_FILE, DROP_FILE, BONUS_FILE = 8, 7, 6


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

    def val64(t, idx):
        f = field(t, idx)
        return 0 if f is None else struct.unpack_from("<Q", d, f)[0]

    count, rows = {}, {}
    for t in vec(u32(0), 0):
        version = val(t, 1)
        k = count.get(version, 0)
        count[version] = k + 1
        for slot, e in enumerate(vec(t, 2)):
            rows.setdefault(str(version), []).append([k, slot, val(e, 1), val(e, 2), val(e, 5),
                                                      str(val64(e, 6)), str(val64(e, 7))])
    return rows


def reward_rows(d):
    """-> {table id: [[item, value at ranks 0 to 4]]} of a NestHoleRewardArchive [pkNX
    NestHoleRewardArchive.fbs]: tables of (u64 id, entries); an entry is (u32 entry, u32 item, [u32])."""
    u32 = lambda o: struct.unpack_from("<I", d, o)[0]

    def field(t, idx):
        vt = t - struct.unpack_from("<i", d, t)[0]
        off = 4 + 2 * idx
        if off >= struct.unpack_from("<H", d, vt)[0]:
            return None
        fo = struct.unpack_from("<H", d, vt + off)[0]
        return t + fo if fo else None

    def vec(at):
        v = at + u32(at)
        return v + 4, u32(v)

    out = {}
    start, count = vec(field(u32(0), 0))
    for k in range(count):
        t = start + 4 * k + u32(start + 4 * k)
        rows = []
        first, n = vec(field(t, 1))
        for j in range(n):
            e = first + 4 * j + u32(first + 4 * j)
            item = field(e, 1)
            values, m = vec(field(e, 2))
            rows.append([u32(item) if item else 0, *struct.unpack_from(f"<{m}I", d, values)])
        out[str(struct.unpack_from("<Q", d, field(t, 0))[0])] = rows
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gfpak", required=True)
    args = ap.parse_args()
    pack = pathlib.Path(args.gfpak).read_bytes()
    rows = nest_rows(gfpak_file(pack, NEST_FILE))
    OUT.write_text(json.dumps({"versions": {"1": "Sword", "2": "Shield"}, "slots": rows},
                              separators=(",", ":")) + "\n")
    print(f"{OUT}: " + ", ".join(f"version {v}: {len(r)} slots" for v, r in rows.items()))
    rewards = {"drop": reward_rows(gfpak_file(pack, DROP_FILE)), "bonus": reward_rows(gfpak_file(pack, BONUS_FILE))}
    REWARDS_OUT.write_text(json.dumps(rewards, separators=(",", ":")) + "\n")
    print(f"{REWARDS_OUT}: {len(rewards['drop'])} drop and {len(rewards['bonus'])} bonus tables")


if __name__ == "__main__":
    main()
