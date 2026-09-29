#!/usr/bin/env python3
"""Resolve an NSO's R_AARCH64_RELATIVE relocations, so vtable slots can be read.

    ./.venv/bin/python tools/switch/nso_relocs.py IMAGE [ADDEND ...]

An NSO's vtable slots are empty in the image and filled from RELATIVE relocations. RELR (DT_RELR,
tag 0x24) carries no addend: the addend is the value stored at the slot. Legends Z-A uses only RELR.
"""
import struct, sys

def mod0(img):
    off = struct.unpack_from('<I', img, 4)[0]
    if img[off:off+4] != b'MOD0':
        raise ValueError(f"no MOD0 at 0x{off:x} (found {img[off:off+4]!r})")
    dyn_rel, bss_start, bss_end, eh_s, eh_e, modobj = struct.unpack_from('<iiiiii', img, off+4)
    return off, off + dyn_rel

def dynamic(img, dyn_off):
    tags = {}
    o = dyn_off
    while True:
        tag, val = struct.unpack_from('<qQ', img, o)
        if tag == 0: break
        tags.setdefault(tag, val)
        o += 16
    return tags

def relatives(img):
    """-> list of (slot_address, addend) for every R_AARCH64_RELATIVE, from RELA and from RELR."""
    _, dyn = mod0(img)
    t = dynamic(img, dyn)
    out = []
    rela, sz, ent = t.get(7), t.get(8), t.get(9, 24)
    if rela is not None:
        for o in range(rela, rela + sz, ent):
            off, info, add = struct.unpack_from('<QQq', img, o)
            if (info & 0xFFFFFFFF) == 1027:        # R_AARCH64_RELATIVE
                out.append((off, add))
    out += relr(img, t)
    return out


def relr(img, tags=None):
    """-> list of (slot_address, addend) for a DT_RELR table; the addend is the stored value."""
    if tags is None:
        _, dyn = mod0(img)
        tags = dynamic(img, dyn)
    table, sz, ent = tags.get(0x24), tags.get(0x23), tags.get(0x25, 8)
    if table is None or not sz:
        return []
    out, where = [], 0
    for o in range(table, table + sz, ent):
        entry = struct.unpack_from('<Q', img, o)[0]
        if entry & 1:
            bits, addr = entry >> 1, where
            for k in range(63):
                if bits & (1 << k):
                    slot = addr + 8 * k
                    out.append((slot, struct.unpack_from('<Q', img, slot)[0]))
            where = addr + 8 * 63
        else:
            where = entry
            out.append((where, struct.unpack_from('<Q', img, where)[0]))
            where += 8
    return out

if __name__ == "__main__":
    img = open(sys.argv[1], 'rb').read()
    rels = relatives(img)
    print(f"{len(rels):,} RELATIVE relocations")
    want = {int(a, 0) for a in sys.argv[2:]}
    for slot, add in rels:
        if add in want:
            print(f"  slot 0x{slot:08x} -> 0x{add:08x}")
