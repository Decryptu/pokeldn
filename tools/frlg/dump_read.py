#!/usr/bin/env python3
"""Decode a save dump taken with `bin/frlg_mg_host.py --buffer-script save-dump`.

    ./.venv/bin/python tools/frlg/dump_read.py DUMP.bin [--block sav1|sav2] [--offset 0x38]

`--block` and `--offset` are whatever the run asked for. SaveBlock2 at offset 0 holds the player
name, gender, play time and the 32-bit trainer id [decomp:include/global.h:327]; SaveBlock1 at 0x34
holds playerPartyCount followed by playerParty[6] [decomp:include/global.h:772].

Party mons decode as a .ek3 does, through pokeldn.frlg.save.mon.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.save import readout
from pokeldn.frlg.text import charmap

PARTY_OFFSET = readout.PARTY_OFFSET
PARTY_COUNT_OFFSET = readout.PARTY_COUNT_OFFSET


_substructs = readout._substructs


def read_party(data, first_offset, tid=None, sid=None):
    """first_offset is where SaveBlock1 0x38 lands inside this dump; IVs as a list, HP ATK DEF SPE SPA
    SPD. The shiny test uses the mon's own OTID; tid/sid are kept for older callers."""
    rows = readout.read_party(data, first_offset)
    for _slot, info, _why in rows:
        if info is not None:
            info["ivs"] = [info["ivs"][name] for name in readout.GAME_ORDER]
    return rows


def _print_trainer(data):
    trainer_id = int.from_bytes(data[0x0A:0x0E], "little")
    print(f"  playerName    {charmap.decode(data[0:8])!r}")
    print(f"  gender        {'girl' if data[8] else 'boy'}")
    print(f"  trainerId     0x{trainer_id:08X}  TID {trainer_id & 0xFFFF}  SID {trainer_id >> 16}")
    print(f"  playTime      {int.from_bytes(data[0x0E:0x10], 'little')}h "
          f"{data[0x10]}m {data[0x11]}s")


def _print_party(data, offset, tid, sid):
    if offset <= PARTY_COUNT_OFFSET < offset + len(data):
        print(f"  playerPartyCount {data[PARTY_COUNT_OFFSET - offset]}")
    party_at = PARTY_OFFSET - offset
    if party_at < 0 or party_at >= len(data):
        print("  SaveBlock1 0x38 (playerParty) is not inside this dump; nothing to decode")
        return
    for slot, info, why in read_party(data, party_at, tid, sid):
        if info is None:
            print(f"  slot {slot + 1}: {why}")
            continue
        shiny = "" if info["shiny"] is None else ("  SHINY" if info["shiny"] else "")
        print(f"  slot {slot + 1}: {info['species_name']:<12} Lv{info['level'] or '?':<3} "
              f"{'EGG ' if info['is_egg'] else ''}"
              f"nick={info['nickname']!r} OT={info['otName']!r} "
              f"PID=0x{info['pid']:08X} {info['nature']:<8} IVs={info['ivs']} "
              f"{'checksum ok' if info['checksum_ok'] else 'CHECKSUM BAD'}{shiny}")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--block", choices=("sav1", "sav2"), default=None,
                    help="which save block the dump came from (default: guessed)")
    ap.add_argument("--offset", type=lambda v: int(v, 0), default=0,
                    help="the --dump-offset the run used")
    ap.add_argument("--tid", type=int, default=None, help="ignored; the shiny test uses each mon's OTID")
    ap.add_argument("--sid", type=int, default=None, help="ignored, likewise")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    with open(a.path, "rb") as fh:
        data = fh.read()
    print(f"{a.path}: {len(data)} bytes from {a.block or 'unknown block'} + 0x{a.offset:x}")

    block = a.block
    if block is None:
        block = "sav2" if a.offset == 0 and 0xFF in data[:8] else "sav1"
        print(f"  (guessed {block}; pass --block to be sure)")

    if block == "sav2" and a.offset == 0 and len(data) >= 0x12:
        _print_trainer(data)
        return
    _print_party(data, a.offset, a.tid, a.sid)


if __name__ == "__main__":
    main()
