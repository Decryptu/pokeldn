"""A RAM script that stages a THUMB stub into gDecompressionBuffer and `callnative`s it, which is
how native code reaches the OVERWORLD - where an encounter is decided and the Mystery Gift link
cannot go. docs/frlg_rng.md has the technique, the draw model and the runs; asm/field/ has the stubs.

Two invariants this module enforces, both of which cost a frozen overworld if broken: the entry
address carries bit 0 (Thumb, `callnative` calls through a function pointer), and every stub is
bounded and run under unicorn offline before it can be staged. `budget()` states the size limit
from the numbers rather than from a comment.
"""

import math
from dataclasses import dataclass, field

from pokeldn.frlg.rom import rom_map
from pokeldn.frlg.rom.field_stubs import STUBS
from pokeldn.frlg.rom.resident_stubs import STUBS as RESIDENT_STUBS
from pokeldn.frlg.rom.rng_countdown import NATURE_NAMES, NUM_NATURES
# One encoder for `setptr`, not two: duplicated encoders go out of step and cost a run.
from pokeldn.frlg.rom.rng_script import (MAX_RAM_SCRIPT_SIZE, SCR_END, SCR_SETPTR, RngScriptError,  # noqa: F401
                         SCR_DOWILDBATTLE, SCR_SETWILDBATTLE, SCR_RELEASEALL, SCR_GOTO,
                         SCR_SETVAR, BATTLE_TAIL, TRAMPOLINE_ADDRESS, TRAMPOLINE_WORD,
                         MAX_LEVEL, MAX_SPECIES, SCR_PLAYSE, SCR_WAITSE, SE_SUCCESS,
                         battle_and_exit, setptr)

SCR_CALLNATIVE = 0x23

SETPTR_SIZE = 6                     # opcode + immediate + 4-byte address
CALLNATIVE_SIZE = 5                 # opcode + 4-byte address

# gDecompressionBuffer. See the module docstring for why this address and not another.
SCRATCH = rom_map.GDECOMPRESSION_BUFFER
SCRATCH_SIZE = 0x4000               # [decomp:src/decompress.c, gDecompressionBuffer[0x4000]]

SHINY_ODDS = 8                      # [decomp:include/constants/pokemon.h]


class NativeScriptError(RngScriptError):
    """A field script that would not do what it says, refused before it can reach a console."""


def stage(blob, address=SCRATCH):
    """-> the `setptr` run that writes `blob` to `address`, one byte per command.

    Six bytes of script per byte of payload. There is no block-copy command in the field engine -
    `copybyte` (0x15) moves ONE byte and needs an absolute source, which is no cheaper and would
    need the bytes to already be somewhere the script can name.
    """
    blob, address = bytes(blob), int(address)
    if not blob:
        raise NativeScriptError("nothing to stage")
    if not 0 <= address <= 0xFFFFFFFF - len(blob):
        raise NativeScriptError(f"0x{address:X} is not a 32-bit address for {len(blob)} bytes")
    return b"".join(setptr(byte, address + i) for i, byte in enumerate(blob))


def callnative_at(address, *, thumb=True):
    """-> one `callnative`. `thumb` sets bit 0, which is what puts the CPU in Thumb state."""
    address = int(address)
    if address % 2:
        raise NativeScriptError(f"0x{address:X} is odd; pass the address, the bit is set here")
    if not 0 <= address <= 0xFFFFFFFF:
        raise NativeScriptError(f"0x{address:X} is not a 32-bit address")
    return bytes([SCR_CALLNATIVE]) + (address | (1 if thumb else 0)).to_bytes(4, "little")


def budget(code_size, other=0):
    """-> {} : what staging `code_size` bytes costs against the 995 a RAM script has."""
    staged = int(code_size) * SETPTR_SIZE
    total = staged + CALLNATIVE_SIZE + int(other)
    return {"code_size": int(code_size), "staged_bytes": staged, "other_bytes": int(other),
            "total": total, "limit": MAX_RAM_SCRIPT_SIZE, "spare": MAX_RAM_SCRIPT_SIZE - total,
            "max_code_size": (MAX_RAM_SCRIPT_SIZE - CALLNATIVE_SIZE - int(other)) // SETPTR_SIZE,
            "fits": total <= MAX_RAM_SCRIPT_SIZE}


def stub(name, **params):
    """-> the stub's THUMB bytes with its literal pool patched.

    The offsets come from the assembler (scripts/gen_field_stubs.py reads the symbol table), so a
    parameter that is renamed or moved in the .s is a KeyError here and not a silently wrong word.
    """
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
                            rng_address=None, sav2_pointer=None):
    """The RAM script that makes the NEXT scripted encounter shiny, from any state, no aiming.

    Stage `shiny-seek`, call it, then `setwildbattle` + `dowildbattle`. Every command before
    dowildbattle returns FALSE [decomp:src/scrcmd.c], so the field engine runs the whole thing in
    ONE frame with nothing in between: the state the stub leaves in gRngValue is the state
    CreateScriptedWildMon consumes two commands later, and shininess is decided by the two draws
    the stub just tested. There is no press to time and no target to go stale.

    NO TRAINER ID IS PASSED, and that is deliberate. The stub dereferences gSaveBlock2Ptr and reads
    playerTrainerId itself, so the same bytes are correct on FireRed and on LeafGreen and nothing
    here has to know, or be kept in step with, whose console it is [asm/field/shiny-seek.s].
    """
    cap = int(cap)
    if not 1 <= cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {cap}")
    code = stub("shiny-seek",
                rng=rom_map.GRNG_VALUE if rng_address is None else int(rng_address),
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
                cap=cap)
    return _stage_and_battle(code, species, level, item=item, scratch=scratch)


