#!/usr/bin/env python3
"""Edit an Emerald save so a test reaches the link features without playing to them: the gates are
flags and a spawn point [docs/rse_switch_build.md, Test saves]. Edits the slot the game loads and
redoes each touched sector's checksum; writes SAVE.bak first.

    ./.venv/bin/python tools/rse/emerald_save.py SAVE --link-ready
    ./.venv/bin/python tools/rse/emerald_save.py SAVE --set-flag 0x8DB --warp 2:3:5:4 --copy-party-mon 1

--link-ready is --set-flag FLAG_SYS_POKEDEX_GET, FLAG_SYS_MYSTERY_GIFT_ENABLE and the Oldale Pokemon
Center 2F warp. --warp sets continueGameWarp and CONTINUE_GAME_WARP, so CONTINUE loads that map the
way the game itself does; moving SaveBlock1's pos alone leaves the saved map view and object events
behind. --copy-party-mon N appends a copy of party slot N with a new PID.
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.save.mon import PARTY_MON_SIZE, PARTY_SIZE, to_decrypted, to_encrypted
from pokeldn.frlg.save.save_inject import (
    NUM_SECTORS_PER_SLOT, SECTOR_CHECKSUM_OFF, SECTOR_COUNTER_OFF, SECTOR_DATA_SIZE, SECTOR_ID_OFF,
    SECTOR_SIGNATURE, SECTOR_SIGNATURE_OFF, SECTOR_SIZE, sector_checksum,
)
from pokeldn.rse import constants as c

SAVE_SIZE = 0x20000


def u(data, at, n):
    return int.from_bytes(data[at:at + n], "little")


class Save:
    def __init__(self, data):
        if len(data) < SAVE_SIZE:
            sys.exit(f"an Emerald save is 128 KB; this one is {len(data)} bytes")
        self.data = bytearray(data)
        slots = []
        for index in (0, 1):
            first = index * NUM_SECTORS_PER_SLOT
            ids = {}
            for n in range(first, first + NUM_SECTORS_PER_SLOT):
                at = n * SECTOR_SIZE
                ident = u(self.data, at + SECTOR_ID_OFF, 2)
                if (u(self.data, at + SECTOR_SIGNATURE_OFF, 4) == SECTOR_SIGNATURE and ident < len(c.CHUNK_SIZES)
                        and sector_checksum(self.data[at:], c.CHUNK_SIZES[ident]) == u(self.data, at + SECTOR_CHECKSUM_OFF, 2)):
                    ids[ident] = at
            if len(ids) == NUM_SECTORS_PER_SLOT:
                slots.append((u(self.data, ids[0] + SECTOR_COUNTER_OFF, 4), ids))
        if not slots:
            sys.exit("no complete Emerald save slot in this file")
        self.sectors = max(slots, key=lambda s: (s[0] + 1) & 0xFFFFFFFF)[1]
        self.touched = set()

    def at(self, block, offset):
        """-> the file offset of byte `offset` of SaveBlock2 (block 2) or SaveBlock1 (block 1)."""
        if block == 2:
            ident, inner = 0, offset
        else:
            ident, inner = 1 + offset // SECTOR_DATA_SIZE, offset % SECTOR_DATA_SIZE
        self.touched.add(ident)
        return self.sectors[ident] + inner

    def set_flag(self, flag):
        self.data[self.at(1, c.SAVEBLOCK1_FLAGS + flag // 8)] |= 1 << (flag % 8)

    def warp(self, group, num, x, y):
        at = self.at(1, c.SAVEBLOCK1_CONTINUE_GAME_WARP)
        self.data[at:at + 8] = bytes((group & 0xFF, num & 0xFF, 0xFF, 0)) + x.to_bytes(2, "little", signed=True) + \
            y.to_bytes(2, "little", signed=True)
        self.data[self.at(2, c.SAVEBLOCK2_SPECIAL_SAVE_WARP_FLAGS)] |= c.CONTINUE_GAME_WARP

    def copy_party_mon(self, slot):
        count_at = self.at(1, c.SAVEBLOCK1_PARTY_COUNT)
        count = self.data[count_at]
        if not 0 <= slot < count or count >= PARTY_SIZE:
            sys.exit(f"the party holds {count}; cannot copy slot {slot}")
        src = self.at(1, c.SAVEBLOCK1_PARTY + slot * PARTY_MON_SIZE)
        mon = bytearray(self.data[src:src + PARTY_MON_SIZE])
        plain = bytearray(to_decrypted(bytes(mon[:80])))
        pid = (int.from_bytes(plain[:4], "little") ^ 0x5A5A1234) & 0xFFFFFFFF
        plain[:4] = pid.to_bytes(4, "little")
        mon[:80] = to_encrypted(bytes(plain))
        dst = self.at(1, c.SAVEBLOCK1_PARTY + count * PARTY_MON_SIZE)
        self.data[dst:dst + PARTY_MON_SIZE] = mon
        self.data[count_at] = count + 1

    def finish(self):
        for ident in self.touched:
            at = self.sectors[ident]
            checksum = sector_checksum(self.data[at:], c.CHUNK_SIZES[ident])
            self.data[at + SECTOR_CHECKSUM_OFF:at + SECTOR_CHECKSUM_OFF + 2] = checksum.to_bytes(2, "little")
        return bytes(self.data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save")
    ap.add_argument("--link-ready", action="store_true", help="Pokedex and Mystery Gift flags, spawn on Oldale 2F")
    ap.add_argument("--set-flag", action="append", default=[], type=lambda v: int(v, 0), metavar="FLAG")
    ap.add_argument("--warp", metavar="GROUP:MAP:X:Y")
    ap.add_argument("--copy-party-mon", type=int, metavar="SLOT")
    args = ap.parse_args()

    save = Save(open(args.save, "rb").read())
    flags = list(args.set_flag)
    if args.link_ready:
        flags += [c.FLAG_SYS_POKEDEX_GET, c.FLAG_SYS_MYSTERY_GIFT_ENABLE]
        save.warp(*c.MAP_OLDALE_TOWN_POKEMON_CENTER_2F, 5, 4)
    for flag in flags:
        save.set_flag(flag)
    if args.warp:
        save.warp(*(int(v, 0) for v in args.warp.split(":")))
    if args.copy_party_mon is not None:
        save.copy_party_mon(args.copy_party_mon)
    shutil.copyfile(args.save, args.save + ".bak")
    open(args.save, "r+b").write(save.finish())
    print(f"{args.save}: edited sectors {sorted(save.touched)}; original in {args.save}.bak")


if __name__ == "__main__":
    main()
