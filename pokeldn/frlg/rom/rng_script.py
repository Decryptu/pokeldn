"""A field script that sets gRngValue with `setptr` [decomp:src/scrcmd.c:300], in the OVERWORLD.

The Mystery Gift link cannot seed: every route out of the menu re-runs `SeedRng`. The script ends
with `end` (0x02), not `endram`, so the binding survives. docs/frlg_rng.md.
"""

from pokeldn.frlg.rom import rom_map

SCR_END = 0x02
SCR_ENDRAM = 0x0D
SCR_SETPTR = 0x11
SCR_PLAYSE = 0x2F
SCR_WAITSE = 0x30

SE_SUCCESS = 25                     # [decomp:include/constants/songs.h:29]
MAX_RAM_SCRIPT_SIZE = 995           # sizeof(struct RamScriptData.script) [decomp:include/global.h]


class RngScriptError(Exception):
    pass


def setptr(value, address):
    value, address = int(value), int(address)
    if not 0 <= value <= 0xFF:
        raise RngScriptError(f"setptr writes ONE byte, got {value}")
    if not 0 <= address <= 0xFFFFFFFF:
        raise RngScriptError(f"0x{address:X} is not a 32-bit address")
    return bytes([SCR_SETPTR, value]) + address.to_bytes(4, "little")


def build_seed_script(value, address=None, sound=SE_SUCCESS):
    """Set a 32-bit word (gRngValue by default); `sound` says it ran, None for silence."""
    address = rom_map.GRNG_VALUE if address is None else int(address)
    value = int(value) & 0xFFFFFFFF
    if address % 4:
        raise RngScriptError(f"0x{address:X} is not word aligned")
    body = b"".join(setptr((value >> (8 * i)) & 0xFF, address + i) for i in range(4))
    if sound is not None:
        body += bytes([SCR_PLAYSE]) + int(sound).to_bytes(2, "little") + bytes([SCR_WAITSE])
    body += bytes([SCR_END])
    if len(body) > MAX_RAM_SCRIPT_SIZE:
        raise RngScriptError(f"{len(body)} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}")
    return body


def describe_seed_script(script):
    """-> lines: what the bytes do, decoded back out of them."""
    lines, i, writes = [], 0, {}
    while i < len(script):
        op = script[i]
        if op == SCR_SETPTR:
            value = script[i + 1]
            address = int.from_bytes(script[i + 2:i + 6], "little")
            writes[address] = value
            lines.append(f"  setptr 0x{value:02X} -> 0x{address:08X}")
            i += 6
        elif op == SCR_PLAYSE:
            lines.append(f"  playse {int.from_bytes(script[i + 1:i + 3], 'little')}")
            i += 3
        elif op == SCR_WAITSE:
            lines.append("  waitse")
            i += 1
        elif op == SCR_END:
            lines.append("  end (the binding SURVIVES; endram 0x0d would clear it)")
            i += 1
        else:
            lines.append(f"  UNKNOWN opcode 0x{op:02X} at {i}")
            break
    base = min(writes) if writes else None
    if base is not None and set(writes) == {base + n for n in range(4)}:
        word = sum(writes[base + n] << (8 * n) for n in range(4))
        what = " (gRngValue)" if base == rom_map.GRNG_VALUE else ""
        lines.append(f"  => 0x{base:08X}{what} = 0x{word:08X}")
    return lines


# `setwildbattle` rolls PID and IVs in four draws with no nature loop [decomp:src/scrcmd.c:1935];
# nothing that yields may sit between the seed and it (a `playse` breaks it). docs/frlg_rng.md.

SCR_SETWILDBATTLE = 0xB6
SCR_DOWILDBATTLE = 0xB7
SCR_RELEASEALL = 0x6B

SCR_GOTO = 0x05
SCR_SETVAR = 0x16
VAR_0x8000 = 0x8000

# Trap: a RAM script never comes back from a battle; MoveSaveBlocks_ResetHeap moves gSaveBlock1
# [decomp:src/battle_main.c:614]. `dowildbattle; end` runs from gSpecialVar_0x8000 via `goto`.
# docs/frlg_rng.md.
BATTLE_TAIL = bytes([SCR_RELEASEALL, SCR_END])      # disassemblers only

# dowildbattle, then end, as the u16 `setvar` writes.
TRAMPOLINE_ADDRESS = rom_map.G_SPECIAL_VAR_0X8000
TRAMPOLINE_WORD = SCR_DOWILDBATTLE | (SCR_END << 8)


def battle_and_exit(species, level, item=0, *, trampoline=None):
    """-> setwildbattle, then the battle from an address the save block cannot move."""
    species, level, item = int(species), int(level), int(item)
    if not 1 <= species <= MAX_SPECIES:
        raise RngScriptError(f"species is 1..{MAX_SPECIES}, got {species}")
    if not 1 <= level <= MAX_LEVEL:
        raise RngScriptError(f"level is 1..{MAX_LEVEL}, got {level}")
    if not 0 <= item <= 0xFFFF:
        raise RngScriptError(f"item is a u16, got {item}")
    address = TRAMPOLINE_ADDRESS if trampoline is None else int(trampoline)
    if address % 2:
        raise RngScriptError(f"0x{address:X} is not a u16 a var command can write")
    return (bytes([SCR_SETWILDBATTLE]) + species.to_bytes(2, "little")
            + bytes([level]) + item.to_bytes(2, "little")
            + bytes([SCR_SETVAR]) + VAR_0x8000.to_bytes(2, "little")
            + TRAMPOLINE_WORD.to_bytes(2, "little")
            + bytes([SCR_GOTO]) + address.to_bytes(4, "little"))