# --- the resident hook ------------------------------------------------------------------------
# The staging area at the top of EWRAM: above every symbol the game links, and clear in every state
# that is not a reset [docs/frlg_rom.md, Where a payload can live].
RESIDENT_BASE = 0x0203FC00
RESIDENT_COUNTER = 0x0203FC40
GINTRTABLE_VBLANK = 0x03002730      # gIntrTable[4] [docs/frlg_rom.md, The per-frame hook]


def resident_words(name="vblank-hook", **params):
    """-> the resident stub as whole words, with its named parameters patched.

    An installer writes words, so a stub whose length is not a multiple of four is a bug in the
    stub rather than something to pad over here.
    """
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


# --- a payload that lives in the save ---------------------------------------------------------
# What a RAM script keeps is a script, and the script rebuilds its code every time, so the code can
# never be larger than a body carries. A payload parked in SaveBlock2's filler_B20 is bounded by save
# space instead. Nothing touches that region: not the save-write that puts it there, not ordinary
# play, not a later Wonder Card [docs/frlg_rom.md, Reading the save].
SAVE_PAYLOAD_MAGIC = 0x444C4B50         # "PKLD" little-endian, the loader's guard
SAVE_PAYLOAD_OFFSET = 0xB20             # filler_B20 inside SaveBlock2 [decomp:include/global.h:357]
SAVE_PAYLOAD_SIZE = 0x400               # the whole of filler_B20; more than one save-write carries,
                                        # so the blob is written in two sessions and the loader is
                                        # the same 64 bytes either way
SAVE_PAYLOAD_COUNTER = 0x0203FBB0       # BELOW the blob: a full-size payload ends at the top of
                                        # EWRAM, and 0x0203FBAC..0x0203FC00 is above every symbol
# Where the V-blank hook sits inside the blob. Deliberately well clear of the head rather than just
# past it: the hook's address is what gIntrTable[4] reads, so every time the head grew the expected
# value moved and had to be re-agreed with whoever was watching the console. Fixed once, with room.
HOOK_OFFSET = 0x140
PROBE_OUT_OFFSET = 0x300                # the probe answer: seven header words then four per number
PROBE_RESULTS_OFFSET = PROBE_OUT_OFFSET + 28
# The thunk and the hook's lr scratch sit ABOVE the results rather than in the middle of them: four
# words per number grows the result region, and at three words per number it already reached the
# thunk. The builder refuses an overlap rather than letting a sweep overwrite the code it calls.
LRSAVE_OFFSET = 0x3BC                   # one word the hook parks lr in while it calls the thunk
# One word in the tail that says which experiment the blob is. Everything else between the results
# and the checksum is self-describing filler and a thunk that rarely changes, so two payloads with
# different probes differed in the tail by the checksum alone: four bytes, and the same four bytes a
# reader is checking the delivery with. A tail-only diff could not then tell a delivered tail from a
# skipped one. This is a second, independent witness, and it is not arithmetic over the blob.
TAIL_MARK_OFFSET = 0x3F0                # clear of the results, the lr scratch and the thunk
# What the probe passes in r0..r3 when the caller does not say. Distinct and non-zero, so a register
# the syscall leaves alone reads differently from one it writes zero into.
PROBE_MARKERS = (0xA5A00052, 0xA5B00001, 0xA5C00002, 0xA5D00003)
PROBE_THUNK_OFFSET = 0x3C0              # `swi N ; bx lr`, assembled into the blob by the builder
# The hook's tail target as it sits in the save. The installer overwrites it with whatever it reads
# out of the table, which is the point, but the copy happens first and the blob may land on top of a
# hook that is already installed and being called. A zero there is a branch to 0 on the next V-blank,
# between the copy and the install, and on the second visit to the object the installer takes its
# already-installed path and never patches it at all. So the save's copy carries the measured handler
# rather than zero, and a second visit re-writes a hook that already works.
VBLANK_HANDLER = 0x0800071D             # VBlankIntr [docs/frlg_rom.md, The per-frame hook]


