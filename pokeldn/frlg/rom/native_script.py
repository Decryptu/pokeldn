"""A RAM script that stages a THUMB stub into gDecompressionBuffer and `callnative`s it: native
code in the OVERWORLD, where the Mystery Gift link cannot go. docs/frlg_rng.md; stubs in asm/field/.

Trap: the entry address carries bit 0 (Thumb), and every stub is run under unicorn before staging;
either mistake freezes the overworld.
"""

import math
from dataclasses import dataclass, field

from pokeldn.frlg.rom import builds, rom_map
from pokeldn.frlg.rom.field_stubs import STUBS
from pokeldn.frlg.rom.resident_stubs import STUBS as RESIDENT_STUBS
from pokeldn.frlg.rom.rng_countdown import NATURE_NAMES, NUM_NATURES
# One `setptr` encoder: duplicated encoders go out of step.
from pokeldn.frlg.rom.rng_script import (MAX_RAM_SCRIPT_SIZE, SCR_END, SCR_SETPTR, RngScriptError,  # noqa: F401
                         SCR_DOWILDBATTLE, SCR_SETWILDBATTLE, SCR_RELEASEALL, SCR_GOTO,
                         SCR_SETVAR, BATTLE_TAIL, TRAMPOLINE_ADDRESS, TRAMPOLINE_WORD,
                         MAX_LEVEL, MAX_SPECIES, SCR_PLAYSE, SCR_WAITSE, SE_SUCCESS,
                         battle_and_exit, setptr)

SCR_CALLNATIVE = 0x23

SETPTR_SIZE = 6                     # opcode + immediate + 4-byte address
CALLNATIVE_SIZE = 5                 # opcode + 4-byte address

SCRATCH = rom_map.GDECOMPRESSION_BUFFER
SCRATCH_SIZE = 0x4000               # [decomp:src/decompress.c, gDecompressionBuffer[0x4000]]

SHINY_ODDS = 8                      # [decomp:include/constants/pokemon.h]


class NativeScriptError(RngScriptError):
    """A field script that would not do what it says, refused before it can reach a console."""


def stage(blob, address=SCRATCH):
    """-> the `setptr` run that writes `blob` to `address`, six script bytes per byte: the field
    engine has no block copy."""
    blob, address = bytes(blob), int(address)
    if not blob:
        raise NativeScriptError("nothing to stage")
    if not 0 <= address <= 0xFFFFFFFF - len(blob):
        raise NativeScriptError(f"0x{address:X} is not a 32-bit address for {len(blob)} bytes")
    return b"".join(setptr(byte, address + i) for i, byte in enumerate(blob))


def callnative_at(address, *, thumb=True):
    """-> one `callnative`; `thumb` sets bit 0."""
    address = int(address)
    if address % 2:
        raise NativeScriptError(f"0x{address:X} is odd; pass the address, the bit is set here")
    if not 0 <= address <= 0xFFFFFFFF:
        raise NativeScriptError(f"0x{address:X} is not a 32-bit address")
    return bytes([SCR_CALLNATIVE]) + (address | (1 if thumb else 0)).to_bytes(4, "little")


def budget(code_size, other=0):
    """-> what staging `code_size` bytes costs against the 995 a RAM script has."""
    staged = int(code_size) * SETPTR_SIZE
    total = staged + CALLNATIVE_SIZE + int(other)
    return {"code_size": int(code_size), "staged_bytes": staged, "other_bytes": int(other),
            "total": total, "limit": MAX_RAM_SCRIPT_SIZE, "spare": MAX_RAM_SCRIPT_SIZE - total,
            "max_code_size": (MAX_RAM_SCRIPT_SIZE - CALLNATIVE_SIZE - int(other)) // SETPTR_SIZE,
            "fits": total <= MAX_RAM_SCRIPT_SIZE}


def stub(name, **params):
    """-> the stub's THUMB bytes with its literal pool patched by assembler symbol, so a renamed
    parameter is an error here."""
    try:
        code, _digest, symbols = STUBS[name]
    except KeyError:
        raise NativeScriptError(f"unknown field stub {name!r}; have {sorted(STUBS)}") from None
    out = bytearray(code)
    for key, value in params.items():
        symbol = f"p_{key}"
        if symbol not in symbols:
            raise NativeScriptError(
                f"{name} has no parameter {key!r}; have "
                f"{sorted(s[2:] for s in symbols if s.startswith('p_'))}")
        offset = symbols[symbol]
        value = int(value) & 0xFFFFFFFF
        out[offset:offset + 4] = value.to_bytes(4, "little")
    return bytes(out)


def build_shiny_hunt_script(species, level, *, item=0, cap=1 << 18, scratch=SCRATCH,
                            rng_address=None, sav2_pointer=None, build=None):
    """The RAM script that makes the next scripted encounter shiny: stage `shiny-seek`, call it,
    then `setwildbattle` + `dowildbattle`, all in one frame [decomp:src/scrcmd.c]. The stub reads
    playerTrainerId through gSaveBlock2Ptr itself [asm/field/shiny-seek.s]."""
    build = builds.resolve(build)
    cap = int(cap)
    if not 1 <= cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {cap}")
    code = stub("shiny-seek",
                rng=build.rng if rng_address is None else int(rng_address),
                sav2ptr=build.sb2ptr if sav2_pointer is None else int(sav2_pointer),
                cap=cap)
    return _stage_and_battle(code, species, level, item=item, scratch=scratch)


# Top of EWRAM: above every symbol the game links, clear until a reset [docs/frlg_rom.md, Where a
# payload can live].
RESIDENT_BASE = 0x0203FC00
RESIDENT_COUNTER = 0x0203FC40
GINTRTABLE_VBLANK = 0x03002730      # gIntrTable[4], French [docs/frlg_rom.md, The per-frame hook]


