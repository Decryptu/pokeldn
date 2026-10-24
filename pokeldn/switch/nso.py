"""A Switch NSO module: its three LZ4 segments laid out at their memory offsets, its dynamic table,
RELATIVE relocations (RELA and RELR), imports and exports. An NSO's vtable slots are empty in the
file and filled from RELATIVE relocations; a RELR entry's addend is the value stored at the slot.
"""

import struct
from pathlib import Path

R_GLOB_DAT, R_JUMP_SLOT, R_ABS64, R_RELATIVE = 1025, 1026, 257, 1027
SEGMENTS = (("text", 0x10, 0x60), ("rodata", 0x20, 0x64), ("data", 0x30, 0x68))


def lz4_block(src, want=None):
    """LZ4 block decompression; raises on a malformed stream rather than returning short."""
    out = bytearray(); i = 0; n = len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255:
                    break
        out += src[i:i + lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8); i += 2
        if off == 0:
            raise ValueError("zero match offset")
        ml = tok & 0xF
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        if start < 0:
            raise ValueError("match before start of output")
        if off >= ml:
            out += out[start:start + ml]
        else:                                   # an overlapping match repeats the last `off` bytes
            out += (out[start:] * (ml // off + 1))[:ml]
    if want is not None and len(out) != want:
        raise ValueError(f"decompressed {len(out)} bytes, header says {want}")
    return bytes(out)


def segments(nso):
    """-> {name: (memory offset, bytes)} of an NSO file's text, rodata and data."""
    if nso[:4] != b"NSO0":
        raise ValueError(f"not an NSO: magic {bytes(nso[:4])!r}")
    flags = struct.unpack_from("<I", nso, 0x0C)[0]
    segs = {}
    for idx, (name, hoff, coff) in enumerate(SEGMENTS):
        foff, moff, dsize = struct.unpack_from("<III", nso, hoff)
        csize = struct.unpack_from("<I", nso, coff)[0]
        raw = nso[foff:foff + csize]
        segs[name] = (moff, lz4_block(raw, dsize) if (flags >> idx) & 1 else bytes(raw[:dsize]))
    return segs


def layout(nso):
    """-> the segments at their memory offsets, extended with zeros to the end of .bss (MOD0)."""
    segs = segments(nso)
    img = bytearray(max(m + len(s) for m, s in segs.values()))
    for m, s in segs.values():
        img[m:m + len(s)] = s
    off = struct.unpack_from("<I", img, 4)[0]
    bss_end = struct.unpack_from("<i", img, off + 12)[0] + off
    if bss_end > len(img):
        img.extend(bytes(bss_end - len(img)))
    return img


def load(img, base=0):
    """-> a laid-out image (bytes, or a path to one) with bss and its RELATIVE slots filled at `base`."""
    if not isinstance(img, (bytes, bytearray)):
        img = Path(img).read_bytes()
    img = bytearray(img)
    off = struct.unpack_from("<I", img, 4)[0]
    bss_end = struct.unpack_from("<i", img, off + 12)[0] + off
    if bss_end > len(img):
        img.extend(bytes(bss_end - len(img)))
    for slot, addend in relatives(bytes(img)):
        if slot + 8 <= len(img):
            struct.pack_into("<Q", img, slot, (addend + base) & 0xFFFFFFFFFFFFFFFF)
    return img


def mod0(img):
    off = struct.unpack_from("<I", img, 4)[0]
    if img[off:off + 4] != b"MOD0":
        raise ValueError(f"no MOD0 at 0x{off:x} (found {bytes(img[off:off + 4])!r})")
    dyn_rel = struct.unpack_from("<i", img, off + 4)[0]
    return off, off + dyn_rel


def dynamic(img, dyn_off):
    tags = {}
    o = dyn_off
    while True:
        tag, val = struct.unpack_from("<qQ", img, o)
        if tag == 0:
            break
        tags.setdefault(tag, val)
        o += 16
    return tags


def _rela_ranges(t):
    return [(t.get(7), t.get(8), t.get(9, 24)), (t.get(23), t.get(2), 24)]


def relatives(img):
    """-> list of (slot_address, addend) for every R_AARCH64_RELATIVE, from RELA and from RELR."""
    _, dyn = mod0(img)
    t = dynamic(img, dyn)
    out = []
    rela, sz, ent = t.get(7), t.get(8), t.get(9, 24)
    if rela is not None:
        for o in range(rela, rela + sz, ent):
            off, info, add = struct.unpack_from("<QQq", img, o)
            if (info & 0xFFFFFFFF) == R_RELATIVE:
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
        entry = struct.unpack_from("<Q", img, o)[0]
        if entry & 1:
            bits, addr = entry >> 1, where
            for k in range(63):
                if bits & (1 << k):
                    slot = addr + 8 * k
                    out.append((slot, struct.unpack_from("<Q", img, slot)[0]))
            where = addr + 8 * 63
        else:
            where = entry
            out.append((where, struct.unpack_from("<Q", img, where)[0]))
            where += 8
    return out


def _symbol_name(img, t, i):
    symtab, strtab, syment = t.get(6), t.get(5), t.get(11, 24)
    o = struct.unpack_from("<I", img, symtab + i * syment)[0]
    e = img.find(b"\0", strtab + o)
    return bytes(img[strtab + o:e]).decode("utf-8", "replace")


def imports(img):
    """-> list of (got_slot, symbol_name) for the GLOB_DAT and JUMP_SLOT relocations."""
    _, dyn = mod0(img)
    t = dynamic(img, dyn)
    out = []
    for rela, sz, ent in _rela_ranges(t):
        if not rela or not sz:
            continue
        for o in range(rela, rela + sz, ent):
            off, info, _add = struct.unpack_from("<QQq", img, o)
            rtype, sym = info & 0xFFFFFFFF, info >> 32
            if rtype in (R_GLOB_DAT, R_JUMP_SLOT) and sym:
                out.append((off, _symbol_name(img, t, sym)))
    return out


def symbols(img):
    """-> (exports name -> value, [(slot, name, addend)] GLOB_DAT / JUMP_SLOT / ABS64 relocations)."""
    _, dyn = mod0(img)
    t = dynamic(img, dyn)
    symtab, strtab, syment = t.get(6), t.get(5), t.get(11, 24)
    nsym = (strtab - symtab) // syment if strtab > symtab else 0
    exports = {}
    for i in range(1, nsym):
        _, _info, _other, shndx, value, _size = struct.unpack_from("<IBBHQQ", img, symtab + i * syment)
        if shndx and value:
            exports.setdefault(_symbol_name(img, t, i), value)
    rel = []
    for rela, sz, ent in _rela_ranges(t):
        if not rela or not sz:
            continue
        for o in range(rela, rela + sz, ent):
            off, info, add = struct.unpack_from("<QQq", img, o)
            if info & 0xFFFFFFFF in (R_GLOB_DAT, R_JUMP_SLOT, R_ABS64) and info >> 32:
                rel.append((off, _symbol_name(img, t, info >> 32), add))
    return exports, rel


def plt_stubs(img, got):
    """PLT stub address -> import name, by the adrp/ldr/add/br shape."""
    n = len(img) // 4
    w = struct.unpack(f"<{n}I", bytes(img[:n * 4]))
    out = {}
    for i in range(n - 3):
        if (w[i] & 0x9F00001F) == 0x90000010 and (w[i + 1] & 0xFFC003FF) == 0xF9400211 \
           and w[i + 3] == 0xD61F0220:
            immlo, immhi = (w[i] >> 29) & 3, (w[i] >> 5) & 0x7FFFF
            imm = (immhi << 2 | immlo)
            imm -= (1 << 21) if imm & (1 << 20) else 0
            slot = ((i * 4) & ~0xFFF) + (imm << 12) + (((w[i + 1] >> 10) & 0xFFF) * 8)
            if slot in got:
                out[i * 4] = got[slot]
    return out