def build_save_payload(*, base=RESIDENT_BASE, size=SAVE_PAYLOAD_SIZE,
                       counter=SAVE_PAYLOAD_COUNTER, table_entry=GINTRTABLE_VBLANK,
                       magic=SAVE_PAYLOAD_MAGIC, filler_byte=None, original=VBLANK_HANDLER,
                       probe=0, probe_args=(), probe_count=1, burst=0, probe_a0_step=0,
                       probe_num_step=1, probe_store=True):
    """-> the blob to park in the save: magic, installer, the V-blank hook, filler, checksum.

    The checksum is the point of the filler. A branch that lands proves the jump and says nothing
    about the size, and the blob travels through a save write, flash, a slot rotation and a copy loop
    before anything runs it. The installer sums the filler and installs nothing unless the sum
    matches, so a short or truncated arrival is a miss rather than a wrong answer.
    """
    head, _digest, symbols = RESIDENT_STUBS["save-payload"]
    hook_params = {"counter": counter, "original": original, "burst": int(burst or 0),
                   "thunk": (base + PROBE_THUNK_OFFSET) | 1, "lrsave": base + LRSAVE_OFFSET}
    hook = b"".join(w.to_bytes(4, "little")
                    for w in resident_words("vblank-hook", **hook_params))
    # Where the hook keeps its tail target, taken from its own symbol table rather than counted in
    # from the start of it: the hook has grown twice and a hardcoded offset would have gone stale
    # silently, with the freeze only appearing on a second visit.
    hook_original_at = base + HOOK_OFFSET + RESIDENT_STUBS["vblank-hook"][2]["p_original"]
    if len(head) > HOOK_OFFSET:
        raise NativeScriptError(
            f"the payload head is {len(head)} bytes and the hook sits at {HOOK_OFFSET:#x}")
    filler_start = HOOK_OFFSET + len(hook)      # where the byte pattern begins
    # What the installer sums is the WHOLE blob, not the filler. Two payloads differing only above
    # the filler carried the same checksum, which was not a collision but the design: the sum could
    # never see the head. A control head with a probe tail passed it on a live console, and would
    # have installed, verified and run with the probe disabled, all green.
    sum_from = 0
    checksum_at = size - 4
    if checksum_at <= filler_start:
        raise NativeScriptError(f"{size} bytes leaves no room for filler")
    blob = bytearray(size)
    blob[0:len(head)] = head
    blob[HOOK_OFFSET:HOOK_OFFSET + len(hook)] = hook
    # Non-zero filler, so a short arrival sums differently rather than summing to the same zero.
    for i in range(filler_start, checksum_at):
        blob[i] = (i & 0xFF) if filler_byte is None else (filler_byte & 0xFF)
    # The probe's thunk is code, and it lives inside the filler so the checksum covers it. It is
    # written before the sum is taken, so a blob with a probe and one without are both consistent.
    if probe:
        if not 0 <= int(probe) <= 0xFF:
            raise NativeScriptError(f"a Thumb `swi` takes 0..255, got {probe}")
        # The last number the sweep reaches, not `first + count`: with probe_num_step 0 the sweep
        # calls one syscall count times and walks r0 instead, which is the only way to ask what a
        # selector does. A step of 1 and a step of 0 are different experiments and the old check
        # could not tell them apart because it assumed the first.
        if int(probe_count) < 1:
            raise NativeScriptError(f"a sweep runs at least once, got {probe_count}")
        last = int(probe) + (int(probe_count) - 1) * int(probe_num_step)
        if not 0 <= last <= 0xFF:
            raise NativeScriptError(
                f"a sweep of {probe_count} from {probe:#x} stepping {probe_num_step} ends at "
                f"{last:#x}, outside the 0..255 a Thumb `swi` takes")
        # Only a run that STORES its results is bounded by the result region. One read through a
        # breakpoint on the wrapper's side needs the guest to issue the calls and nothing else, and
        # then the whole 256-entry selector range fits in one deployment.
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
    # A register that went in as zero and came out as zero has measured nothing: "the syscall left it
    # alone" and "the syscall wrote zero" are the same reading. The markers are the default rather
    # than a caller's responsibility, because a caller who passes r0 and stops gets three dead
    # registers and a table of zeros that looks like a broken store. That happened once and the run
    # was spent before the argument list was looked at.
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
    # The experiment, written where a reader of the tail can see it, AFTER the patches because it
    # sums the head and the patches are what the head says. Everything else between the results and
    # the checksum is self-describing filler and a thunk that rarely changes, so two payloads
    # differing only in their probe differed in the tail by the checksum word alone: the same four
    # bytes a reader checks the delivery with, doing two jobs and neither independently.
    #
    # The mark NAMES ITS HEAD. Carrying only the syscall number and the pass count, it would be
    # identical between two builds whose probes match and whose arguments differ, so one build's head
    # and the other's tail would still read as a pair. With the head summed into it a chimera names
    # itself: the reader sums the head in flash and the tail says which head it was built against.
    # The checksum cannot do that, since a mismatch there says something is wrong and never which
    # half is wrong.
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
        # FOLDED, not truncated. Taking the sum's low half leaves a witness blind to any change
        # confined to a word's upper bits, which is not a chance collision but a shape: two builds
        # differing only in the high halfword of one patched word carry the same mark. A step going
        # from 0x00200000 to 0x01000000 is exactly that, and it happened. Folding the high half in
        # makes every bit of the head sum reach the mark.
        head_sum = sum(int.from_bytes(blob[i:i + 4], "little")
                       for i in range(0, head_end - head_end % 4, 4)) & 0xFFFFFFFF
        folded = (head_sum ^ (head_sum >> 16)) & 0xFFFF
        mark = (folded << 16) | ((int(probe) & 0xFF) << 8) | min(int(probe_count), 0xFF)
        blob[TAIL_MARK_OFFSET:TAIL_MARK_OFFSET + 4] = mark.to_bytes(4, "little")
    # LAST, because it now covers the head and the head is what the patches write. Computing it
    # before them was invisible while the sum began after the hook and is a stored value that does
    # not describe the blob the moment it does not.
    total = sum(int.from_bytes(blob[i:i + 4], "little")
                for i in range(sum_from, checksum_at, 4)) & 0xFFFFFFFF
    blob[checksum_at:checksum_at + 4] = total.to_bytes(4, "little")
    return bytes(blob)