MAX_SPECIES = 411           # the internal table's last entry
MAX_LEVEL = 100


def build_wild_battle_script(seed, species, level, item=0, address=None):
    """Set gRngValue, then roll a wild Pokemon from it and start the battle; `lcg.draws(seed, 4)`
    predicts the mon."""
    address = rom_map.GRNG_VALUE if address is None else int(address)
    species, level, item = int(species), int(level), int(item)
    if not 1 <= species <= MAX_SPECIES:
        raise RngScriptError(f"species is 1..{MAX_SPECIES}, got {species}")
    if not 1 <= level <= MAX_LEVEL:
        raise RngScriptError(f"level is 1..{MAX_LEVEL}, got {level}")
    if not 0 <= item <= 0xFFFF:
        raise RngScriptError(f"item is a u16, got {item}")
    body = build_seed_script(seed, address=address, sound=None)
    if body[-1] != SCR_END:
        raise RngScriptError("the seed script must end with end (0x02)")
    body = body[:-1]                                    # the battle replaces the end
    body += battle_and_exit(species, level, item)       # ...and it ends OUT of the save block
    if len(body) > MAX_RAM_SCRIPT_SIZE:
        raise RngScriptError(f"{len(body)} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}")
    return body


def predict_wild_mon(seed, tid, sid):
    """-> {personality, ivs, shiny, ...} for build_wild_battle_script's four draws. Both PID
    half-orders are reported; shininess and IVs agree either way."""
    from pokeldn.frlg.rom import lcg
    (first, second, third, fourth), _ = lcg.draws(int(seed), 4)
    ivs = (third & 31, (third >> 5) & 31, (third >> 10) & 31,
           fourth & 31, (fourth >> 5) & 31, (fourth >> 10) & 31)
    out = {"ivs": ivs, "iv_total": sum(ivs), "draws": (first, second, third, fourth)}
    for name, personality in (("low_first", first | (second << 16)),
                              ("high_first", second | (first << 16))):
        value = (int(tid) ^ int(sid) ^ (personality >> 16) ^ (personality & 0xFFFF))
        out[name] = {"personality": personality, "shiny_value": value, "shiny": value < 8,
                     "nature": personality % 25, "ability_num": personality & 1}
    out["shiny"] = out["low_first"]["shiny"]
    assert out["shiny"] == out["high_first"]["shiny"], "the shiny test is symmetric in the halves"
    return out


# Reading the seed back: `gift_composer.build_seed_read_script` copies gRngValue into
# gSpecialVar_0x8000/0x8001 (0x020370B4) and prints them.

from pokeldn.frlg.gift.gift_composer import build_seed_read_script     # noqa: E402,F401  (re-exported here)


def seed_from_printed(low, high):
    """-> gRngValue from the NPC's "RNG LO" (bytes 0..1) and "RNG HI" (bytes 2..3) readings."""
    low, high = int(low), int(high)
    for name, value in (("low", low), ("high", high)):
        if not 0 <= value <= 0xFFFF:
            raise RngScriptError(f"the {name} half is a u16 the console printed, got {value}")
    return (high << 16) | low


def check_two_readings(first, second, *, seconds=None):
    """-> lines: whether two readings can both be gRngValue. A distance always exists; only a small
    one (thousands of turns, not ~2**31) says the address is right. `seconds` is optional."""
    from pokeldn.frlg.rom import lcg
    turns = lcg.distance(first, second)
    lines = [f"reading 1  0x{first:08X}",
             f"reading 2  0x{second:08X}",
             f"distance   {turns:,} turns"]
    # A uniformly random pair sits ~2**31 apart.
    plausible = turns < 10 ** 7
    if seconds is not None:
        lines.append(f"           = {turns / float(seconds):,.0f} turns/second over the "
                     f"{seconds} s between them")
    lines.append(
        "  => CONSISTENT with two readings of a live gRngValue: the second is a short walk "
        "along the orbit from the first."
        if plausible else
        "  => NOT consistent: 0x%08X and 0x%08X are ~2**31 apart, which is what two UNRELATED "
        "numbers look like. The address is wrong, or the read tore." % (first, second))
    lines.append(f"  (a distance always exists; this one is 1 in {2 ** 32 // max(turns, 1):,})")
    return lines


from pokeldn.frlg.gift.gift_composer import build_seed_rate_script      # noqa: E402,F401  (re-exported here)


def measure_rate(first, second, frames):
    """-> lines: turns per frame from two readings and an exact `delay` frame count; no clock.
    This is the rate while a field script delays, not while the player walks."""
    from pokeldn.frlg.rom import lcg
    frames = int(frames)
    if frames <= 0:
        raise RngScriptError(f"frames must be positive, got {frames}")
    turns = lcg.distance(first, second)
    per_frame = turns / frames
    lines = [f"before  0x{first:08X}",
             f"after   0x{second:08X}  ({frames} frames later, exactly)",
             f"turns   {turns:,}",
             f"rate    {per_frame:.6f} turns/frame"]
    exact = turns % frames == 0
    if exact:
        lines.append(f"        = EXACTLY {turns // frames} per frame, on every frame of the wait")
    remainder = turns - 2 * frames
    lines.append(f"        vs 2/frame: {remainder:+,} turns over {frames} frames"
                 + (" - the link menu's rate holds here too" if remainder == 0 else ""))
    lines.append(f"        (~{per_frame * 59.7275:,.1f} turns/second at 59.7275 Hz - commentary,"
                 " not data: no clock was used)")
    return lines
