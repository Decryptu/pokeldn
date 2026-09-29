"""Reading THUMB code out of a ROM dump: where a function ends, what it calls, what it points at.

Trap: agbcc ends a function `pop {r4,r5,r6}; pop {r1}; bx r1`, not `pop {..., pc}`, so `bx Rn` is a
terminator too; a reader looking only for 0xBDxx walks into the next function. docs/frlg_rom.md.
"""

# `bl` is a pair of halfwords: F800|hi carries offset bits 22..12, F800|lo bits 11..1. PC = address
# + 4.
BL_HI, BL_LO, BL_MASK = 0xF000, 0xF800, 0xF800

# `ldr Rd, [pc, #imm8*4]`, 0x48xx..0x4Fxx: the literal pool holds the addresses a function touches.
LDR_PC, LDR_PC_MASK = 0x4800, 0xF800


def is_return(halfword):
    """`pop {..., pc}` or `bx Rn`: the agbcc epilogue, see the module docstring."""
    return halfword & 0xFF00 == 0xBD00 or halfword & 0xFF87 == 0x4700


def is_prologue(halfword):
    """`push {...}` with or without lr."""
    return halfword & 0xFF00 in (0xB500, 0xB400)


def _halfword(data, at):
    return int.from_bytes(data[at:at + 2], "little")


def function_end(data, base, start, limit):
    """-> where the function at `start` ends. A return is a boundary only when a prologue follows
    within a few halfwords (alignment, literal pool): a function can return from several places."""
    for at in range(start - base, min(limit - base, len(data) - 1), 2):
        if not is_return(_halfword(data, at)):
            continue
        for ahead in range(at + 2, min(at + 12, len(data) - 1), 2):
            if is_prologue(_halfword(data, ahead)):
                return base + at + 2
    return limit


def bl_targets(data, base, start, stop):
    """-> [(call site, absolute target)] for the `bl` pairs between `start` and `stop`."""
    out = []
    for at in range(start - base, min(stop - base, len(data) - 3), 2):
        hi, lo = _halfword(data, at), _halfword(data, at + 2)
        if hi & BL_MASK != BL_HI or lo & BL_MASK != BL_LO:
            continue
        offset = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
        if offset & (1 << 22):
            offset -= 1 << 23
        out.append((base + at, (base + at + 4 + offset) & 0xFFFFFFFF))
    return out


def pc_literals(data, base, start, stop):
    """-> [(site, pool address, value or None)] for the `ldr Rd, [pc, #imm]` between the two;
    None when the pool word falls outside this dump."""
    out = []
    for at in range(start - base, min(stop - base, len(data) - 1), 2):
        word = _halfword(data, at)
        if word & LDR_PC_MASK != LDR_PC:
            continue
        pool = (((base + at) + 4) & ~3) + (word & 0xFF) * 4
        inside = pool - base
        value = (int.from_bytes(data[inside:inside + 4], "little")
                 if 0 <= inside <= len(data) - 4 else None)
        out.append((base + at, pool, value))
    return out