def save_write_chunks(blob, *, offset=SAVE_PAYLOAD_OFFSET, limit=None):
    """-> [(offset, bytes)] : the blob split into as few `save-write` sessions as it needs.

    One session carries `MAX_SAVE_WRITE_BYTES`, the receive buffer less the payload that does the
    writing. A blob larger than that is not a different mechanism, only more sessions; the region it
    lands in persists between them.
    """
    from pokeldn.frlg.rom.buffer_script import MAX_SAVE_WRITE_BYTES
    limit = MAX_SAVE_WRITE_BYTES if limit is None else int(limit)
    blob = bytes(blob)
    return [(offset + at, blob[at:at + limit]) for at in range(0, len(blob), limit)]


def build_loader_script(*, base=RESIDENT_BASE, size=SAVE_PAYLOAD_SIZE,
                        offset=SAVE_PAYLOAD_OFFSET, magic=SAVE_PAYLOAD_MAGIC,
                        sav2_pointer=None, scratch=SCRATCH, sound=SE_SUCCESS):
    """The RAM script that copies the payload out of the save and runs it.

    About fifty bytes of staged code whatever the payload's size, where staging the payload itself
    would cost six script bytes a byte. The save block's address is read from `gSaveBlock2Ptr` every
    time rather than patched, because it is re-rolled on every battle and every load.
    """
    if size % 4:
        raise NativeScriptError(f"{size} bytes is not a whole number of words")
    code = stub("save-loader",
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
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
                              table_entry=GINTRTABLE_VBLANK, scratch=SCRATCH, sound=SE_SUCCESS):
    """The RAM script that installs the resident V-blank hook, and survives a reset to do it again.

    A buffer script can install the hook directly and the console then runs it every frame until
    something clears EWRAM. Every route to the Mystery Gift menu passes through a boot, and
    `AgbMain` clears EWRAM and IWRAM there [decomp:src/main.c:134], so a gift session can never be
    delivered while a payload is live: a new install always destroys the old one first. This is the
    other way in. The script lives in the save, survives a power cycle, and needs no link, so the
    player talking to the bound object re-arms the hook on any later boot.

    The stub's own tail target is not passed in. `install-vblank-hook` reads the table entry and
    writes what it found into the stub, so the hook chains whatever handler is actually there.
    """
    # The hook travels with the installer as data, so its size is a number rather than a shape the
    # installer has to know. `original` is left at the measured handler for the same reason the
    # save-carried copy does: the installer patches it, but a second visit re-copies this one.
    words = resident_words("vblank-hook", counter=counter, original=VBLANK_HANDLER)
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
    """-> the staged stub, the call, and the encounter. ONE of these, for every hunt stub.

    The tail is why the builders share a path: a
    battle MOVES the save block the RAM script lives in, so the engine comes back from the battle
    to an address the script no longer occupies. `battle_and_exit` starts the battle from
    gSpecialVar_0x8000 instead, which does not move [rng_script, and the block above it].
    """
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


# --- asking for more than a shiny -----------------------------------------------------------
# shiny-seek tests the first two draws. mon-seek tests all four, which is the whole mon: the
# personality decides shininess AND the nature, and draws 3 and 4 are the six IVs
# [decomp:src/pokemon.c:1836]. Everything here is the HOST half of asm/field/mon-seek.s - the
# packed words it reads, and the cost of asking for each thing.

# The IVs in the order the ROM draws them, which is the order the packed words use. It is NOT the
# order a summary screen shows (that one puts SPEED last), and mixing the two silently asks for a
# floor on the wrong stat, so the names are spelled out once here and parsed against.
IV_FIELDS = ("hp", "attack", "defense", "speed", "sp_attack", "sp_defense")
MAX_IV = 31                             # MAX_PER_STAT_IVS [decomp:include/constants/pokemon.h]
IV_BITS = 5
IV_TERMINATOR_BIT = 30                  # asm/field/mon-seek.s: the loop counts with this bit
ANY_NATURE = (1 << NUM_NATURES) - 1

# The hot loop, counted off the disassembly and asserted against unicorn in the tests: fifteen
# THUMB instructions for a state that is not shiny, which is 8191 states in 8192.
INSTRUCTIONS_PER_ITERATION = 15

# How long a search may freeze the overworld. There is no menu to back out of and the field engine
# has not returned; the player sees a still frame with the music still playing. The ceiling is on
# the worst case, the whole cap, which by construction of `cap_for` is what 1 search in 100 costs;
# the expected search is `SEARCH_CONFIDENCE`-dependent and several times shorter, and `search_cost`
# reports both. An estimate from the GBA's clock, not a measurement; see
# CYCLES_PER_INSTRUCTION_FROM_EWRAM below.
MAX_FREEZE_FRAMES = 900                 # ~15 s at 59.7275 Hz
SEARCH_CONFIDENCE = 0.99                # the default cap is the one that finds a state this often