def resident_words(name="vblank-hook", **params):
    """-> the resident stub as whole words, with its named parameters patched."""
    try:
        code, _digest, symbols = RESIDENT_STUBS[name]
    except KeyError:
        raise NativeScriptError(
            f"unknown resident stub {name!r}; have {sorted(RESIDENT_STUBS)}") from None
    out = bytearray(code)
    for key, value in params.items():
        symbol = f"p_{key}"
        if symbol not in symbols:
            raise NativeScriptError(
                f"{name} has no parameter {key!r}; have "
                f"{sorted(s[2:] for s in symbols if s.startswith('p_'))}")
        at = symbols[symbol]
        out[at:at + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    if len(out) % 4:
        raise NativeScriptError(f"{name} is {len(out)} bytes, not a whole number of words")
    return [int.from_bytes(out[i:i + 4], "little") for i in range(0, len(out), 4)]


# A payload parked in SaveBlock2's filler_B20, untouched by play and by later cards
# [docs/frlg_rom.md, Reading the save].
SAVE_PAYLOAD_MAGIC = 0x444C4B50         # "PKLD", the loader's guard
SAVE_PAYLOAD_OFFSET = 0xB20             # filler_B20 inside SaveBlock2 [decomp:include/global.h:357]
SAVE_PAYLOAD_SIZE = 0x400               # the whole of filler_B20; written over two sessions
SAVE_PAYLOAD_COUNTER = 0x0203FBB0  # below the blob: a full-size payload reaches the top of EWRAM
# Fixed well clear of the head: gIntrTable[4] reads the hook's address.
HOOK_OFFSET = 0x140
PROBE_OUT_OFFSET = 0x300                # seven header words, then four per number
PROBE_RESULTS_OFFSET = PROBE_OUT_OFFSET + 28
# Above the results; the builder refuses an overlap.
LRSAVE_OFFSET = 0x3BC                   # the hook parks lr here while it calls the thunk
# Which experiment the blob is: without it, two probes differ in the tail by the checksum alone, and
# a tail-only diff cannot tell a delivered tail from a skipped one.
TAIL_MARK_OFFSET = 0x3F0                # clear of the results, the lr scratch and the thunk
# Default r0..r3: distinct and non-zero, so a register the syscall leaves alone reads differently
# from one it zeroes.
PROBE_MARKERS = (0xA5A00052, 0xA5B00001, 0xA5C00002, 0xA5D00003)
PROBE_THUNK_OFFSET = 0x3C0              # `swi N ; bx lr`, assembled into the blob by the builder
# Trap: the save's copy of the hook's tail target must be the measured handler, never zero: the
# loader may copy over a live hook, and a second visit patches nothing. docs/frlg_rom.md.
VBLANK_HANDLER = 0x0800071D             # VBlankIntr, French; a build's is Build.vblank_intr


def build_save_payload(*, base=RESIDENT_BASE, size=SAVE_PAYLOAD_SIZE,
                       counter=SAVE_PAYLOAD_COUNTER, table_entry=None,
                       magic=SAVE_PAYLOAD_MAGIC, filler_byte=None, original=None,
                       probe=0, probe_args=(), probe_count=1, burst=0, probe_a0_step=0,
                       probe_num_step=1, probe_store=True, build=None):
    """-> the blob to park in the save: magic, installer, the V-blank hook, filler, checksum. The
    installer installs nothing unless the sum matches, so a truncated arrival is a miss.
    `table_entry` and `original` default to `build`'s gIntrTable[4] and VBlankIntr."""
    build = builds.resolve(build)
    table_entry = build.intr_vblank if table_entry is None else table_entry
    original = build.vblank_intr | 1 if original is None else original
    head, _digest, symbols = RESIDENT_STUBS["save-payload"]
    hook_params = {"counter": counter, "original": original, "burst": int(burst or 0),
                   "thunk": (base + PROBE_THUNK_OFFSET) | 1, "lrsave": base + LRSAVE_OFFSET}
    hook = b"".join(w.to_bytes(4, "little")
                    for w in resident_words("vblank-hook", **hook_params))
    # From the hook's symbol table: the hook has grown twice and a counted offset goes stale.
    hook_original_at = base + HOOK_OFFSET + RESIDENT_STUBS["vblank-hook"][2]["p_original"]
    if len(head) > HOOK_OFFSET:
        raise NativeScriptError(
            f"the payload head is {len(head)} bytes and the hook sits at {HOOK_OFFSET:#x}")
    filler_start = HOOK_OFFSET + len(hook)
    # The installer sums the whole blob: a filler-only sum cannot see the head, and a control head
    # with a probe tail passed it on a live console.
    sum_from = 0
    checksum_at = size - 4
    if checksum_at <= filler_start:
        raise NativeScriptError(f"{size} bytes leaves no room for filler")
    blob = bytearray(size)
    blob[0:len(head)] = head
    blob[HOOK_OFFSET:HOOK_OFFSET + len(hook)] = hook
    # Non-zero filler, so a short arrival sums differently.
    for i in range(filler_start, checksum_at):
        blob[i] = (i & 0xFF) if filler_byte is None else (filler_byte & 0xFF)
    # The thunk lives inside the filler so the checksum covers it.
    if probe:
        if not 0 <= int(probe) <= 0xFF:
            raise NativeScriptError(f"a Thumb `swi` takes 0..255, got {probe}")
        # The last number reached: with probe_num_step 0 the sweep calls one syscall count times and
        # walks r0.
        if int(probe_count) < 1:
            raise NativeScriptError(f"a sweep runs at least once, got {probe_count}")
        last = int(probe) + (int(probe_count) - 1) * int(probe_num_step)
        if not 0 <= last <= 0xFF:
            raise NativeScriptError(
                f"a sweep of {probe_count} from {probe:#x} stepping {probe_num_step} ends at "
                f"{last:#x}, outside the 0..255 a Thumb `swi` takes")
        # Only a storing run is bounded by the result region; a breakpoint read on the wrapper's
        # side fits all 256 selectors.
        room = LRSAVE_OFFSET - PROBE_RESULTS_OFFSET
        if probe_store and int(probe_count) * 16 > room:
            raise NativeScriptError(
                f"{probe_count} numbers need {probe_count * 16} bytes of results and there are "
                f"{room} between the block and the thunk; pass probe_store=False to sweep without "
                f"storing, when the answer is read from the wrapper's side")
        if int(probe_count) > 0x100:
            raise NativeScriptError(f"a sweep of {probe_count} passes more than 256 selectors")
        for at in (PROBE_OUT_OFFSET, PROBE_THUNK_OFFSET):
            if not filler_start <= at < checksum_at - 0x20:
                raise NativeScriptError(f"{at:#x} is not inside the filler of a {size}-byte blob")
        blob[PROBE_THUNK_OFFSET:PROBE_THUNK_OFFSET + 4] = \
            (0xDF00 | int(probe)).to_bytes(2, "little") + (0x4770).to_bytes(2, "little")
    # Markers are the default: zero in, zero out measures nothing.
    args = list(probe_args or ())
    args += PROBE_MARKERS[len(args):]
    if probe and any(v == 0 for v in args[:4]):
        raise NativeScriptError(
            "every probe register needs a distinct non-zero marker, or a register the syscall "
            f"leaves alone reads the same as one it zeroes; got {[hex(v) for v in args[:4]]}")
    patches = {"magic": magic, "hook": (base + HOOK_OFFSET) | 1, "table_entry": table_entry,
               "counter": counter, "filler_start": base + sum_from,
               "filler_end": base + checksum_at, "checksum_at": base + checksum_at,
               "hook_original_at": hook_original_at,
               "probe_first": int(probe or 0),
               "probe_count": int(probe_count) if probe else 0,
               "probe_num_step": int(probe_num_step),
               "probe_store": 1 if probe_store else 0,
               "probe_out": base + PROBE_OUT_OFFSET,
               "probe_thunk": (base + PROBE_THUNK_OFFSET) | 1,
               "probe_a0": args[0], "probe_a0_step": int(probe_a0_step),
               "probe_a1": args[1],
               "probe_a2": args[2], "probe_a3": args[3]}
    for key, value in patches.items():
        at = symbols[f"p_{key}"]
        blob[at:at + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    # The tail mark: the probe plus a fold of the head sum, written after the patches. It names the
    # head it was built against, so a head from one build and a tail from another reads as a
    # chimera; the checksum only says something is wrong.
    if probe:
        if not filler_start <= TAIL_MARK_OFFSET < checksum_at - 4:
            raise NativeScriptError(f"{TAIL_MARK_OFFSET:#x} is not inside the filler")
        for at, span in ((PROBE_THUNK_OFFSET, 4), (LRSAVE_OFFSET, 4)):
            if at < TAIL_MARK_OFFSET + 4 and TAIL_MARK_OFFSET < at + span:
                raise NativeScriptError(f"the tail mark at {TAIL_MARK_OFFSET:#x} overlaps {at:#x}")
        from pokeldn.frlg.rom.buffer_script import MAX_SAVE_WRITE_BYTES
        head_end = min(MAX_SAVE_WRITE_BYTES, size)
        if TAIL_MARK_OFFSET < head_end:
            raise NativeScriptError(
                f"the tail mark at {TAIL_MARK_OFFSET:#x} is inside the head, which it sums")
        # Folded, not truncated: the low half alone is blind to a change in a word's upper bits
        # (0x00200000 -> 0x01000000 happened).
        head_sum = sum(int.from_bytes(blob[i:i + 4], "little")
                       for i in range(0, head_end - head_end % 4, 4)) & 0xFFFFFFFF
        folded = (head_sum ^ (head_sum >> 16)) & 0xFFFF
        mark = (folded << 16) | ((int(probe) & 0xFF) << 8) | min(int(probe_count), 0xFF)
        blob[TAIL_MARK_OFFSET:TAIL_MARK_OFFSET + 4] = mark.to_bytes(4, "little")
    # Last: the sum covers the head, which the patches write.
    total = sum(int.from_bytes(blob[i:i + 4], "little")
                for i in range(sum_from, checksum_at, 4)) & 0xFFFFFFFF
    blob[checksum_at:checksum_at + 4] = total.to_bytes(4, "little")
    return bytes(blob)


def save_write_chunks(blob, *, offset=SAVE_PAYLOAD_OFFSET, limit=None):
    """-> [(offset, bytes)]: the blob split into `MAX_SAVE_WRITE_BYTES` save-write sessions."""
    from pokeldn.frlg.rom.buffer_script import MAX_SAVE_WRITE_BYTES
    limit = MAX_SAVE_WRITE_BYTES if limit is None else int(limit)
    blob = bytes(blob)
    return [(offset + at, blob[at:at + limit]) for at in range(0, len(blob), limit)]


def build_loader_script(*, base=RESIDENT_BASE, size=SAVE_PAYLOAD_SIZE,
                        offset=SAVE_PAYLOAD_OFFSET, magic=SAVE_PAYLOAD_MAGIC,
                        sav2_pointer=None, scratch=SCRATCH, sound=SE_SUCCESS, build=None):
    """The RAM script that copies the payload out of the save and runs it. gSaveBlock2Ptr is read
    every time: the block moves on every battle and load."""
    if size % 4:
        raise NativeScriptError(f"{size} bytes is not a whole number of words")
    code = stub("save-loader",
                sav2ptr=(builds.resolve(build).sb2ptr if sav2_pointer is None
                         else int(sav2_pointer)),
                offset=offset, dest=base, words=size // 4, magic=magic)
    tail = b""
    if sound is not None:
        tail += bytes([SCR_PLAYSE]) + int(sound).to_bytes(2, "little") + bytes([SCR_WAITSE])
    tail += bytes([SCR_END])
    body = stage(code, scratch) + callnative_at(scratch) + tail
    plan = budget(len(code), other=len(tail))
    if not plan["fits"]:
        raise NativeScriptError(f"{plan['total']} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}")
    return body


def build_install_hook_script(*, base=RESIDENT_BASE, counter=RESIDENT_COUNTER,
                              table_entry=None, scratch=SCRATCH, sound=SE_SUCCESS, build=None):
    """The RAM script that installs the resident V-blank hook from the save, with no link, on any
    boot: `AgbMain` clears EWRAM [decomp:src/main.c:134], so a gift session can never find a live
    hook. `install-vblank-hook` reads the table entry and chains whatever handler is there."""
    # `original` is the measured handler: a second visit re-copies this one.
    build = builds.resolve(build)
    table_entry = build.intr_vblank if table_entry is None else table_entry
    words = resident_words("vblank-hook", counter=counter, original=build.vblank_intr | 1)
    original_at = base + RESIDENT_STUBS["vblank-hook"][2]["p_original"]
    code = stub("install-vblank-hook",
                table_entry=table_entry, hook_ptr=base | 1, resident=base, counter=counter,
                original_at=original_at, words=len(words))
    tail_at = STUBS["install-vblank-hook"][2]["_words"]
    code = code[:tail_at] + b"".join(w.to_bytes(4, "little") for w in words)
    tail = b""
    if sound is not None:
        tail += bytes([SCR_PLAYSE]) + int(sound).to_bytes(2, "little") + bytes([SCR_WAITSE])
    tail += bytes([SCR_END])
    body = stage(code, scratch) + callnative_at(scratch) + tail
    plan = budget(len(code), other=len(tail))
    if not plan["fits"]:
        raise NativeScriptError(
            f"{plan['total']} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}")
    assert len(body) == plan["total"]
    return body


def _stage_and_battle(code, species, level, *, item=0, scratch=SCRATCH):
    """-> the staged stub, the call, and the encounter, via `battle_and_exit`: a battle moves the
    save block the RAM script lives in [rng_script]."""
    try:
        battle = battle_and_exit(species, level, item)
    except RngScriptError as error:
        raise NativeScriptError(str(error)) from None
    body = stage(code, scratch) + callnative_at(scratch) + battle
    plan = budget(len(code), other=len(battle))
    if not plan["fits"]:
        raise NativeScriptError(
            f"{plan['total']} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}; the stub is "
            f"{len(code)} bytes and at most {plan['max_code_size']} can be staged")
    assert len(body) == plan["total"]
    return body


# mon-seek tests all four draws: shininess, nature and the six IVs [decomp:src/pokemon.c:1836]. The
# host half of asm/field/mon-seek.s.

# Draw order, which the packed words use; a summary screen puts SPEED last.
IV_FIELDS = ("hp", "attack", "defense", "speed", "sp_attack", "sp_defense")
MAX_IV = 31                             # MAX_PER_STAT_IVS [decomp:include/constants/pokemon.h]
IV_BITS = 5
IV_TERMINATOR_BIT = 30                  # asm/field/mon-seek.s: the loop counts with this bit
ANY_NATURE = (1 << NUM_NATURES) - 1

# Counted off the disassembly, asserted under unicorn: 15 THUMB instructions for a non-shiny state.
INSTRUCTIONS_PER_ITERATION = 15

# A search freezes the overworld with no way out. The ceiling is on the whole cap, which `cap_for`
# makes 1 search in 100; an estimate from the GBA clock, not a measurement.
MAX_FREEZE_FRAMES = 900                 # ~15 s at 59.7275 Hz
SEARCH_CONFIDENCE = 0.99                # the default cap is the one that finds a state this often


@dataclass(frozen=True)
class MonCriteria:
    """What mon-seek will accept; the hot loop always tests shininess. `natures` is nature ids
    (empty = any), `iv_minimums` six floors in draw order (IV_FIELDS)."""

    natures: tuple = ()
    iv_minimums: tuple = field(default_factory=lambda: (0,) * len(IV_FIELDS))

    def __post_init__(self):
        natures = tuple(sorted({int(n) for n in self.natures}))
        for nature in natures:
            if not 0 <= nature < NUM_NATURES:
                raise NativeScriptError(
                    f"nature ids are 0..{NUM_NATURES - 1}, got {nature}")
        minimums = tuple(int(v) for v in self.iv_minimums)
        if len(minimums) != len(IV_FIELDS):
            raise NativeScriptError(
                f"iv_minimums takes {len(IV_FIELDS)} floors in draw order "
                f"({', '.join(IV_FIELDS)}), got {len(minimums)}")
        for value in minimums:
            if not 0 <= value <= MAX_IV:
                raise NativeScriptError(f"an IV floor is 0..{MAX_IV}, got {value}")
        object.__setattr__(self, "natures", natures)
        object.__setattr__(self, "iv_minimums", minimums)

    @property
    def nature_mask(self):
        """-> p_nature: bit N set = nature N accepted; none named means every one."""
        if not self.natures:
            return ANY_NATURE
        mask = 0
        for nature in self.natures:
            mask |= 1 << nature
        return mask

    @property
    def iv_word(self):
        """-> p_ivmin: six 5-bit floors, plus the terminator the stub's loop counts with."""
        word = 1 << IV_TERMINATOR_BIT
        for index, minimum in enumerate(self.iv_minimums):
            word |= minimum << (IV_BITS * index)
        return word

    @property
    def probability(self):
        """-> roughly what fraction of states pass all three tests; shininess and nature share the
        personality, which the estimate ignores (negligibly)."""
        chance = SHINY_ODDS / 65536
        chance *= (len(self.natures) or NUM_NATURES) / NUM_NATURES
        for minimum in self.iv_minimums:
            chance *= (MAX_IV + 1 - minimum) / (MAX_IV + 1)
        return chance

    def describe(self):
        """-> one line naming everything asked for, read back out of the packed words."""
        parts = ["shiny"]
        if self.natures:
            parts.append("/".join(NATURE_NAMES[n] for n in self.natures))
        floors = [f"{name} >= {value}"
                  for name, value in zip(IV_FIELDS, self.iv_minimums) if value]
        parts.extend(floors)
        return ", ".join(parts)


def parse_natures(text):
    """-> the nature ids in `text`: names as the game spells them, or plain numbers."""
    if text is None or not str(text).strip():
        return ()
    lowered = {name.lower(): index for index, name in enumerate(NATURE_NAMES)}
    out = []
    for token in str(text).replace(",", " ").split():
        if token.lower() in lowered:
            out.append(lowered[token.lower()])
            continue
        try:
            value = int(token, 0)
        except ValueError:
            raise NativeScriptError(
                f"{token!r} is not a nature; they are {', '.join(NATURE_NAMES)}") from None
        if not 0 <= value < NUM_NATURES:
            raise NativeScriptError(f"nature ids are 0..{NUM_NATURES - 1}, got {value}")
        out.append(value)
    return tuple(sorted(set(out)))


def parse_iv_minimums(items):
    """-> six floors in draw order, from `stat=value` strings (`speed=31`, `hp=20`)."""
    minimums = [0] * len(IV_FIELDS)
    for item in items or ():
        text = str(item).replace(">=", "=").replace(":", "=")
        name, _, value = text.partition("=")
        name = name.strip().lower().replace("-", "_")
        aliases = {"atk": "attack", "def": "defense", "spe": "speed", "spd": "speed",
                   "spa": "sp_attack", "spatk": "sp_attack", "spdef": "sp_defense",
                   "spd_def": "sp_defense"}
        name = aliases.get(name, name)
        if name not in IV_FIELDS:
            raise NativeScriptError(
                f"{item!r} does not name an IV; they are {', '.join(IV_FIELDS)}")
        try:
            floor = int(value, 0)
        except ValueError:
            raise NativeScriptError(f"{item!r} needs a floor, as in {name}=31") from None
        if not 0 <= floor <= MAX_IV:
            raise NativeScriptError(f"an IV floor is 0..{MAX_IV}, got {floor}")
        minimums[IV_FIELDS.index(name)] = floor
    return tuple(minimums)


def frames_for_iterations(iterations):
    """-> how long a search of this many states blocks the field engine, in frames (an estimate)."""
    return frames_for(float(iterations) * INSTRUCTIONS_PER_ITERATION)


def probability_for(criteria, placements=1):
    """-> the fraction of states that pass when the IV floors must hold in `placements` words
    (mon-seek-both tests two, docs/frlg_rng.md); the personality terms are not raised."""
    chance = SHINY_ODDS / 65536
    chance *= (len(criteria.natures) or NUM_NATURES) / NUM_NATURES
    ivs = 1.0
    for minimum in criteria.iv_minimums:
        ivs *= (MAX_IV + 1 - minimum) / (MAX_IV + 1)
    return chance * ivs ** int(placements)


def cap_for(criteria, confidence=SEARCH_CONFIDENCE, placements=1):
    """-> the smallest cap that finds a state `confidence` of the time."""
    chance = probability_for(criteria, placements)
    if not 0 < confidence < 1:
        raise NativeScriptError(f"confidence is a probability, got {confidence}")
    return max(1, math.ceil(math.log1p(-confidence) / math.log1p(-chance)))


def search_cost(criteria, cap, placements=1):
    """-> expected and worst-case search cost, in frames; an estimate from the GBA clock."""
    chance = probability_for(criteria, placements)
    cap = int(cap)
    expected = 1 / chance
    return {"probability": chance,
            "expected_iterations": expected,
            "expected_frames": frames_for_iterations(expected),
            "expected_seconds": frames_for_iterations(expected) / 59.7275,
            "cap": cap,
            "worst_frames": frames_for_iterations(cap),
            "worst_seconds": frames_for_iterations(cap) / 59.7275,
            "found_within_cap": 1 - (1 - chance) ** cap}


def build_mon_hunt_script(species, level, *, criteria=None, item=0, cap=None,
                          max_freeze_frames=MAX_FREEZE_FRAMES, scratch=SCRATCH,
                          rng_address=None, sav2_pointer=None, build=None):
    """The RAM script that makes the next scripted encounter a mon matching `criteria`, in one frame
    like build_shiny_hunt_script. A cap whose worst case exceeds `max_freeze_frames` is refused
    before the card is built."""
    criteria = MonCriteria() if criteria is None else criteria
    if not isinstance(criteria, MonCriteria):
        raise NativeScriptError("criteria must be a MonCriteria")
    chosen_cap = cap_for(criteria) if cap is None else int(cap)
    cost = search_cost(criteria, chosen_cap)
    # The freeze check comes first: a cap past its range is always past this ceiling too.
    if cost["worst_frames"] > max_freeze_frames:
        raise NativeScriptError(
            f"{criteria.describe()} is 1 state in {1 / cost['probability']:,.0f}: searching for "
            f"it can block the overworld for {cost['worst_frames']:,.0f} frames "
            f"({cost['worst_seconds']:.1f} s), past the {max_freeze_frames} frame ceiling. Ask "
            f"for less, or raise max_freeze_frames deliberately.")
    if not 1 <= chosen_cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {chosen_cap}")
    build = builds.resolve(build)
    code = stub("mon-seek",
                rng=build.rng if rng_address is None else int(rng_address),
                sav2ptr=build.sb2ptr if sav2_pointer is None else int(sav2_pointer),
                cap=chosen_cap, nature=criteria.nature_mask, ivmin=criteria.iv_word)
    return _stage_and_battle(code, species, level, item=item, scratch=scratch)


def describe(script):
    """-> lines: what the bytes do, decoded; a run of `setptr` is collapsed to one line."""
    lines, i, run = [], 0, []

    def flush():
        if run:
            base = run[0][0]
            lines.append(f"  setptr x{len(run)} -> 0x{base:08X}..0x{run[-1][0]:08X}  "
                         f"({bytes(v for _, v in run)[:8].hex()}...)")
            run.clear()

    while i < len(script):
        op = script[i]
        if op == SCR_SETPTR:
            run.append((int.from_bytes(script[i + 2:i + 6], "little"), script[i + 1]))
            i += SETPTR_SIZE
            continue
        flush()
        if op == SCR_CALLNATIVE:
            address = int.from_bytes(script[i + 1:i + 5], "little")
            state = "THUMB" if address & 1 else "ARM"
            lines.append(f"  callnative 0x{address:08X} ({state})")
            i += CALLNATIVE_SIZE
        elif op == SCR_SETWILDBATTLE:
            species = int.from_bytes(script[i + 1:i + 3], "little")
            lines.append(f"  setwildbattle species {species} Lv{script[i + 3]} "
                         f"item {int.from_bytes(script[i + 4:i + 6], 'little')}")
            i += 6
        elif op == SCR_SETVAR:
            var = int.from_bytes(script[i + 1:i + 3], "little")
            value = int.from_bytes(script[i + 3:i + 5], "little")
            note = ""
            if var == 0x8000 and value == TRAMPOLINE_WORD:
                note = "  (dowildbattle; end, at gSpecialVar_0x8000 - out of the save block)"
            lines.append(f"  setvar 0x{var:04X} = 0x{value:04X}{note}")
            i += 5
        elif op == SCR_GOTO:
            target = int.from_bytes(script[i + 1:i + 5], "little")
            where = " (the trampoline)" if target == TRAMPOLINE_ADDRESS else ""
            lines.append(f"  goto 0x{target:08X}{where}")
            i += 5
            # Nothing after an unconditional `goto` is script; on a body-hosted card it is the
            # payload.
            if i < len(script):
                lines.append(f"  ... {len(script) - i} bytes of payload at offset {i}, never "
                             f"read by the engine (the trampoline branches to it)")
                break
        elif op == SCR_DOWILDBATTLE:
            lines.append("  dowildbattle (yields; the battle RESUMES the script after it)")
            i += 1
        elif op == SCR_RELEASEALL:
            lines.append("  releaseall")
            i += 1
        elif op == SCR_END:
            lines.append("  end (the binding SURVIVES; endram 0x0d would clear it)")
            i += 1
        else:
            lines.append(f"  UNKNOWN opcode 0x{op:02X} at {i}")
            break
    flush()
    return lines


# Every stub runs under unicorn first [docs/frlg_rom.md]: a hanging field stub freezes the overworld
# with no menu.

_EWRAM, _EWRAM_SIZE = 0x02000000, 0x40000
_IWRAM, _IWRAM_SIZE = 0x03000000, 0x8000
_STACK, _STACK_SIZE = 0x03007000, 0x1000        # inside IWRAM, where the GBA's sp lives
_RETURN = 0x02FF0000                            # mapped, never executed
_INSTRUCTION_LIMIT = 1 << 24


def emulate(code, *, base=SCRATCH, memory=None, instruction_limit=_INSTRUCTION_LIMIT):
    """Run a staged stub as `callnative` does (no arguments, Thumb, returns to lr). `memory` is
    {address: bytes} placed before and read back after: a field stub speaks only through memory."""
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UcError
    from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(_EWRAM, _EWRAM_SIZE)
    uc.mem_map(_IWRAM, _IWRAM_SIZE)
    uc.mem_map(_RETURN & ~0xFFF, 0x1000)
    code = bytes(code)
    uc.mem_write(base, code)
    for address, blob in (memory or {}).items():
        uc.mem_write(int(address), bytes(blob))
    counted = [0]
    uc.hook_add(UC_HOOK_CODE, lambda *_args: counted.__setitem__(0, counted[0] + 1))
    uc.reg_write(UC_ARM_REG_SP, _STACK + _STACK_SIZE - 0x40)
    uc.reg_write(UC_ARM_REG_LR, _RETURN | 1)
    try:
        uc.emu_start(base | 1, _RETURN, count=instruction_limit)
    except UcError as error:
        raise NativeScriptError(f"the stub faulted: {error}") from error
    if uc.reg_read(UC_ARM_REG_PC) & ~1 != _RETURN:
        raise NativeScriptError(
            f"the stub had not returned after {instruction_limit} instructions. In the overworld "
            "that is a frozen game with no menu to back out of.")
    return {"instructions": counted[0],
            "memory": {int(a): bytes(uc.mem_read(int(a), len(b)))
                       for a, b in (memory or {}).items()}}


# 16.78 MHz, 280,896 cycles a frame. Code runs from EWRAM (16-bit, waitstates), ~3 cycles an
# instruction: an average search is a little over one frame. Interrupts stay enabled, so the music
# carries on. An estimate, not measured.
CYCLES_PER_INSTRUCTION_FROM_EWRAM = 3
CYCLES_PER_FRAME = 280896


def frames_for(instructions):
    """-> roughly how many frames a stub of this length blocks the field engine for."""
    return int(instructions) * CYCLES_PER_INSTRUCTION_FROM_EWRAM / CYCLES_PER_FRAME


# Payload in the script body, one byte each: `GetRamScript` returns a pointer into
# gSaveBlock1Ptr->ramScript.data [decomp:src/script.c:514] and never reads past the last command.
# The block moves, so a 36-byte trampoline reads &gSaveBlock1Ptr at run time. docs/frlg_rng.md.

RAMSCRIPT_IN_SAVEBLOCK1 = 0x361C        # SaveBlock1.ramScript [decomp:include/global.h]
RAMSCRIPT_MAGIC_OFFSET = RAMSCRIPT_IN_SAVEBLOCK1 + 4        # past the u32 checksum
RAMSCRIPT_BODY_OFFSET = RAMSCRIPT_MAGIC_OFFSET + 4          # past magic, mapGroup, mapNum, objectId
RAM_SCRIPT_MAGIC = 51                   # [decomp:src/script.c:12], written by InitRamScript [:505]

# The hunt's report: SaveBlock1.unused_348C[400] [decomp:include/global.h], zero on the console,
# outside ramScript so the RAM script checksum holds. docs/frlg_rng.md.
HUNT_LOG_OFFSET = 0x348C
HUNT_LOG_MAGIC = 0x474F4C31             # so an untouched region is not read as a report
HUNT_LOG_SIZE = 20
HUNT_LOG_FIELDS = ("magic", "start", "found", "iterations", "cap")

TRAMPOLINE_STUB = "ram-jump"

# Trap: the payload starts at a multiple of four. `ldr [pc]` and `adr` use Align(PC, 4); two bytes
# off, every pool word is read two bytes late. Four suffices: the save-block shift is `& 0x7C`
# [decomp:src/load_save.c:75].
BODY_ALIGNMENT = 4


def ram_jump_stub(payload_offset, *, sb1_pointer=None, magic_offset=RAMSCRIPT_MAGIC_OFFSET,
                  build=None):
    """-> the trampoline, patched to branch `payload_offset` bytes into the body; `p_entry` is
    measured from the magic byte [asm/field/ram-jump.s]."""
    offset = int(payload_offset)
    if offset < 0:
        raise NativeScriptError(f"the payload offset is not negative, got {offset}")
    if offset % 4:
        raise NativeScriptError(
            f"the payload must start at a MULTIPLE OF FOUR, got {offset}; see BODY_ALIGNMENT")
    entry = (RAMSCRIPT_BODY_OFFSET - int(magic_offset)) + offset
    return stub(TRAMPOLINE_STUB,
                sb1ptr=(builds.resolve(build).sb1ptr if sb1_pointer is None
                        else int(sb1_pointer)),
                magic=int(magic_offset), entry=entry | 1)


def body_prefix_size(tail_size):
    """-> script bytes before the payload; the trampoline's length is independent of its patch."""
    size = len(STUBS[TRAMPOLINE_STUB][0]) * SETPTR_SIZE + CALLNATIVE_SIZE + int(tail_size)
    return size + (-size % BODY_ALIGNMENT)


def body_capacity(tail_size):
    """-> how many payload bytes fit after a tail of `tail_size`, and what the old way allowed."""
    prefix = body_prefix_size(tail_size)
    staged = (MAX_RAM_SCRIPT_SIZE - CALLNATIVE_SIZE - int(tail_size)) // SETPTR_SIZE
    return {"prefix": prefix, "payload": MAX_RAM_SCRIPT_SIZE - prefix,
            "staged_equivalent": staged, "limit": MAX_RAM_SCRIPT_SIZE}


def build_body_script(payload, tail=b"", *, scratch=SCRATCH, sb1_pointer=None, build=None):
    """-> the RAM script that stages the trampoline, calls it, runs `tail`, and carries `payload`:

        setptr x36 (trampoline) | callnative | <tail, ends in goto> | <pad> | <payload>

    The trampoline branches, so the payload's `pop {r4-r7, pc}` returns into `tail`."""
    payload = bytes(payload)
    tail = bytes(tail)
    if not payload:
        raise NativeScriptError("nothing to run")
    prefix = body_prefix_size(len(tail))
    code = ram_jump_stub(prefix, sb1_pointer=sb1_pointer, build=build)
    body = (stage(code, scratch) + callnative_at(scratch) + tail
            + b"\x00" * (prefix - len(stage(code, scratch)) - CALLNATIVE_SIZE - len(tail))
            + payload)
    assert body.index(payload, prefix) == prefix
    if len(body) > MAX_RAM_SCRIPT_SIZE:
        raise NativeScriptError(
            f"{len(body)} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}; the payload is "
            f"{len(payload)} bytes and at most {body_capacity(len(tail))['payload']} fit")
    return body


# Every byte non-zero: ClearRamScript zero-fills the body [decomp:src/script.c:495], so a short
# delivery sums strictly lower than the stub's pool word.
FILLER_SEED = 0x5EED1E55


def filler_bytes(count, seed=FILLER_SEED):
    """-> `count` reproducible non-zero bytes; not constant, so a reordering changes the sum."""
    out = bytearray()
    state = int(seed) & 0xFFFFFFFF
    while len(out) < int(count):
        state = (state * 0x41C64E6D + 0x00006073) & 0xFFFFFFFF
        out.append(((state >> 16) & 0xFE) + 1)      # 1..255, never 0
    return bytes(out)


# 95% when the floors are tested twice: a miss costs one A press, and 99% would freeze the overworld
# for 18 s on an unlucky run.
BOTH_CONFIDENCE = 0.95


def build_mon_hunt_far_script(species, level, *, criteria=None, item=0, cap=None,
                              max_freeze_frames=MAX_FREEZE_FRAMES, scratch=SCRATCH,
                              rng_address=None, sav2_pointer=None, sb1_pointer=None,
                              payload_bytes=None, seed=FILLER_SEED,
                              stub_name="mon-seek-far", placements=1,
                              confidence=SEARCH_CONFIDENCE, build=None):
    """build_mon_hunt_script with the code run out of the body behind a filler it sums before
    searching: shiny as asked = body arrived and ran; ordinary mon = guard bailed or tail short; a
    freeze must not happen. `payload_bytes` (default: all that fits) bisects a partial delivery."""
    criteria = MonCriteria() if criteria is None else criteria
    if not isinstance(criteria, MonCriteria):
        raise NativeScriptError("criteria must be a MonCriteria")
    chosen_cap = (cap_for(criteria, confidence, placements) if cap is None else int(cap))
    cost = search_cost(criteria, chosen_cap, placements)
    if cost["worst_frames"] > max_freeze_frames:
        raise NativeScriptError(
            f"{criteria.describe()} is 1 state in {1 / cost['probability']:,.0f}: searching for "
            f"it can block the overworld for {cost['worst_frames']:,.0f} frames "
            f"({cost['worst_seconds']:.1f} s), past the {max_freeze_frames} frame ceiling. Ask "
            f"for less, or raise max_freeze_frames deliberately.")
    if not 1 <= chosen_cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {chosen_cap}")

    try:
        tail = battle_and_exit(species, level, item)
    except RngScriptError as error:
        raise NativeScriptError(str(error)) from None
    room = body_capacity(len(tail))["payload"]
    total = room if payload_bytes is None else int(payload_bytes)
    bare = len(STUBS[stub_name][0])
    if not bare <= total <= room:
        raise NativeScriptError(
            f"the payload is {bare}..{room} bytes here; asked for {total}")
    filler = filler_bytes(total - bare, seed)
    build = builds.resolve(build)
    sb1 = build.sb1ptr if sb1_pointer is None else int(sb1_pointer)
    # mon-seek-log carries gSaveBlock1Ptr for its log too.
    own_sb1 = {"sb1ptr": sb1} if "p_sb1ptr" in STUBS[stub_name][2] else {}
    code = stub(stub_name,
                rng=build.rng if rng_address is None else int(rng_address),
                sav2ptr=build.sb2ptr if sav2_pointer is None else int(sav2_pointer),
                cap=chosen_cap, nature=criteria.nature_mask, ivmin=criteria.iv_word,
                padlen=len(filler), padsum=sum(filler) & 0xFFFFFFFF, **own_sb1)
    return build_body_script(code + filler, tail, scratch=scratch, sb1_pointer=sb1,
                             build=build)


# The whole script offline: setptr staging, callnative, the trampoline reading gSaveBlock1Ptr and
# branching back into the body, each of which can be wrong on its own.

def emulate_body_script(script, *, sb1_base=0x02025734, rng_state=0, trainer_id=0, secret_id=0,
                        sav2_base=0x02024588, instruction_limit=1 << 26,
                        magic=RAM_SCRIPT_MAGIC, build=None):
    """Execute `script` as the field engine would, its bytes at sb1_base + RAMSCRIPT_BODY_OFFSET
    behind the magic byte. Only setptr and callnative are interpreted; `goto` ends the walk.
    `sb1_base` defaults to the address seen on the console."""
    script = bytes(script)
    if len(script) > MAX_RAM_SCRIPT_SIZE:
        raise NativeScriptError(f"{len(script)} bytes is past the {MAX_RAM_SCRIPT_SIZE}-byte body")
    save2 = bytearray(0x10)
    save2[0x0A:0x0C] = int(trainer_id).to_bytes(2, "little")
    save2[0x0C:0x0E] = int(secret_id).to_bytes(2, "little")
    # As InitRamScript leaves it [decomp:src/script.c:495].
    ram_script = (bytes([int(magic) & 0xFF, 0xFF, 0xFF, 0xFF])
                  + script.ljust(MAX_RAM_SCRIPT_SIZE, b"\0"))
    staged, called, executed = {}, [], []
    i = 0
    while i < len(script):
        op = script[i]
        if op == SCR_SETPTR:
            staged[int.from_bytes(script[i + 2:i + 6], "little")] = script[i + 1]
            i += SETPTR_SIZE
        elif op == SCR_CALLNATIVE:
            called.append(int.from_bytes(script[i + 1:i + 5], "little"))
            i += CALLNATIVE_SIZE
        elif op == SCR_SETWILDBATTLE:
            i += 6
        elif op == SCR_SETVAR:
            i += 5
        elif op == SCR_GOTO:
            break
        elif op == SCR_END:
            break
        else:
            raise NativeScriptError(f"unhandled opcode 0x{op:02X} at {i} of the body")
    if len(called) != 1:
        raise NativeScriptError(f"expected exactly one callnative, found {len(called)}")
    low, high = min(staged), max(staged)
    if sorted(staged) != list(range(low, high + 1)):
        raise NativeScriptError("the staged bytes are not contiguous")
    blob = bytes(staged[a] for a in range(low, high + 1))
    entry = called[0]
    if entry & ~1 != low:
        raise NativeScriptError(
            f"callnative goes to 0x{entry & ~1:08X}, the staged bytes start at 0x{low:08X}")
    build = builds.resolve(build)
    regions = {
        build.rng: int(rng_state).to_bytes(4, "little"),
        build.sb1ptr: int(sb1_base).to_bytes(4, "little"),
        build.sb2ptr: int(sav2_base).to_bytes(4, "little"),
        int(sav2_base): bytes(save2),
        int(sb1_base) + RAMSCRIPT_MAGIC_OFFSET: ram_script,
        int(sb1_base) + HUNT_LOG_OFFSET: bytes(HUNT_LOG_SIZE),
    }
    result = emulate(blob, base=low, memory=regions, instruction_limit=instruction_limit)
    executed.append(entry)
    return {"rng": int.from_bytes(result["memory"][build.rng], "little"),
            "instructions": result["instructions"],
            "staged_bytes": len(blob), "staged_at": low, "entry": entry,
            "payload_at": int(sb1_base) + RAMSCRIPT_BODY_OFFSET,
            "log": decode_hunt_log(result["memory"][int(sb1_base) + HUNT_LOG_OFFSET]),
            "body": ram_script}


def build_mon_hunt_both_script(species, level, **kwargs):
    """build_mon_hunt_far_script with asm/field/mon-seek-both.s: the floors tested at both draw
    placements the stray draw produces (the .s header has the derivation)."""
    kwargs.setdefault("stub_name", "mon-seek-both")
    kwargs.setdefault("placements", 2)
    kwargs.setdefault("confidence", BOTH_CONFIDENCE)
    return build_mon_hunt_far_script(species, level, **kwargs)


def decode_hunt_log(blob):
    """-> what a hunt wrote into SaveBlock1.unused_348C, or None; the magic separates an exhausted
    search (`found` 0) from a stub that never ran."""
    blob = bytes(blob)
    if len(blob) < HUNT_LOG_SIZE:
        raise NativeScriptError(f"a hunt log is {HUNT_LOG_SIZE} bytes, got {len(blob)}")
    words = [int.from_bytes(blob[i * 4:i * 4 + 4], "little") for i in range(len(HUNT_LOG_FIELDS))]
    record = dict(zip(HUNT_LOG_FIELDS, words))
    if record["magic"] != HUNT_LOG_MAGIC:
        return None
    record["found_one"] = record["found"] != 0
    record["exhausted"] = not record["found_one"]
    record["instructions"] = record["iterations"] * INSTRUCTIONS_PER_ITERATION
    record["frames"] = frames_for(record["instructions"])
    record["seconds"] = record["frames"] / 59.7275
    return record


def build_mon_hunt_log_script(species, level, **kwargs):
    """build_mon_hunt_both_script with asm/field/mon-seek-log.s, which writes {marker, start, found,
    iterations, cap} to SaveBlock1 + HUNT_LOG_OFFSET."""
    kwargs.setdefault("stub_name", "mon-seek-log")
    kwargs.setdefault("placements", 2)
    kwargs.setdefault("confidence", BOTH_CONFIDENCE)
    return build_mon_hunt_far_script(species, level, **kwargs)