@dataclass(frozen=True)
class MonCriteria:
    """What mon-seek will accept. Shininess is not a field here; the hot loop always tests it.

    `natures` is a tuple of nature ids (empty means any) and `iv_minimums` six floors in DRAW
    order, IV_FIELDS. Both turn into one packed word the stub reads out of its literal pool.
    """

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
        """-> p_nature: bit N set = nature N accepted. No nature named means every one."""
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
        """-> roughly what fraction of states pass all three tests.

        An ESTIMATE, and the approximation is named: shininess and the nature are both functions
        of the same personality, so they are not independent in the strict sense, and `% 25` over
        2**32 favours 21 of the 25 residues by one part in 171 million. Neither moves a search
        budget. The IV draws are separate draws and multiply exactly.
        """
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
    """-> how long a search of this many states blocks the field engine, in frames. AN ESTIMATE."""
    return frames_for(float(iterations) * INSTRUCTIONS_PER_ITERATION)


def probability_for(criteria, placements=1):
    """-> the fraction of states that pass, when the IV floors must hold in `placements` words.

    asm/field/mon-seek-both.s tests the floors at TWO draw placements because the stray draw moves
    them (docs/frlg_rng.md's Methods 1, 2 and 4), so the IV term is raised to that power. The
    shiny and nature terms are not: both come from the personality, which is drawn before the stray
    and is the same word in every method.
    """
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
    """-> what asking for this costs: how long it is expected to take, and the worst it can take.

    The freeze is what the player sees, so both are in frames. Everything here rests on
    INSTRUCTIONS_PER_ITERATION and the GBA's clock and NOT on a hardware measurement; the first
    run that reports a visible pause is the measurement, and it goes in docs/frlg_rng.md when it comes.
    """
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
                          rng_address=None, sav2_pointer=None):
    """The RAM script that makes the next scripted encounter a mon we described, from any state.

    build_shiny_hunt_script with three tests instead of one, and the same one-frame guarantee:
    every command before `dowildbattle` returns FALSE, so the search and the generation happen in
    one pass of the field engine with nothing between them that draws.

    THE COST IS CHECKED BEFORE THE CARD IS BUILT, not after the player is looking at a frozen
    overworld. A criterion does not slow an iteration down - it multiplies how many are needed -
    so `cap` is what bounds the freeze, and a cap whose worst case exceeds `max_freeze_frames` is
    refused here. Raising that ceiling is a decision, so it is an argument and not a default.
    """
    criteria = MonCriteria() if criteria is None else criteria
    if not isinstance(criteria, MonCriteria):
        raise NativeScriptError("criteria must be a MonCriteria")
    chosen_cap = cap_for(criteria) if cap is None else int(cap)
    cost = search_cost(criteria, chosen_cap)
    # The freeze is checked BEFORE the cap's own range, because a cap past that range is always a
    # freeze past this ceiling and the ceiling is the answer that says what to do about it.
    if cost["worst_frames"] > max_freeze_frames:
        raise NativeScriptError(
            f"{criteria.describe()} is 1 state in {1 / cost['probability']:,.0f}: searching for "
            f"it can block the overworld for {cost['worst_frames']:,.0f} frames "
            f"({cost['worst_seconds']:.1f} s), past the {max_freeze_frames} frame ceiling. Ask "
            f"for less, or raise max_freeze_frames deliberately.")
    if not 1 <= chosen_cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {chosen_cap}")
    code = stub("mon-seek",
                rng=rom_map.GRNG_VALUE if rng_address is None else int(rng_address),
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
                cap=chosen_cap, nature=criteria.nature_mask, ivmin=criteria.iv_word)
    return _stage_and_battle(code, species, level, item=item, scratch=scratch)


def describe(script):
    """-> lines: what the bytes do, read back OUT of them rather than from what we meant.

    A run of `setptr` into one region is collapsed, because 72 of them say nothing one at a time.
    """
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
            # `goto` is unconditional, so nothing after it is script at all. On a body-hosted
            # card what follows is the PAYLOAD, and decoding it as commands prints nonsense.
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


# --- running a stub offline, before it can ever reach the overworld ------------------------------
# The same rule buffer payloads live under [docs/frlg_rom.md], and it matters MORE here: a
# buffer script that hangs freezes the Mystery Gift menu, which the player can at least see is
# stuck; a field stub that hangs freezes the overworld inside a script, with no menu at all.

_EWRAM, _EWRAM_SIZE = 0x02000000, 0x40000
_IWRAM, _IWRAM_SIZE = 0x03000000, 0x8000
_STACK, _STACK_SIZE = 0x03007000, 0x1000        # inside IWRAM, where the GBA's sp lives
_RETURN = 0x02FF0000                            # our own marker, mapped but never executed
_INSTRUCTION_LIMIT = 1 << 24


def emulate(code, *, base=SCRATCH, memory=None, instruction_limit=_INSTRUCTION_LIMIT):
    """Run a staged stub the way `callnative` does: no arguments, Thumb, returns to lr.

    `memory` places regions the stub reads or writes as {address: bytes}; the result's `memory` is
    those same regions read back afterwards, which is where the answer is - a field stub returns
    nothing (`callnative` ignores r0) and speaks only through what it wrote.
    """
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


# The CPU is 16.78 MHz and a frame is 280,896 cycles [the GBA's clock]. A Thumb ALU instruction is
# one cycle from IWRAM but this runs from EWRAM, which is 16-bit and WAITS: 3 cycles a halfword
# fetch on the default waitstate setting, so ~3 cycles an instruction is the honest figure. The
# search is 15 instructions an iteration and averages 8192 iterations (1 state in 8192 is shiny),
# so ~370k cycles - a little over ONE FRAME. The worst case allowed by the default cap is ~50
# frames, or most of a second. That is a visible hitch and nothing worse: interrupts stay enabled
# throughout, so VBlank, DMA and the music carry on; the field engine simply has not returned yet.
# Not measured on hardware: an estimate from the clock.
CYCLES_PER_INSTRUCTION_FROM_EWRAM = 3
CYCLES_PER_FRAME = 280896


def frames_for(instructions):
    """-> roughly how many frames a stub of this length blocks the field engine for."""
    return int(instructions) * CYCLES_PER_INSTRUCTION_FROM_EWRAM / CYCLES_PER_FRAME


# --- the payload in the script body: one byte each instead of six -------------------------------
# Everything above stages code with `setptr`, six script bytes a payload byte, which caps a field
# stub at ~163 bytes. The cap comes off here because the field engine does not copy the body:
# `GetRamScript` returns `scriptData->script` itself [decomp:src/script.c:514], a pointer into
# gSaveBlock1Ptr->ramScript.data, and never reads past the last command. Bytes appended after it are
# delivered storage at one script byte each.
#
# Aiming at them is a run-time read, not a build-time constant: the save-block offset is re-rolled at
# a battle or a load and then fixed for the frame our script runs in, and &gSaveBlock1Ptr is a
# link-time IWRAM word that says what it currently is. A 36-byte trampoline reads it.
#
# The body is 995 bytes [RamScriptData.script] and the Mystery Event script carrying it is 1024
# [mystery_event.MAX_SCRIPT_SIZE] less the VM's own 16, so 995 binds by 13 bytes. `body_capacity`
# states it. docs/frlg_rng.md.

RAMSCRIPT_IN_SAVEBLOCK1 = 0x361C        # SaveBlock1.ramScript [decomp:include/global.h]
RAMSCRIPT_MAGIC_OFFSET = RAMSCRIPT_IN_SAVEBLOCK1 + 4        # past the u32 checksum
RAMSCRIPT_BODY_OFFSET = RAMSCRIPT_MAGIC_OFFSET + 4          # past magic, mapGroup, mapNum, objectId
RAM_SCRIPT_MAGIC = 51                   # [decomp:src/script.c:12], written by InitRamScript [:505]

# Where a hunt reports what it did: SaveBlock1.unused_348C[400] [decomp:include/global.h]. It reads
# all 400 bytes off the console as zero before anything was written there. It is in the save, so it
# survives the battle and reaches flash when the player saves, and it is outside ramScript, so the
# RAM script checksum is untouched and the binding survives.
HUNT_LOG_OFFSET = 0x348C
HUNT_LOG_MAGIC = 0x474F4C31             # so an untouched region is not read as a report
HUNT_LOG_SIZE = 20
HUNT_LOG_FIELDS = ("magic", "start", "found", "iterations", "cap")

TRAMPOLINE_STUB = "ram-jump"

# The payload must start at a multiple of four, not merely an even offset. A Thumb stub reaches its
# literal pool with `ldr rN, [pc, #imm]` and its tail with `adr`, and both use Align(PC, 4). Two
# bytes off, the branch still lands and the code still runs, but every pool word is read two bytes
# past where it lives: for mon-seek-far, a filler length of 0x0433CF15 and a fault inside its own
# checksum loop. Caught by emulate_body_script below, which walks the real script bytes rather than
# running a stub at an address a harness chose.
#
# Four is also sufficient, provably, which is why nothing checks it at run time:
# `offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)` [decomp:src/load_save.c:75] is `& 0x7C`,
# and gSaveBlock1 is an EWRAM struct of u32 fields, so RAMSCRIPT_BODY_OFFSET (0x3624) keeps the base
# word-aligned.
BODY_ALIGNMENT = 4


def ram_jump_stub(payload_offset, *, sb1_pointer=None, magic_offset=RAMSCRIPT_MAGIC_OFFSET):
    """-> the trampoline, patched to branch at the payload `payload_offset` bytes into the body.

    `p_entry` is measured from the MAGIC BYTE rather than from the block base so the stub can add
    the same register twice and needs no third pool word. See asm/field/ram-jump.s.
    """
    offset = int(payload_offset)
    if offset < 0:
        raise NativeScriptError(f"the payload offset is not negative, got {offset}")
    if offset % 4:
        raise NativeScriptError(
            f"the payload must start at a MULTIPLE OF FOUR, got {offset}; see BODY_ALIGNMENT")
    entry = (RAMSCRIPT_BODY_OFFSET - int(magic_offset)) + offset
    return stub(TRAMPOLINE_STUB,
                sb1ptr=rom_map.GSAVEBLOCK1PTR if sb1_pointer is None else int(sb1_pointer),
                magic=int(magic_offset), entry=entry | 1)


def body_prefix_size(tail_size):
    """-> how many script bytes come before the payload: the staged trampoline, the call, the tail.

    The trampoline's LENGTH does not depend on what it is patched with, so this is knowable before
    the stub exists - which is what breaks the circularity of "the offset depends on the script
    that contains the offset".
    """
    size = len(STUBS[TRAMPOLINE_STUB][0]) * SETPTR_SIZE + CALLNATIVE_SIZE + int(tail_size)
    return size + (-size % BODY_ALIGNMENT)


def body_capacity(tail_size):
    """-> how many payload bytes fit after a tail of `tail_size`, and what the old way allowed."""
    prefix = body_prefix_size(tail_size)
    staged = (MAX_RAM_SCRIPT_SIZE - CALLNATIVE_SIZE - int(tail_size)) // SETPTR_SIZE
    return {"prefix": prefix, "payload": MAX_RAM_SCRIPT_SIZE - prefix,
            "staged_equivalent": staged, "limit": MAX_RAM_SCRIPT_SIZE}


def build_body_script(payload, tail=b"", *, scratch=SCRATCH, sb1_pointer=None):
    """-> the RAM script that stages the trampoline, calls it, runs `tail`, and carries `payload`.

    The layout, and the order is the argument:

        setptr x36    the trampoline, into gDecompressionBuffer      216 bytes
        callnative    -> the trampoline -> the payload -> back         5
        <tail>        whatever the script does after the payload has returned
        <pad>         one byte at most, so the payload starts even
        <payload>     never reached by the engine: `tail` ends in a `goto`

    The payload returns with `pop {r4-r7, pc}`, which lands back in ScrCmd_callnative's caller
    because the trampoline BRANCHES rather than calls, so the script continues into `tail`.
    """
    payload = bytes(payload)
    tail = bytes(tail)
    if not payload:
        raise NativeScriptError("nothing to run")
    prefix = body_prefix_size(len(tail))
    code = ram_jump_stub(prefix, sb1_pointer=sb1_pointer)
    body = (stage(code, scratch) + callnative_at(scratch) + tail
            + b"\x00" * (prefix - len(stage(code, scratch)) - CALLNATIVE_SIZE - len(tail))
            + payload)
    assert body.index(payload, prefix) == prefix
    if len(body) > MAX_RAM_SCRIPT_SIZE:
        raise NativeScriptError(
            f"{len(body)} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}; the payload is "
            f"{len(payload)} bytes and at most {body_capacity(len(tail))['payload']} fit")
    return body


# The filler that proves the far end of the body arrived. EVERY BYTE IS NON-ZERO, and that is the
# whole design: `InitRamScript` zero-fills the body before copying what it was given
# [ClearRamScript, decomp:src/script.c:495], so a short delivery reads back as zeros and the sum
# the stub computes is STRICTLY LOWER than the one in its pool. A missing tail cannot sum right.
FILLER_SEED = 0x5EED1E55


def filler_bytes(count, seed=FILLER_SEED):
    """-> `count` reproducible non-zero bytes. Not random, just not uniform: a constant fill would
    sum the same under a reordering, and a zero byte would hide a truncation."""
    out = bytearray()
    state = int(seed) & 0xFFFFFFFF
    while len(out) < int(count):
        state = (state * 0x41C64E6D + 0x00006073) & 0xFFFFFFFF
        out.append(((state >> 16) & 0xFE) + 1)      # 1..255, never 0
    return bytes(out)


# 95%, not 99%, when the floors are tested twice. The RAM script ends in `end` and not `endram`, so
# the binding survives and a miss costs the player one A press [rng_script]. A 99% cap would freeze
# the overworld for 18 s on every unlucky run.
BOTH_CONFIDENCE = 0.95


def build_mon_hunt_far_script(species, level, *, criteria=None, item=0, cap=None,
                              max_freeze_frames=MAX_FREEZE_FRAMES, scratch=SCRATCH,
                              rng_address=None, sav2_pointer=None, sb1_pointer=None,
                              payload_bytes=None, seed=FILLER_SEED,
                              stub_name="mon-seek-far", placements=1,
                              confidence=SEARCH_CONFIDENCE):
    """build_mon_hunt_script, with the code RUN OUT OF THE BODY and the body FILLED to prove it.

    One variable changes against the control card: where the search code lives. Same criteria, same
    species, same cap, same battle tail. What is new is the filler behind the stub and the sum the
    stub takes over it before it will search at all - so the run distinguishes three things the
    screen could not otherwise tell apart:

        a shiny mon of the nature and IVs asked for   the whole body arrived and ran from the body
        an ordinary mon                               the guard bailed, or the tail is short
        a frozen overworld                            neither of the above; it must not happen

    `payload_bytes` is how much of the body the payload occupies, filler included; it defaults to
    every byte that fits. Passing a smaller number is the way to bisect a partial delivery without
    changing anything else.
    """
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
    code = stub(stub_name,
                rng=rom_map.GRNG_VALUE if rng_address is None else int(rng_address),
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
                cap=chosen_cap, nature=criteria.nature_mask, ivmin=criteria.iv_word,
                padlen=len(filler), padsum=sum(filler) & 0xFFFFFFFF)
    return build_body_script(code + filler, tail, scratch=scratch, sb1_pointer=sb1_pointer)


# --- running the WHOLE script offline, not just the stub ----------------------------------------
# The offline harness can pass throughout: "it builds its
# distribution DIRECTLY - the one path the hardware uses was the one never exercised offline."
# `emulate` above runs a stub at an address someone hands it. That is not the path any more. The
# path is: the engine walks the body, `setptr` writes the trampoline a byte at a time, `callnative`
# enters it, the trampoline reads gSaveBlock1Ptr and branches BACK INTO THE BODY at an offset the
# host computed. Every one of those can be wrong on its own, so all of them run here.

def emulate_body_script(script, *, sb1_base=0x02025734, rng_state=0, trainer_id=0, secret_id=0,
                        sav2_base=0x02024588, instruction_limit=1 << 26,
                        magic=RAM_SCRIPT_MAGIC):
    """Execute `script` the way the field engine would, and return what it left behind.

    Only the four commands these scripts use are interpreted - `setptr`, `callnative`, and enough
    of the battle tail to stop at it. `goto` ENDS the walk: it leaves the body for the trampoline
    at gSpecialVar_0x8000, which is where the battle happens and where nothing offline can follow.

    `sb1_base` stands in for whatever SetSaveBlocksPointers rolled this time; the default is the
    address the console was actually seen at. The script's own bytes are placed at
    sb1_base + RAMSCRIPT_BODY_OFFSET, which is where `GetRamScript` hands them to the engine, and
    the magic byte in front of them is set to RAM_SCRIPT_MAGIC exactly as InitRamScript sets it.
    """
    script = bytes(script)
    if len(script) > MAX_RAM_SCRIPT_SIZE:
        raise NativeScriptError(f"{len(script)} bytes is past the {MAX_RAM_SCRIPT_SIZE}-byte body")
    save2 = bytearray(0x10)
    save2[0x0A:0x0C] = int(trainer_id).to_bytes(2, "little")
    save2[0x0C:0x0E] = int(secret_id).to_bytes(2, "little")
    # The RamScript as InitRamScript leaves it: magic, the three binding bytes, then the body
    # zero-filled to 995 [ClearRamScript then memcpy, decomp:src/script.c:495].
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
    # The staged bytes have to be contiguous or `callnative`'s entry means nothing.
    low, high = min(staged), max(staged)
    if sorted(staged) != list(range(low, high + 1)):
        raise NativeScriptError("the staged bytes are not contiguous")
    blob = bytes(staged[a] for a in range(low, high + 1))
    entry = called[0]
    if entry & ~1 != low:
        raise NativeScriptError(
            f"callnative goes to 0x{entry & ~1:08X}, the staged bytes start at 0x{low:08X}")
    regions = {
        rom_map.GRNG_VALUE: int(rng_state).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK1PTR: int(sb1_base).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: int(sav2_base).to_bytes(4, "little"),
        int(sav2_base): bytes(save2),
        int(sb1_base) + RAMSCRIPT_MAGIC_OFFSET: ram_script,
        int(sb1_base) + HUNT_LOG_OFFSET: bytes(HUNT_LOG_SIZE),
    }
    result = emulate(blob, base=low, memory=regions, instruction_limit=instruction_limit)
    executed.append(entry)
    return {"rng": int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little"),
            "instructions": result["instructions"],
            "staged_bytes": len(blob), "staged_at": low, "entry": entry,
            "payload_at": int(sb1_base) + RAMSCRIPT_BODY_OFFSET,
            "log": decode_hunt_log(result["memory"][int(sb1_base) + HUNT_LOG_OFFSET]),
            "body": ram_script}


def build_mon_hunt_both_script(species, level, **kwargs):
    """build_mon_hunt_far_script with asm/field/mon-seek-both.s: the floors tested at BOTH draw
    placements, so the stray draw cannot move the IVs out from under the answer.

    The .s header has the derivation: two words cover all three
    methods docs/frlg_rng.md records, because word A puts the first IV triple on d3 and the second on
    d4, and word B puts them on d4 and d5.
    """
    kwargs.setdefault("stub_name", "mon-seek-both")
    kwargs.setdefault("placements", 2)
    kwargs.setdefault("confidence", BOTH_CONFIDENCE)
    return build_mon_hunt_far_script(species, level, **kwargs)


def decode_hunt_log(blob):
    """-> what a hunt wrote into SaveBlock1.unused_348C, or None if nothing did.

    `magic` is checked rather than assumed: the region is zero on an untouched save, and a
    run whose search was exhausted writes a `found` of 0 on purpose - so without the marker a miss
    and a stub that never ran would decode identically, which is exactly the pair this is for.
    """
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
    """build_mon_hunt_both_script with asm/field/mon-seek-log.s: the same search, reporting.

    The stub writes {marker, start, found, iterations, cap} to SaveBlock1 + HUNT_LOG_OFFSET, which
    a `save-dump` of sav1 at that offset reads back. That is what turns a hunt from something
    reconstructed out of the caught mon into something measured while it happens.
    """
    kwargs.setdefault("stub_name", "mon-seek-log")
    kwargs.setdefault("placements", 2)
    kwargs.setdefault("confidence", BOTH_CONFIDENCE)
    return build_mon_hunt_far_script(species, level, **kwargs)
