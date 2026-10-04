"""CLI_RUN_BUFFER_SCRIPT: native ARM code the console executes out of gDecompressionBuffer.

Client_Run copies the 1024-byte receive buffer there and calls it every frame until it returns 1,
with r0 = &client->param, r1 = gSaveBlock2Ptr, r2 = gSaveBlock1Ptr [mystery_gift_client.c:237,276];
*param comes back through CLI_LOAD_TOSS_RESPONSE. ARM state. `emulate` proves a payload under
unicorn before it is sent. docs/frlg_rom.md.
"""

import dataclasses
from dataclasses import dataclass

from pokeldn.frlg.rom import builds
from pokeldn.frlg.rom.buffer_payloads import PAYLOADS

# MG_LINK_BUFFER_SIZE [decomp:include/mystery_gift_link.h:4]: the whole buffer is copied but only
# what we send is fresh, so a payload must be self-contained.
MAX_BUFFER_SCRIPT_SIZE = 0x400

# Measured by `anchors`; payloads are position independent.
GDECOMPRESSION_BUFFER = 0x0201C000

# Anything else means "call me again next frame" [decomp:src/mystery_gift_client.c:279].
BUFFER_SCRIPT_DONE = 1

# struct SaveBlock2 [decomp:include/global.h:327].
SAV2_PLAYER_NAME = 0x00
SAV2_PLAYER_GENDER = 0x08
SAV2_PLAYER_TRAINER_ID = 0x0A

TRAINER_ID_PROBE = "trainer-id-probe"

# The payload's trainer id must match the one in MysteryGiftLinkGameData, read by another route.
EXPECT_TRAINER_ID = "trainer-id"


class BufferScriptError(ValueError):
    """A payload the console could not safely be asked to run. A ValueError so the CLI reports a
    refusal rather than a traceback."""


def payload(name):
    """The committed machine code for asm/<name>.s."""
    try:
        code = PAYLOADS[name][0]
    except KeyError:
        raise BufferScriptError(
            f"unknown buffer script {name!r}; have {sorted(PAYLOADS)}") from None
    validate(code)
    return code


def validate(code):
    """Everything checkable about a payload without running it."""
    if not isinstance(code, (bytes, bytearray)):
        raise BufferScriptError("a buffer script is raw ARM machine code")
    if not code:
        raise BufferScriptError("a buffer script is empty")
    if len(code) > MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a buffer script is at most {MAX_BUFFER_SCRIPT_SIZE} bytes, got {len(code)}")
    if len(code) % 4:
        # The console enters in ARM state.
        raise BufferScriptError(
            f"ARM code is a multiple of 4 bytes, got {len(code)}")
    return code


@dataclass(frozen=True)
class BufferScriptSpec:
    name: str
    description: str
    expect: object          # EXPECT_TRAINER_ID, a demanded u32, or None


MEMORY_DUMP = "memory-dump"
MEMORY_DUMP_MULTI = "memory-dump-multi"
MEMORY_DUMP_SCATTER = "memory-dump-scatter"
SAVE_DUMP = "save-dump"
ANCHORS = "anchors"
SAVE_WRITE = "save-write"
FLASH_WRITE = "flash-write"
FLASH_PATCH = "flash-patch"
FLASH_READ = "flash-read"
SLOOP_SVC = "sloop-svc"
INSTALL_RESIDENT = "install-resident"
INSTALL_KEPT = "install-kept"

# Save flash: 32 sectors of 0x1000 [decomp:include/save.h]. Only swi 0x48 and swi 0x56 write it
# [docs/frlg_rom.md, the Sloop syscall boundary].
FLASH_BASE, FLASH_SIZE = 0x0E000000, 0x00020000
FLASH_SECTOR_SIZE = 0x1000
# 0x48 writes a sector; 0x56 writes and then voids the destination's signature at +0xFF8.
SWI_WRITE_SECTOR = 0x48
SWI_REPLACE_SECTOR = 0x56
SECTOR_SIGNATURE_OFFSET_IN_SECTOR = 0xFF8


# save-write's operands, from its literal pool; tests emulate a patched payload.
SAVE_WRITE_WHICH_OFFSET = 0x4C
SAVE_WRITE_OFFSET_OFFSET = 0x50
SAVE_WRITE_SIZE_OFFSET = 0x54
SAVE_WRITE_DATA_OFFSET = 0x58
MAX_SAVE_WRITE_BYTES = MAX_BUFFER_SCRIPT_SIZE - SAVE_WRITE_DATA_OFFSET


# The eleven words `anchors` sends back, in order.
ANCHORS_FIELDS = (
    "code",             # gDecompressionBuffer, measured
    "return_address",   # after the call in Client_RunBufferScript; THUMB
    "stack_pointer",
    "client_param",     # r0
    "save_block_2",     # r1
    "save_block_1",     # r2
    "client_send_buffer",
    "client_recv_buffer",
    "client_script",
    "client_msg",
    "link_send_buffer",  # must equal client_send_buffer
)
ANCHORS_SIZE = 4 * len(ANCHORS_FIELDS)


def read_anchors(dump):
    """-> {field: u32} for the bytes `anchors` sent back."""
    dump = bytes(dump)
    if len(dump) < ANCHORS_SIZE:
        raise BufferScriptError(
            f"the anchors payload sends {ANCHORS_SIZE} bytes, got {len(dump)}")
    return {name: int.from_bytes(dump[4 * i:4 * i + 4], "little")
            for i, name in enumerate(ANCHORS_FIELDS)}


def describe_anchors(dump):
    """The anchors as log lines, with every consistency check they allow."""
    a = read_anchors(dump)
    lines = [f"{name:<19} 0x{a[name]:08X}" for name in ANCHORS_FIELDS]
    rom = a["return_address"]
    lines.append(
        f"-> the ROM call site is 0x{rom & ~1:08X} ({'THUMB' if rom & 1 else 'ARM'} caller), "
        "the instruction after the call in Client_RunBufferScript [mystery_gift_client.c:276]")
    if not 0x08000000 <= (rom & ~1) < 0x0A000000:
        lines.append("   WARNING: that is not in the cartridge; the anchor is not what we think")
    lines.append(
        f"-> gDecompressionBuffer is 0x{a['code']:08X} "
        + ("(the 0x0201C000 deduction holds)" if a["code"] == 0x0201C000
           else "(NOT the deduced 0x0201C000 - docs/frlg_rom.md is wrong)"))
    if a["link_send_buffer"] != a["client_send_buffer"]:
        lines.append("   WARNING: link->sendBuffer is not client->sendBuffer; "
                     "the struct offsets this project computes from r0 are wrong")
    return lines

# save-dump's operands, from its literal pool; tests emulate a patched payload.
SAVE_DUMP_WHICH_OFFSET = 0x2C
SAVE_DUMP_OFFSET_OFFSET = 0x30
SAVE_DUMP_SIZE_OFFSET = 0x34

SAVE_BLOCK_2 = "sav2"       # r1, struct SaveBlock2: name, trainer id, pokedex, battle tower
SAVE_BLOCK_1 = "sav1"       # r2, struct SaveBlock1: party, bag, money, flags, vars
SAVE_BLOCKS = (SAVE_BLOCK_2, SAVE_BLOCK_1)
# Save regions the game never reads: `u8 filler[]` in SaveBlock2 [decomp:include/global.h:345,357],
# unreferenced in src/ but still saved to flash.
SAVE_SCRATCH = {
    SAVE_BLOCK_2: ((0x090, 0x008),      # filler_90
                   (0xB20, 0x400)),     # filler_B20
    SAVE_BLOCK_1: (),
}

# memory-dump's literal pool; tests emulate a patched payload.
DUMP_TARGET_OFFSET = 0x18
DUMP_SIZE_OFFSET = 0x1C

# memory-dump-multi: CLI_RUN_BUFFER_SCRIPT re-copies the image every pass
# [mystery_gift_client.c:238], so the block index lives in client->param [asm/memory-dump-multi.s].
# Offsets are the literal pool, checked by emulation (a count was once 0x10 off).
DUMP_MULTI_MAGIC_OFFSET = 0x44
DUMP_MULTI_BASE_OFFSET = 0x48
DUMP_MULTI_SIZE_OFFSET = 0x4C
DUMP_MULTI_MAGIC = 0x5A5A0000
# The payload's ceiling (a one-byte cursor); mg_script.MAX_DUMP_BLOCKS is lower.
MAX_DUMP_MULTI_BLOCKS = 0x100

# memory-dump-scatter: the cursor indexes a table of 32 bases carried in the payload.
DUMP_SCATTER_SIZE_OFFSET = 0x48
DUMP_SCATTER_TABLE_OFFSET = 0x4C
DUMP_SCATTER_TABLE_SLOTS = 32

# memory-scan: a payload returning 0 is called again next frame with its image intact
# [decomp:src/mystery_gift_client.c:239,276-280], so a 16 MB search loops across frames. The offsets
# are fixed by construction: the payload branches over its parameter block.
SCAN_CURSOR_OFFSET = 0x04       # the start address; the payload advances it
SCAN_END_OFFSET = 0x08
SCAN_NEEDLE_OFFSET = 0x0C
SCAN_BLOCKS_OFFSET = 0x10       # 32-byte blocks per call
SCAN_MAX_CALLS_OFFSET = 0x14    # watchdog; a payload that never returns 1 hangs the menu
SCAN_RESULT_OFFSET = 0x18
SCAN_HITS_OFFSET = 0x28
SCAN_HIT_CAPACITY = 64
SCAN_BLOCK_BYTES = 32           # one ldmia of eight words
# Fixed size, hits or not, so the host's length check proves the payload repointed the send.
SCAN_ANSWER_SIZE = 4 * 4 + 8 * SCAN_HIT_CAPACITY

# FireRed fills the first 16 MB of the cartridge window.
SCAN_ROM_START = 0x08000000
SCAN_ROM_END = 0x09000000
# ~14 ARM instructions per 8 words from EWRAM: milliseconds, while the console holds the link open.
SCAN_DEFAULT_BLOCKS = 512
MAX_SCAN_BLOCKS = 0x10000
MAX_SCAN_CALLS = 0x8000
# Readable without a bus abort: EWRAM up to the cartridge window. Below is the BIOS, above the
# second wait-state mirror.
SCAN_MIN_ADDRESS = 0x02000000
SCAN_MAX_ADDRESS = 0x0A000000

MEMORY_SCAN = "memory-scan"


def scan_call_count(start, end, blocks):
    """How many frames a scan of this range takes at this budget."""
    span_blocks = (int(end) - int(start)) // SCAN_BLOCK_BYTES
    return -(-span_blocks // int(blocks))


def build_memory_scan(needle, start=SCAN_ROM_START, end=SCAN_ROM_END,
                      blocks=SCAN_DEFAULT_BLOCKS, max_calls=None):
    """The memory-scan payload, patched; `max_calls` is a watchdog, defaulting to what the range
    needs plus two."""
    needle = int(needle) & 0xFFFFFFFF
    start, end, blocks = int(start), int(end), int(blocks)
    if not 0 < blocks <= MAX_SCAN_BLOCKS:
        raise BufferScriptError(
            f"a call scans 1..{MAX_SCAN_BLOCKS} blocks of {SCAN_BLOCK_BYTES} bytes, got {blocks}")
    if start % SCAN_BLOCK_BYTES or end % SCAN_BLOCK_BYTES:
        raise BufferScriptError(
            f"the range is scanned in {SCAN_BLOCK_BYTES}-byte blocks, so 0x{start:X}..0x{end:X} "
            f"must both be {SCAN_BLOCK_BYTES}-byte aligned")
    if not start < end:
        raise BufferScriptError(f"0x{start:X}..0x{end:X} is not a range")
    if start < SCAN_MIN_ADDRESS or end > SCAN_MAX_ADDRESS:
        raise BufferScriptError(
            f"0x{start:X}..0x{end:X} leaves the memory the CPU can read: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    needed = scan_call_count(start, end, blocks)
    max_calls = needed + 2 if max_calls is None else int(max_calls)
    if not 0 < max_calls <= MAX_SCAN_CALLS:
        raise BufferScriptError(
            f"the watchdog allows 1..{MAX_SCAN_CALLS} calls, got {max_calls}")
    code = bytearray(payload(MEMORY_SCAN))
    for offset, value in ((SCAN_CURSOR_OFFSET, start), (SCAN_END_OFFSET, end),
                          (SCAN_NEEDLE_OFFSET, needle), (SCAN_BLOCKS_OFFSET, blocks),
                          (SCAN_MAX_CALLS_OFFSET, max_calls)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def scan_parameters(code):
    """-> {needle, start, end, blocks, max_calls} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"start": word(SCAN_CURSOR_OFFSET), "end": word(SCAN_END_OFFSET),
            "needle": word(SCAN_NEEDLE_OFFSET), "blocks": word(SCAN_BLOCKS_OFFSET),
            "max_calls": word(SCAN_MAX_CALLS_OFFSET)}


def read_scan(dump):
    """-> what the scan found, from the bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < SCAN_ANSWER_SIZE:
        raise BufferScriptError(
            f"a scan answers with {SCAN_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, SCAN_ANSWER_SIZE, 4)]
    found, cursor, calls, stored = words[:4]
    stored = min(stored, SCAN_HIT_CAPACITY)
    hits = [(words[4 + 2 * i], words[5 + 2 * i]) for i in range(stored)]
    return {"found": found, "cursor": cursor, "calls": calls, "hits": hits}


def describe_scan(dump, needle=None, start=None, end=None):
    """The scan as log lines; a cursor short of `end` means the watchdog stopped it early."""
    scan = read_scan(dump)
    lines = [f"scan: {scan['found']} match(es) for "
             + ("the needle" if needle is None else f"0x{int(needle):08X}")
             + f", {scan['calls']} call(s) = frames, stopped at 0x{scan['cursor']:08X}"]
    if end is not None:
        if scan["cursor"] >= int(end):
            lines.append(f"   the whole range 0x{int(start):08X}..0x{int(end):08X} was scanned")
        else:
            done = scan["cursor"] - int(start)
            lines.append(
                f"   STOPPED EARLY: {done} of {int(end) - int(start)} bytes. The watchdog "
                f"(max_calls) ended it; re-run from 0x{scan['cursor']:08X}")
    if scan["found"] > len(scan["hits"]):
        lines.append(f"   only the first {len(scan['hits'])} of {scan['found']} are listed "
                     f"(the table holds {SCAN_HIT_CAPACITY})")
    for address, value in scan["hits"]:
        lines.append(f"   0x{address:08X}  0x{value:08X}")
    return lines


# table-scan: a run of N words each exactly D above the one before. gSpecialVars' first twelve
# entries point at consecutive u16s, so D is 2. docs/frlg_rom.md.
TABLE_CURSOR_OFFSET = 0x04       # the start address; the payload advances it
TABLE_END_OFFSET = 0x08
TABLE_DELTA_OFFSET = 0x0C        # what each word must exceed its predecessor by
TABLE_BLOCKS_OFFSET = 0x10       # 16-byte blocks per call
TABLE_MAX_CALLS_OFFSET = 0x14    # watchdog
TABLE_RESULT_OFFSET = 0x18
TABLE_HITS_OFFSET = 0x28
TABLE_HIT_CAPACITY = 64
TABLE_RUNLEN_OFFSET = 0x228      # how many words in a row make a run worth reporting
TABLE_RUN_OFFSET = 0x22C         # carried across the ldmia and the frame boundary
TABLE_RUNSTART_OFFSET = 0x230
TABLE_EXPECT_OFFSET = 0x234
TABLE_BLOCK_BYTES = 16           # one ldmia of four words
TABLE_ANSWER_SIZE = 4 * 4 + 8 * TABLE_HIT_CAPACITY
MAX_TABLE_RUN_LENGTH = 0x1000
# ~7 ARM instructions a word against memory-scan's ~1.75: 192 blocks is the same load per frame as
# memory-scan's 512, while the console holds the link open.
TABLE_SCAN_DEFAULT_BLOCKS = 192

# gSpecialVar_0x8000..0x800B; the named vars after them are declared in a different order, so the
# ascending run stops at twelve.
SPECIAL_VARS_DELTA = 2
SPECIAL_VARS_RUN_LENGTH = 12

TABLE_SCAN = "table-scan"


def table_scan_call_count(start, end, blocks):
    """How many frames a shape search over this range takes at this budget."""
    span_blocks = (int(end) - int(start)) // TABLE_BLOCK_BYTES
    return -(-span_blocks // int(blocks))


def build_table_scan(delta=SPECIAL_VARS_DELTA, runlen=SPECIAL_VARS_RUN_LENGTH,
                     start=SCAN_ROM_START, end=SCAN_ROM_END,
                     blocks=TABLE_SCAN_DEFAULT_BLOCKS, max_calls=None):
    """The table-scan payload, patched with a shape, a range and a frame budget."""
    delta = int(delta) & 0xFFFFFFFF
    runlen, start, end, blocks = int(runlen), int(start), int(end), int(blocks)
    if not 0 < blocks <= MAX_SCAN_BLOCKS:
        raise BufferScriptError(
            f"a call scans 1..{MAX_SCAN_BLOCKS} blocks of {TABLE_BLOCK_BYTES} bytes, got {blocks}")
    if not 1 < runlen <= MAX_TABLE_RUN_LENGTH:
        raise BufferScriptError(
            f"a run is 2..{MAX_TABLE_RUN_LENGTH} words; one word is not a shape, got {runlen}")
    if delta == 0:
        raise BufferScriptError(
            "a delta of 0 matches every stretch of repeated words - use memory-scan for a value")
    if start % TABLE_BLOCK_BYTES or end % TABLE_BLOCK_BYTES:
        raise BufferScriptError(
            f"the range is scanned in {TABLE_BLOCK_BYTES}-byte blocks, so 0x{start:X}..0x{end:X} "
            f"must both be {TABLE_BLOCK_BYTES}-byte aligned")
    if not start < end:
        raise BufferScriptError(f"0x{start:X}..0x{end:X} is not a range")
    if start < SCAN_MIN_ADDRESS or end > SCAN_MAX_ADDRESS:
        raise BufferScriptError(
            f"0x{start:X}..0x{end:X} leaves the memory the CPU can read: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    needed = table_scan_call_count(start, end, blocks)
    max_calls = needed + 2 if max_calls is None else int(max_calls)
    if not 0 < max_calls <= MAX_SCAN_CALLS:
        raise BufferScriptError(
            f"the watchdog allows 1..{MAX_SCAN_CALLS} calls, got {max_calls}")
    code = bytearray(payload(TABLE_SCAN))
    for offset, value in ((TABLE_CURSOR_OFFSET, start), (TABLE_END_OFFSET, end),
                          (TABLE_DELTA_OFFSET, delta), (TABLE_BLOCKS_OFFSET, blocks),
                          (TABLE_MAX_CALLS_OFFSET, max_calls),
                          (TABLE_RUNLEN_OFFSET, runlen)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def table_scan_parameters(code):
    """-> {delta, runlen, start, end, blocks, max_calls} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"start": word(TABLE_CURSOR_OFFSET), "end": word(TABLE_END_OFFSET),
            "delta": word(TABLE_DELTA_OFFSET), "blocks": word(TABLE_BLOCKS_OFFSET),
            "max_calls": word(TABLE_MAX_CALLS_OFFSET), "runlen": word(TABLE_RUNLEN_OFFSET)}


def read_table_scan(dump, start=None, end=None):
    """-> what the shape search found. A hit outside the range asked for is dropped: the payload
    can credit a run to the range's first word, whose `runstart` was never written."""
    dump = bytes(dump)
    if len(dump) < TABLE_ANSWER_SIZE:
        raise BufferScriptError(
            f"a table scan answers with {TABLE_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, TABLE_ANSWER_SIZE, 4)]
    found, cursor, calls, stored = words[:4]
    stored = min(stored, TABLE_HIT_CAPACITY)
    hits = [(words[4 + 2 * i], words[5 + 2 * i]) for i in range(stored)]
    dropped = []
    if start is not None and end is not None:
        keep = [(a, v) for a, v in hits if int(start) <= a < int(end)]
        dropped = [(a, v) for a, v in hits if not (int(start) <= a < int(end))]
        hits = keep
    return {"found": found, "cursor": cursor, "calls": calls, "hits": hits, "dropped": dropped}


def describe_table_scan(dump, delta=None, runlen=None, start=None, end=None):
    """The table scan as log lines; for gSpecialVars the first value is &gSpecialVar_0x8000."""
    scan = read_table_scan(dump, start, end)
    shape = ("a run" if runlen is None or delta is None
             else f"a run of {runlen} words rising by {delta}")
    lines = [f"table: {scan['found']} match(es) for {shape}, "
             f"{scan['calls']} call(s) = frames, stopped at 0x{scan['cursor']:08X}"]
    if end is not None:
        if scan["cursor"] >= int(end):
            lines.append(f"   the whole range 0x{int(start):08X}..0x{int(end):08X} was scanned")
        else:
            done = scan["cursor"] - int(start)
            lines.append(
                f"   STOPPED EARLY: {done} of {int(end) - int(start)} bytes. The watchdog "
                f"(max_calls) ended it; re-run from 0x{scan['cursor']:08X}")
    if scan["found"] > len(scan["hits"]) + len(scan["dropped"]):
        lines.append(f"   only the first {TABLE_HIT_CAPACITY} of {scan['found']} are listed")
    for address, value in scan["hits"]:
        lines.append(f"   table at 0x{address:08X}  first entry 0x{value:08X}")
    for address, value in scan["dropped"]:
        lines.append(f"   (dropped, outside the range asked for: 0x{address:08X} 0x{value:08X})")
    return lines


# rom-checksum: memory-scan's frame loop around a per-block sum; the host sums a ROM file the same
# way and names the blocks that differ. docs/frlg_rom.md, rom-checksum.
ROM_CHECKSUM = "rom-checksum"
ROM_CHECKSUM_CURSOR_OFFSET = 0x04     # the start address; the payload advances it
ROM_CHECKSUM_END_OFFSET = 0x08
ROM_CHECKSUM_START_OFFSET = 0x0C
ROM_CHECKSUM_BUDGET_OFFSET = 0x10     # 32-byte chunks per call
ROM_CHECKSUM_MAX_CALLS_OFFSET = 0x14  # watchdog
ROM_CHECKSUM_SHIFT_OFFSET = 0x18      # log2 of the block size in bytes
ROM_CHECKSUM_ACC_OFFSET = 0x1C        # the block in progress, across calls
ROM_CHECKSUM_RESULT_OFFSET = 0x20
ROM_CHECKSUM_SUMS_OFFSET = 0x30
ROM_CHECKSUM_CAPACITY = 128
ROM_CHECKSUM_CHUNK_BYTES = 32         # one ldmia of eight words
ROM_CHECKSUM_ANSWER_SIZE = 4 * 4 + 4 * ROM_CHECKSUM_CAPACITY
ROM_CHECKSUM_MIN_SHIFT = 5            # a block is at least one chunk
ROM_CHECKSUM_MAX_SHIFT = 25           # the 32 MB cartridge window
ROM_CHECKSUM_DEFAULT_BLOCK = 0x20000  # 128 KiB: 128 sums cover the 16 MB FireRed fills
# 13 ARM instructions per 8 words against memory-scan's 15: the same load.
ROM_CHECKSUM_DEFAULT_BUDGET = 512


def rom_checksum_call_count(start, end, budget):
    """How many frames a checksum of this range takes at this budget."""
    chunks = (int(end) - int(start)) // ROM_CHECKSUM_CHUNK_BYTES
    return -(-chunks // int(budget))


def build_rom_checksum(start=SCAN_ROM_START, end=SCAN_ROM_END, block=ROM_CHECKSUM_DEFAULT_BLOCK,
                       budget=ROM_CHECKSUM_DEFAULT_BUDGET, max_calls=None):
    """The rom-checksum payload, patched; `max_calls` defaults to what the range needs plus two."""
    start, end, block, budget = int(start), int(end), int(block), int(budget)
    shift = block.bit_length() - 1
    if block <= 0 or block != 1 << shift \
            or not ROM_CHECKSUM_MIN_SHIFT <= shift <= ROM_CHECKSUM_MAX_SHIFT:
        raise BufferScriptError(
            f"a block is a power of two from {1 << ROM_CHECKSUM_MIN_SHIFT} to "
            f"0x{1 << ROM_CHECKSUM_MAX_SHIFT:X} bytes, got {block}")
    if not 0 < budget <= MAX_SCAN_BLOCKS:
        raise BufferScriptError(
            f"a call sums 1..{MAX_SCAN_BLOCKS} chunks of {ROM_CHECKSUM_CHUNK_BYTES} bytes, "
            f"got {budget}")
    if not start < end:
        raise BufferScriptError(f"0x{start:X}..0x{end:X} is not a range")
    if start % block:
        raise BufferScriptError(
            f"0x{start:X} is not aligned to the 0x{block:X}-byte block; the payload finds a "
            "block boundary by the address alone")
    if (end - start) % block:
        raise BufferScriptError(
            f"0x{start:X}..0x{end:X} is not a whole number of 0x{block:X}-byte blocks; the last "
            "block would be partial and its sum never stored")
    if start < SCAN_MIN_ADDRESS or end > SCAN_MAX_ADDRESS:
        raise BufferScriptError(
            f"0x{start:X}..0x{end:X} leaves the memory the CPU can read: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    if (end - start) >> shift > ROM_CHECKSUM_CAPACITY:
        raise BufferScriptError(
            f"0x{start:X}..0x{end:X} is {(end - start) >> shift} blocks of 0x{block:X} bytes; "
            f"the answer holds {ROM_CHECKSUM_CAPACITY}. Use a larger block or a narrower range")
    needed = rom_checksum_call_count(start, end, budget)
    max_calls = needed + 2 if max_calls is None else int(max_calls)
    if not 0 < max_calls <= MAX_SCAN_CALLS:
        raise BufferScriptError(
            f"the watchdog allows 1..{MAX_SCAN_CALLS} calls, got {max_calls}")
    code = bytearray(payload(ROM_CHECKSUM))
    for offset, value in ((ROM_CHECKSUM_CURSOR_OFFSET, start), (ROM_CHECKSUM_END_OFFSET, end),
                          (ROM_CHECKSUM_START_OFFSET, start),
                          (ROM_CHECKSUM_BUDGET_OFFSET, budget),
                          (ROM_CHECKSUM_MAX_CALLS_OFFSET, max_calls),
                          (ROM_CHECKSUM_SHIFT_OFFSET, shift)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def rom_checksum_parameters(code):
    """-> {start, end, block, budget, max_calls} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"start": word(ROM_CHECKSUM_START_OFFSET), "end": word(ROM_CHECKSUM_END_OFFSET),
            "block": 1 << word(ROM_CHECKSUM_SHIFT_OFFSET),
            "budget": word(ROM_CHECKSUM_BUDGET_OFFSET),
            "max_calls": word(ROM_CHECKSUM_MAX_CALLS_OFFSET)}


def read_rom_checksum(dump):
    """-> {cursor, calls, stored, shift, sums} from the bytes the payload sent back."""
    dump = bytes(dump)
    if len(dump) < ROM_CHECKSUM_ANSWER_SIZE:
        raise BufferScriptError(
            f"a rom checksum answers with {ROM_CHECKSUM_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little")
             for i in range(0, ROM_CHECKSUM_ANSWER_SIZE, 4)]
    cursor, calls, stored, shift = words[:4]
    stored = min(stored, ROM_CHECKSUM_CAPACITY)
    return {"cursor": cursor, "calls": calls, "stored": stored, "shift": shift,
            "sums": words[4:4 + stored]}


def rom_checksum_reference(image, start, end, block, base=None):
    """-> the sums the payload computes over [start, end) of `image` loaded at `base`, one per
    block; None for a block the image does not wholly cover. acc = w + ror(acc, 31), from 0."""
    import sys
    from array import array
    image = memoryview(bytes(image))
    start, end, block = int(start), int(end), int(block)
    base = ROM_BASE if base is None else int(base)
    sums = []
    for address in range(start, end, block):
        offset = address - base
        if offset < 0 or offset + block > len(image):
            sums.append(None)
            continue
        words = array("I")
        assert words.itemsize == 4
        words.frombytes(image[offset:offset + block])
        if sys.byteorder != "little":
            words.byteswap()
        acc = 0
        for w in words:
            acc = (w + (((acc << 1) | (acc >> 31)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        sums.append(acc)
    return sums


def _open_bus_block(low, block):
    """What a GBA reads past the end of its cartridge: each halfword is its own address / 2."""
    return b"".join(((a >> 1) & 0xFFFF).to_bytes(2, "little") for a in range(low, low + block, 2))


def _past_image(console, low, block, reference):
    """Names a sum past the reference image: a known fill, a mirror of the image, or content."""
    fills = {"zero-filled": bytes(block), "0xFF-filled": b"\xff" * block,
             "open bus": _open_bus_block(low, block)}
    for name, data in fills.items():
        if rom_checksum_reference(data, low, low + block, block, base=low)[0] == console:
            return name
    if len(reference) and (low - ROM_BASE) % len(reference) + block <= len(reference):
        mirror = ROM_BASE + (low - ROM_BASE) % len(reference)
        if rom_checksum_reference(reference, mirror, mirror + block, block)[0] == console:
            return f"a mirror of 0x{mirror:08X}"
    return "CONTENT"


def describe_rom_checksum(dump, start=None, end=None, block=None, reference=None,
                          reference_name=None):
    """The answer as log lines, each block's sum against `reference` (the ROM image's bytes, or None
    to list the console's sums alone)."""
    got = read_rom_checksum(dump)
    block = (1 << got["shift"]) if block is None else int(block)
    lines = [f"rom-checksum: {got['stored']} block sum(s) of 0x{block:X} bytes, "
             f"{got['calls']} call(s) = frames, stopped at 0x{got['cursor']:08X}"]
    if got["shift"] != block.bit_length() - 1:
        lines.append(f"   the answer names 0x{1 << got['shift']:X}-byte blocks, not the "
                     f"0x{block:X} asked for; this is not the payload that was sent")
        return lines
    if start is None:
        start = got["cursor"] - got["stored"] * block
    if end is not None:
        if got["cursor"] >= int(end):
            lines.append(f"   the whole range 0x{int(start):08X}..0x{int(end):08X} was summed")
        else:
            lines.append(
                f"   STOPPED EARLY: {got['cursor'] - int(start)} of {int(end) - int(start)} "
                f"bytes. The watchdog (max_calls) ended it; re-run from 0x{got['cursor']:08X}")
    expected = ([None] * got["stored"] if reference is None else
                rom_checksum_reference(reference, start, int(start) + got["stored"] * block,
                                       block))
    compared = differ = 0
    for i, (console, ours) in enumerate(zip(got["sums"], expected)):
        low = int(start) + i * block
        if ours is None:
            verdict, ours_text = ("" if reference is None else
                                  "no reference, " + _past_image(console, low, block, reference)), "-" * 10
        else:
            compared += 1
            same = console == ours
            differ += not same
            verdict, ours_text = ("SAME" if same else "DIFF"), f"0x{ours:08X}"
        lines.append(f"   0x{low:08X}..0x{low + block:08X}  console 0x{console:08X}  "
                     f"reference {ours_text}  {verdict}".rstrip())
    if reference is not None:
        lines.append(f"rom-checksum: {differ} of {compared} blocks differ from "
                     f"{reference_name or 'the reference image'}")
    return lines


# string-gather: dereferences a pointer array and sends back the strings, a whole Easy Chat group a
# run. It never truncates (a half word reads as a short French word); `next` names where to resume,
# and `maxlen` stops a pointer that is no string. docs/frlg_rom.md.
STRING_GATHER = "string-gather"
GATHER_SRC_OFFSET = 0x04        # the first pointer; the payload advances it
GATHER_STRIDE_OFFSET = 0x08     # 12 for struct EasyChatWordInfo, `text` at offset 0
GATHER_COUNT_OFFSET = 0x0C
GATHER_BUDGET_OFFSET = 0x10
GATHER_MAXLEN_OFFSET = 0x14
GATHER_RESULT_OFFSET = 0x18
GATHER_STRINGS_OFFSET = 0x28
# Fixed in asm/string-gather.s so the image is exactly MAX_BUFFER_SCRIPT_SIZE.
GATHER_STRING_AREA = 760
GATHER_ANSWER_SIZE = 4 * 4 + GATHER_STRING_AREA
# Terminator included; the longest English word is 15 characters.
GATHER_DEFAULT_MAXLEN = 64
GATHER_STOP = {0: "followed every pointer asked for",
               1: "the budget ran out - re-run from `next`",
               2: "a pointer with no terminator within maxlen: NOT a string table"}
EOS = 0xFF                      # [decomp:include/characters.h]


def build_string_gather(src, count, stride=12, budget=None, maxlen=GATHER_DEFAULT_MAXLEN):
    """The string-gather payload. `src` is the address of the first pointer; `stride` is 4 for
    `const u8 *[]`, 12 for struct EasyChatWordInfo."""
    src, count, stride = int(src), int(count), int(stride)
    budget = GATHER_STRING_AREA if budget is None else int(budget)
    maxlen = int(maxlen)
    if not 0 <= src <= 0xFFFFFFFF or src % 4:
        raise BufferScriptError(
            f"0x{src:X} is not a word-aligned address, so it is not an array of pointers")
    if not 0 < stride <= 0x1000 or stride % 4:
        raise BufferScriptError(f"the stride between pointers is a positive multiple of 4, got {stride}")
    if not 0 < count <= 0x10000:
        raise BufferScriptError(f"a run follows 1..65536 pointers, got {count}")
    if not 0 < budget <= GATHER_STRING_AREA:
        raise BufferScriptError(
            f"the answer holds 1..{GATHER_STRING_AREA} bytes of string, got {budget}")
    if not 0 < maxlen <= GATHER_STRING_AREA:
        raise BufferScriptError(f"maxlen is 1..{GATHER_STRING_AREA}, got {maxlen}")
    code = bytearray(payload(STRING_GATHER))
    for offset, value in ((GATHER_SRC_OFFSET, src), (GATHER_STRIDE_OFFSET, stride),
                          (GATHER_COUNT_OFFSET, count), (GATHER_BUDGET_OFFSET, budget),
                          (GATHER_MAXLEN_OFFSET, maxlen)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def gather_parameters(code):
    """-> {src, stride, count, budget, maxlen} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"src": word(GATHER_SRC_OFFSET), "stride": word(GATHER_STRIDE_OFFSET),
            "count": word(GATHER_COUNT_OFFSET), "budget": word(GATHER_BUDGET_OFFSET),
            "maxlen": word(GATHER_MAXLEN_OFFSET)}


def read_gather(dump):
    """-> what the walk collected; `strings` are in the game's encoding, terminators stripped."""
    dump = bytes(dump)
    if len(dump) < GATHER_ANSWER_SIZE:
        raise BufferScriptError(
            f"a string-gather answers with {GATHER_ANSWER_SIZE} bytes, got {len(dump)}")
    copied, written, resume, reason = (
        int.from_bytes(dump[i:i + 4], "little") for i in range(0, 16, 4))
    written = min(written, GATHER_STRING_AREA)
    blob = dump[16:16 + written]
    strings = [piece for piece in blob.split(bytes([EOS]))][:copied]
    return {"copied": copied, "written": written, "next": resume, "reason": reason,
            "strings": strings}


def describe_gather(dump, src=None, stride=None, count=None):
    """The gather as log lines; a short run is the budget; `next` is where the next starts."""
    from pokeldn.frlg.text import charmap
    gathered = read_gather(dump)
    lines = [f"gather: {gathered['copied']} string(s), {gathered['written']} bytes"
             + ("" if src is None else f", from 0x{int(src):08X}")
             + (f" of {int(count)} asked for" if count is not None else "")
             + f"; resume at 0x{gathered['next']:08X}"]
    lines.append("   " + GATHER_STOP.get(gathered["reason"], f"reason {gathered['reason']}"))
    for index, raw in enumerate(gathered["strings"]):
        lines.append(f"   {index:>3}  {charmap.decode(raw)!r}")
    return lines


# rng-trace: read the word, call the function, read again, and check after == before * RAND_MULT +
# RAND_ADD [decomp:include/random.h:18-19]: address and call in one run.
RNG_TRACE = "rng-trace"
TRACE_ADDRESS_OFFSET = 0x04
TRACE_FUNCTION_OFFSET = 0x08
TRACE_SAMPLES_OFFSET = 0x0C
TRACE_MAX_CALLS_OFFSET = 0x10
TRACE_RESULT_OFFSET = 0x14
TRACE_SAMPLE_CAPACITY = 96          # 2 words each; the image is 1012 bytes
TRACE_HEADER_SIZE = 16

RAND_MULT = 1103515245              # 0x41C64E6D [decomp:include/random.h:18]
RAND_ADD = 24691                    # ISO_RANDOMIZE1's addend [:19]


def rand_step(value):
    """One turn of the game's LCG."""
    return (value * RAND_MULT + RAND_ADD) & 0xFFFFFFFF


def trace_answer_size(samples):
    return TRACE_HEADER_SIZE + 8 * int(samples)


def build_rng_trace(address, function=0, samples=TRACE_SAMPLE_CAPACITY, max_calls=None):
    """The rng-trace payload. `function` is a THUMB pointer to an ordinary returning function, or 0
    for a plain per-frame sampler."""
    address, function, samples = int(address), int(function), int(samples)
    if address % 4:
        raise BufferScriptError(f"0x{address:X} is not word aligned")
    if not SCAN_MIN_ADDRESS <= address < SCAN_MAX_ADDRESS:
        raise BufferScriptError(
            f"0x{address:X} is outside the memory the CPU can read: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    if function:
        if not function & 1:
            raise BufferScriptError(
                f"0x{function:X} is an ARM pointer; the ROM is THUMB, so a callable address has "
                "bit 0 set (the `bx` selects the state from it)")
        if not ROM_BASE <= function < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{function:X} is not in the cartridge; calling it would run whatever is there")
    if not 0 < samples <= TRACE_SAMPLE_CAPACITY:
        raise BufferScriptError(
            f"a trace takes 1..{TRACE_SAMPLE_CAPACITY} samples, got {samples}")
    max_calls = samples + 2 if max_calls is None else int(max_calls)
    if not 0 < max_calls <= MAX_SCAN_CALLS:
        raise BufferScriptError(f"the watchdog allows 1..{MAX_SCAN_CALLS} calls, got {max_calls}")
    code = bytearray(payload(RNG_TRACE))
    for offset, value in ((TRACE_ADDRESS_OFFSET, address), (TRACE_FUNCTION_OFFSET, function),
                          (TRACE_SAMPLES_OFFSET, samples), (TRACE_MAX_CALLS_OFFSET, max_calls)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def trace_parameters(code):
    """-> {address, function, samples, max_calls} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"address": word(TRACE_ADDRESS_OFFSET), "function": word(TRACE_FUNCTION_OFFSET),
            "samples": word(TRACE_SAMPLES_OFFSET), "max_calls": word(TRACE_MAX_CALLS_OFFSET)}


def read_rng_trace(dump):
    """-> what the trace sampled, from the bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < TRACE_HEADER_SIZE:
        raise BufferScriptError(f"a trace answers with at least {TRACE_HEADER_SIZE} bytes, "
                                f"got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, len(dump) - 3, 4)]
    calls, taken, address, function = words[:4]
    taken = min(taken, (len(words) - 4) // 2, TRACE_SAMPLE_CAPACITY)
    pairs = [(words[4 + 2 * i], words[5 + 2 * i]) for i in range(taken)]
    return {"calls": calls, "taken": taken, "address": address, "function": function,
            "samples": pairs}


def lcg_distance(start, target, limit=1 << 16):
    """Turns of the LCG from `start` to `target`, or None within `limit`."""
    value = start & 0xFFFFFFFF
    for steps in range(int(limit)):
        if value == (target & 0xFFFFFFFF):
            return steps
        value = rand_step(value)
    return None


def describe_rng_trace(dump):
    """The trace as log lines, with the recurrence checked."""
    trace = read_rng_trace(dump)
    lines = [f"rng-trace: {trace['taken']} sample(s) of 0x{trace['address']:08X} over "
             f"{trace['calls']} call(s) = frames"
             + (f", calling 0x{trace['function']:08X}" if trace["function"] else
                ", calling nothing")]
    samples = trace["samples"]
    if not samples:
        return lines + ["   nothing was sampled"]
    if trace["function"]:
        held = sum(1 for before, after in samples if after == rand_step(before))
        lines.append(
            f"   the LCG recurrence after == before * {RAND_MULT} + {RAND_ADD} holds on "
            f"{held}/{len(samples)} samples"
            + (" - THE ADDRESS IS gRngValue AND THE ROM CALL RAN" if held == len(samples)
               else " - it does NOT hold, so one of the two is wrong"))
    changed = sum(1 for i in range(1, len(samples)) if samples[i][0] != samples[i - 1][1])
    gaps = [lcg_distance(samples[i - 1][1], samples[i][0]) for i in range(1, len(samples))]
    known = [g for g in gaps if g is not None]
    lines.append(
        f"   between frames the word changed {changed}/{len(samples) - 1} times"
        + (f"; the game's own Random calls per frame: min {min(known)}, max {max(known)}, "
           f"total {sum(known)}" if known and len(known) == len(gaps) else
           "; some frame-to-frame gaps are not on the LCG orbit"))
    lines.append("   first: " + ", ".join(f"0x{b:08X}->0x{a:08X}" for b, a in samples[:3]))
    lines.append("   last:  " + ", ".join(f"0x{b:08X}->0x{a:08X}" for b, a in samples[-3:]))
    return lines


# call: an address, up to eight argument words (r0..r3, then [sp+0..12], not popped by the callee,
# as CreateMon's prologue shows), the r0 back, and one watched word either side: SeedRng returns
# nothing [decomp:src/random.c:15]. asm/call.s, docs/frlg_rom.md.

CALL = "call"
CALL_FUNCTION_OFFSET = 0x04
CALL_ARGC_OFFSET = 0x08
CALL_ARGS_OFFSET = 0x0C
CALL_WATCH_OFFSET = 0x2C
CALL_RESULT_OFFSET = 0x30
CALL_MAX_ARGS = 8
CALL_ANSWER_SIZE = 24


def build_call(function, args=(), watch=0):
    """The `call` payload. `function` 0 calls nothing and reads `watch` twice; `watch` 0 watches
    nothing."""
    function, watch = int(function), int(watch)
    args = [int(a) & 0xFFFFFFFF for a in args]
    if len(args) > CALL_MAX_ARGS:
        raise BufferScriptError(
            f"the call passes at most {CALL_MAX_ARGS} arguments: four in r0..r3 and four on the "
            f"stack. Got {len(args)}")
    if function:
        if not function & 1:
            raise BufferScriptError(
                f"0x{function:X} is an ARM pointer; the ROM is THUMB, so a callable address has "
                "bit 0 set (the `bx` selects the state from it)")
        if not ROM_BASE <= function < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{function:X} is not in the cartridge; calling it would run whatever is there")
    if watch:
        if watch % 4:
            raise BufferScriptError(f"0x{watch:X} is not word aligned")
        if not SCAN_MIN_ADDRESS <= watch < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{watch:X} is outside the memory the CPU can read: "
                f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    code = bytearray(payload(CALL))
    def put(offset, value):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    put(CALL_FUNCTION_OFFSET, function)
    put(CALL_ARGC_OFFSET, len(args))
    put(CALL_WATCH_OFFSET, watch)
    for index, value in enumerate(args):
        put(CALL_ARGS_OFFSET + 4 * index, value)
    return bytes(code)


def call_parameters(code):
    """-> {function, argc, args, watch} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    argc = word(CALL_ARGC_OFFSET)
    return {"function": word(CALL_FUNCTION_OFFSET), "argc": argc, "watch": word(CALL_WATCH_OFFSET),
            "args": [word(CALL_ARGS_OFFSET + 4 * i) for i in range(CALL_MAX_ARGS)][:argc]}


def read_call(dump):
    """-> what the call answered, from the 24 bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < CALL_ANSWER_SIZE:
        raise BufferScriptError(f"a call answers with {CALL_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, CALL_ANSWER_SIZE, 4)]
    calls, function, argc, returned, before, after = words
    return {"calls": calls, "function": function, "argc": argc, "returned": returned,
            "before": before, "after": after}


def describe_call(dump, expected=None):
    """The call as log lines, with `expected` checked against the watched word after it."""
    got = read_call(dump)
    lines = [f"call: 0x{got['function']:08X} with {got['argc']} argument(s) in {got['calls']} "
             f"call(s), returned 0x{got['returned']:08X} ({got['returned'] & 0xFFFF} as a u16)"]
    if got["function"] == 0:
        lines[0] = (f"call: nothing was called ({got['calls']} call(s)); the two reads of the "
                    "watched word are the whole answer")
    lines.append(f"   watched word: 0x{got['before']:08X} before -> 0x{got['after']:08X} after"
                 + (" (unchanged)" if got["before"] == got["after"] else ""))
    if expected is not None:
        expected &= 0xFFFFFFFF
        lines.append(f"   expected 0x{expected:08X} after the call: "
                     + ("IT HOLDS - the call ran and did what it was called for"
                        if got["after"] == expected else
                        "IT DOES NOT - the call did not do what it was called for"))
    return lines


# call-chain: up to CHAIN_MAX_STEPS calls and accesses in one frame, one word back per step. PREV
# exists for `call GetVarPointer; write16 [prev]`: ScrCmd_setvar writes through GetVarPointer's
# return [decomp:src/scrcmd.c:472]. asm/call-chain.s has the step layout.

CALL_CHAIN = "call-chain"
CHAIN_COUNT_OFFSET = 0x04
CHAIN_STEPS_OFFSET = 0x10
CHAIN_STEP_SIZE = 24
CHAIN_MAX_STEPS = 16
CHAIN_MAX_ARGS = 4                  # r0..r3
CHAIN_RESULT_OFFSET = 0x190
CHAIN_VALUES_OFFSET = 0x1A0
CHAIN_ANSWER_SIZE = 16 + 4 * CHAIN_MAX_STEPS

# The opcodes, as asm/call-chain.s dispatches them.
CHAIN_END = 0
CHAIN_CALL = 1
CHAIN_READ32 = 2
CHAIN_READ16 = 3
CHAIN_READ8 = 4
CHAIN_WRITE32 = 5
CHAIN_WRITE16 = 6
CHAIN_WRITE8 = 7
# Modifier bits and the argument count. The payload loads all four argument words regardless; the
# count is for the log.
CHAIN_TARGET_FROM_PREV = 0x100
CHAIN_ARG_FROM_PREV = 0x200      # the first argument is PREV + a0
CHAIN_KEEP_PREV = 0x400
CHAIN_ARGC_SHIFT = 16
CHAIN_ARGC_MASK = 0xF

CHAIN_OPS = {
    "call": CHAIN_CALL,
    "read32": CHAIN_READ32,
    "read16": CHAIN_READ16,
    "read8": CHAIN_READ8,
    "write32": CHAIN_WRITE32,
    "write16": CHAIN_WRITE16,
    "write8": CHAIN_WRITE8,
}
CHAIN_OP_NAMES = {value: name for name, value in CHAIN_OPS.items()}
CHAIN_READS = (CHAIN_READ32, CHAIN_READ16, CHAIN_READ8)
CHAIN_WRITES = (CHAIN_WRITE32, CHAIN_WRITE16, CHAIN_WRITE8)
# Access width, which is also the target's alignment.
CHAIN_WIDTH = {CHAIN_READ32: 4, CHAIN_READ16: 2, CHAIN_READ8: 1,
               CHAIN_WRITE32: 4, CHAIN_WRITE16: 2, CHAIN_WRITE8: 1}


@dataclass(frozen=True)
class ChainStep:
    """One step: an opcode, a target, and up to four argument words. `target_from_prev` makes the
    target prev + `target`; `arg_from_prev` does the same to the first argument
    (`AddMoney(&money)` is prev + 0x290). The console resolves both."""
    op: int
    target: int = 0
    args: tuple = ()
    target_from_prev: bool = False
    arg_from_prev: bool = False
    keep_prev: bool = False
    # A named call: build_call_chain resolves it on the build the chain is for.
    function_name: str | None = dataclasses.field(default=None, compare=False)

    @property
    def op_word(self):
        return (int(self.op) & 0xFF
                | (CHAIN_TARGET_FROM_PREV if self.target_from_prev else 0)
                | (CHAIN_ARG_FROM_PREV if self.arg_from_prev else 0)
                | (CHAIN_KEEP_PREV if self.keep_prev else 0)
                | (min(len(self.args), CHAIN_ARGC_MASK) << CHAIN_ARGC_SHIFT))

    @property
    def name(self):
        return CHAIN_OP_NAMES.get(int(self.op) & 0xFF, f"op {int(self.op) & 0xFF}")

    def describe(self):
        keep = " keep" if self.keep_prev else ""
        target = "prev" if self.target_from_prev else f"0x{self.target:08X}"
        if self.target_from_prev and self.target:
            target = f"prev + 0x{self.target:X}"
        if self.op == CHAIN_CALL:
            def argument(index, value):
                if index or not self.arg_from_prev:
                    return f"0x{value:X}"
                return f"prev + 0x{value:X}" if value else "prev"
            args = [argument(i, a) for i, a in enumerate(self.args)] \
                or (["prev"] if self.arg_from_prev else [])
            return f"call {target}({', '.join(args)}){keep}"
        if self.op in CHAIN_READS:
            return f"{self.name} [{target}]{keep}"
        first = (self.args or (0,))[0]
        value = (("prev" if not first else f"prev + 0x{first:X}") if self.arg_from_prev
                 else f"0x{first:X}")
        return f"{self.name} [{target}] = {value}"


def chain_call(function, args=(), *, arg_from_prev=False):
    """A CALL step; `function` is a THUMB pointer (Build.callable_function)."""
    return ChainStep(CHAIN_CALL, int(function), tuple(int(a) & 0xFFFFFFFF for a in args),
                     arg_from_prev=bool(arg_from_prev))


def chain_read(address, size=4, *, from_prev=False, keep_prev=False):
    """A READ step of 1, 2 or 4 bytes; `keep_prev` leaves the pointer as prev."""
    op = {4: CHAIN_READ32, 2: CHAIN_READ16, 1: CHAIN_READ8}.get(int(size))
    if op is None:
        raise BufferScriptError(f"a read is 1, 2 or 4 bytes, got {size}")
    return ChainStep(op, int(address), target_from_prev=bool(from_prev),
                     keep_prev=bool(keep_prev))


def chain_write(address, value=0, size=2, *, from_prev=False, value_from_prev=False):
    """A WRITE step of 1, 2 or 4 bytes, which reads itself back into the answer."""
    op = {4: CHAIN_WRITE32, 2: CHAIN_WRITE16, 1: CHAIN_WRITE8}.get(int(size))
    if op is None:
        raise BufferScriptError(f"a write is 1, 2 or 4 bytes, got {size}")
    return ChainStep(op, int(address), (int(value) & 0xFFFFFFFF,),
                     target_from_prev=bool(from_prev), arg_from_prev=bool(value_from_prev))


def parse_chain_step(text, resolve=None):
    """-> a ChainStep from `OP[+keep]:TARGET[,ARG]...`: `call:FlagSet,0x828`, `write16:prev,7`,
    `read32:prev+4`. Only the first argument may be `prev[+N]`. A named call keeps its name so
    build_call_chain resolves it on the build it is sent to."""
    resolve = builds.DEFAULT.callable_function if resolve is None else resolve
    head, _, rest = str(text).strip().partition(":")
    head = head.strip().lower()
    keep_prev = head.endswith("+keep")
    if keep_prev:
        head = head[:-len("+keep")].strip()
    op = CHAIN_OPS.get(head)
    if op is None:
        raise BufferScriptError(
            f"{text!r}: a step starts with one of {', '.join(sorted(CHAIN_OPS))}, each of which "
            "may carry a +keep suffix meaning `do not make this step's result the new prev`")
    fields = [f.strip() for f in rest.split(",")] if rest.strip() else []
    if not fields:
        raise BufferScriptError(f"{text!r}: a step needs a target")

    def number(field):
        try:
            return int(field, 0) & 0xFFFFFFFF
        except ValueError:
            raise BufferScriptError(f"{text!r}: {field!r} is not a number") from None

    target_text, args_text = fields[0], fields[1:]
    target_from_prev, target, function_name = False, 0, None
    if target_text.lower().startswith("prev"):
        target_from_prev = True
        tail = target_text[4:].strip()
        if tail:
            if not tail.startswith("+"):
                raise BufferScriptError(
                    f"{text!r}: a prev target is `prev` or `prev+N`, got {target_text!r}")
            target = number(tail[1:].strip())
    elif op == CHAIN_CALL:
        try:
            target = resolve(target_text)
            function_name = target_text
        except KeyError:
            target = number(target_text)
    else:
        target = number(target_text)

    arg_from_prev = False
    args = []
    for index, field in enumerate(args_text):
        if field.lower().startswith("prev"):
            if index:
                raise BufferScriptError(
                    f"{text!r}: only the FIRST argument can be prev - the payload carries one "
                    "previous result, not a register file")
            arg_from_prev = True
            tail = field[4:].strip()
            if tail and not tail.startswith("+"):
                raise BufferScriptError(
                    f"{text!r}: a prev argument is `prev` or `prev+N`, got {field!r}")
            args.append(number(tail[1:].strip()) if tail else 0)
        else:
            args.append(number(field))
    return ChainStep(op, target, tuple(args), target_from_prev=target_from_prev,
                     arg_from_prev=arg_from_prev, keep_prev=keep_prev,
                     function_name=function_name)


def build_call_chain(steps, *, unsafe=False, build=None):
    """The `call-chain` payload, steps executed in order in one frame. Every write needs `unsafe`:
    there is no scratch region here."""
    build = builds.resolve(build)
    try:
        steps = [step if step.function_name is None else
                 ChainStep(step.op, build.callable_function(step.function_name), step.args,
                           step.target_from_prev, step.arg_from_prev, step.keep_prev,
                           step.function_name)
                 for step in steps]
    except KeyError as exc:
        raise BufferScriptError(str(exc.args[0])) from None
    if not steps:
        raise BufferScriptError(
            "a chain needs at least one step; an empty one would send back sixteen zeroes")
    if len(steps) > CHAIN_MAX_STEPS:
        raise BufferScriptError(
            f"a chain is at most {CHAIN_MAX_STEPS} steps, got {len(steps)}")
    code = bytearray(payload(CALL_CHAIN))
    def put(offset, value):
        code[offset:offset + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    put(CHAIN_COUNT_OFFSET, len(steps))
    for index, step in enumerate(steps):
        op = int(step.op) & 0xFF
        if op not in CHAIN_OP_NAMES:
            raise BufferScriptError(
                f"step {index + 1}: {op} is not an opcode asm/call-chain.s dispatches; "
                "the payload would stop there")
        if len(step.args) > CHAIN_MAX_ARGS:
            raise BufferScriptError(
                f"step {index + 1}: a chained call passes at most {CHAIN_MAX_ARGS} arguments, in "
                f"r0..r3; the stack arguments are what `{CALL}` is for (got {len(step.args)})")
        if op == CHAIN_CALL:
            if step.target_from_prev:
                raise BufferScriptError(
                    f"step {index + 1}: a call to an address computed on the console cannot be "
                    "checked from here, and a wrong one hangs the Mystery Gift menu with no way "
                    "out. Name the function.")
            if not step.target & 1:
                raise BufferScriptError(
                    f"step {index + 1}: 0x{step.target:X} is an ARM pointer; the ROM is THUMB, so "
                    "a callable address has bit 0 set (the `bx` selects the state from it)")
            if not ROM_BASE <= step.target < SCAN_MAX_ADDRESS:
                raise BufferScriptError(
                    f"step {index + 1}: 0x{step.target:X} is not in the cartridge; calling it "
                    "would run whatever is there")
        else:
            width = CHAIN_WIDTH[op]
            if not step.target_from_prev:
                if step.target % width:
                    raise BufferScriptError(
                        f"step {index + 1}: 0x{step.target:X} is not {width}-byte aligned")
                if not SCAN_MIN_ADDRESS <= step.target < SCAN_MAX_ADDRESS:
                    raise BufferScriptError(
                        f"step {index + 1}: 0x{step.target:X} is outside the memory the CPU can "
                        f"reach: 0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
            if op in CHAIN_WRITES and not unsafe:
                raise BufferScriptError(
                    f"step {index + 1}: {CHAIN_OP_NAMES[op]} writes the console's live memory, "
                    "which the console commits to flash when it saves. There is no scratch "
                    "region to be safe in here, so every write needs --write-unsafe.")
        base = CHAIN_STEPS_OFFSET + CHAIN_STEP_SIZE * index
        put(base, step.op_word)
        put(base + 4, step.target)
        for slot in range(CHAIN_MAX_ARGS):
            put(base + 8 + 4 * slot, step.args[slot] if slot < len(step.args) else 0)
    return bytes(code)


def chain_parameters(code):
    """-> {count, steps} read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    count = min(word(CHAIN_COUNT_OFFSET), CHAIN_MAX_STEPS)
    steps = []
    for index in range(count):
        base = CHAIN_STEPS_OFFSET + CHAIN_STEP_SIZE * index
        op_word = word(base)
        argc = min((op_word >> CHAIN_ARGC_SHIFT) & CHAIN_ARGC_MASK, CHAIN_MAX_ARGS)
        steps.append(ChainStep(
            op_word & 0xFF, word(base + 4),
            tuple(word(base + 8 + 4 * slot) for slot in range(argc)),
            target_from_prev=bool(op_word & CHAIN_TARGET_FROM_PREV),
            arg_from_prev=bool(op_word & CHAIN_ARG_FROM_PREV),
            keep_prev=bool(op_word & CHAIN_KEEP_PREV)))
    return {"count": word(CHAIN_COUNT_OFFSET), "steps": steps}


def read_call_chain(dump):
    """-> what the chain answered, from the 80 bytes it sent back."""
    dump = bytes(dump)
    if len(dump) < CHAIN_ANSWER_SIZE:
        raise BufferScriptError(
            f"a chain answers with {CHAIN_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little") for i in range(0, CHAIN_ANSWER_SIZE, 4)]
    calls, count, executed, refused = words[:4]
    return {"calls": calls, "count": count, "executed": min(executed, CHAIN_MAX_STEPS),
            "refused": refused, "values": words[4:4 + CHAIN_MAX_STEPS]}


def describe_call_chain(dump, steps=None):
    """The chain as log lines, each result beside its step."""
    got = read_call_chain(dump)
    lines = [f"call-chain: {got['executed']} of {got['count']} step(s) ran in {got['calls']} "
             "call(s) = frames"]
    asked = list(steps or ())
    for index in range(got["executed"]):
        value = got["values"][index]
        step = asked[index].describe() if index < len(asked) else "step"
        lines.append(f"   {index + 1}. {step} -> 0x{value:08X} ({value & 0xFFFF} as a u16)")
    if got["refused"]:
        lines.append(f"   STOPPED: op word 0x{got['refused']:08X} is not one this payload has, "
                     "so nothing after it ran")
    elif got["executed"] < got["count"]:
        lines.append(f"   STOPPED after {got['executed']} of {got['count']}: a step's op word was "
                     "zero, which is END")
    return lines


# create-mon: CreateMon's eight arguments, four in r0..r3 and four at entry sp+0..12. The mon is
# built inside our image; `destination` copies it on and is a live write. docs/frlg_rom.md.
CREATE_MON = "create-mon"
CREATE_MON_FUNCTION_OFFSET = 0x04
CREATE_MON_DESTINATION_OFFSET = 0x08
CREATE_MON_PARTY_APPEND_OFFSET = 0x0C
CREATE_MON_PARTY_BASE_OFFSET = 0x10
CREATE_MON_PARTY_COUNT_OFFSET = 0x14
CREATE_MON_SPECIES_OFFSET = 0x18
CREATE_MON_LEVEL_OFFSET = 0x1C
CREATE_MON_FIXED_IV_OFFSET = 0x20
CREATE_MON_HAS_FIXED_PERSONALITY_OFFSET = 0x24
CREATE_MON_FIXED_PERSONALITY_OFFSET = 0x28
CREATE_MON_OT_ID_TYPE_OFFSET = 0x2C
CREATE_MON_FIXED_OT_ID_OFFSET = 0x30
CREATE_MON_RESULT_OFFSET = 0x34
CREATE_MON_MON_OFFSET = 0x44
CREATE_MON_PARTY_OFFSET = 0xA8
# struct Pokemon [decomp:include/pokemon.h]: an 80-byte BoxPokemon and 20 bytes of party data.
PARTY_MON_SIZE = 100
PARTY_SIZE = 6                      # [decomp:include/constants/party_menu.h]
CREATE_MON_HEADER_SIZE = 16
# The party word is an addendum past header and mon, so a 116-byte answer still reads.
CREATE_MON_ANSWER_SIZE = CREATE_MON_HEADER_SIZE + PARTY_MON_SIZE + 4

# struct SaveBlock1 [decomp:include/global.h:772]. For reading only: SavePlayerParty overwrites it
# from gPlayerParty [decomp:src/load_save.c:160].
SAV1_PARTY_COUNT = 0x34
SAV1_PARTY = 0x38
SAV1_VARS = 0x1000                  # u16 vars[], indexed by id - VARS_START

# struct MysteryGiftSave at SaveBlock1 + 0x3120 [decomp:include/global.h:681]. The card metadata
# counters are read with no CRC check [decomp:src/mystery_gift.c:490].
SAV1_MYSTERY_GIFT = 0x3120
SAV1_CARD_METADATA = SAV1_MYSTERY_GIFT + 0x314
SAV1_CARD_BATTLES_WON = SAV1_CARD_METADATA + 0
SAV1_CARD_BATTLES_LOST = SAV1_CARD_METADATA + 2
SAV1_CARD_NUM_TRADES = SAV1_CARD_METADATA + 4
SAV1_CARD_ICON_SPECIES = SAV1_CARD_METADATA + 6


def sav1_var_offset(var_id):
    """-> a saved var's offset in SaveBlock1 [decomp:src/event_data.c:186]."""
    if not 0x4000 <= int(var_id) <= 0x40FF:
        raise ValueError(f"0x{int(var_id):04X} is not a saved var (0x4000..0x40FF)")
    return SAV1_VARS + 2 * (int(var_id) - 0x4000)

# The status half of the party word the payload sends back.
PARTY_WRITE_NONE = 0                # no party write was asked for
PARTY_WRITE_APPENDED = 1            # written at slot == count, count raised
PARTY_WRITE_FULL = 2                # six mons already: nothing written, nothing changed
PARTY_WRITE_DRY_RUN = 3             # nothing written; the bytes are the slot's contents

# An empty slot is not all zeros: ZeroMonData sets mail (0x55) to MAIL_NONE
# [decomp:src/pokemon.c:1737].
EMPTY_PARTY_SLOT = bytes(85) + b"\xFF" + bytes(PARTY_MON_SIZE - 86)


def is_empty_party_slot(raw):
    """-> whether these 100 bytes are a slot the game zeroed."""
    return bytes(raw) == EMPTY_PARTY_SLOT or bytes(raw) == bytes(PARTY_MON_SIZE)
PARTY_WRITE_STATUS = {
    PARTY_WRITE_NONE: "no party write was asked for",
    PARTY_WRITE_APPENDED: "APPENDED to the player's party, and the count was raised",
    PARTY_WRITE_FULL: "the party was already full - NOTHING was written",
    PARTY_WRITE_DRY_RUN: "DRY RUN - nothing was written; the 100 bytes are what is in that slot",
}

PARTY_APPEND_NO = 0
PARTY_APPEND_WRITE = 1
PARTY_APPEND_DRY_RUN = 2

# NUM_SPECIES [decomp:include/constants/species.h]; out of range indexes gLevelUpLearnsets, a table
# of pointers.
MAX_SPECIES = 411
MAX_LEVEL = 100
# fixedIV >= this rolls the IVs [USE_RANDOM_IVS, pokemon.h:232].
USE_RANDOM_IVS = 32
OT_ID_PLAYER_ID = 0                 # the id comes off the real save
OT_ID_PRESET = 1                    # fixedOtId is used verbatim
OT_ID_RANDOM_NO_SHINY = 2           # rolled until GET_SHINY_VALUE fails [pokemon.c:1783]
OT_ID_TYPES = (OT_ID_PLAYER_ID, OT_ID_PRESET, OT_ID_RANDOM_NO_SHINY)
SHINY_ODDS = 8                      # [decomp:include/constants/pokemon.h:185]


def shiny_value(ot_id, personality):
    """GET_SHINY_VALUE [decomp:include/pokemon.h:282]; below SHINY_ODDS is a shiny."""
    ot_id, personality = int(ot_id) & 0xFFFFFFFF, int(personality) & 0xFFFFFFFF
    return ((ot_id >> 16) ^ (ot_id & 0xFFFF)
            ^ (personality >> 16) ^ (personality & 0xFFFF))


def is_shiny(ot_id, personality):
    return shiny_value(ot_id, personality) < SHINY_ODDS


def shiny_personality(tid, sid, low=0):
    """A personality shiny for this trainer, with `low` as its bottom half; needs the secret id."""
    ot_id = (int(sid) << 16 | int(tid)) & 0xFFFFFFFF
    low = int(low) & 0xFFFF
    return (((ot_id >> 16) ^ (ot_id & 0xFFFF) ^ low) << 16 | low) & 0xFFFFFFFF


def build_create_mon(function, species, level, *, fixed_iv=USE_RANDOM_IVS,
                     has_fixed_personality=1, fixed_personality=0,
                     ot_id_type=OT_ID_PLAYER_ID, fixed_ot_id=0, destination=0,
                     party_append=False, party_base=None, party_count=None):
    """The create-mon payload. `function` 0 calls nothing and answers the zeroed buffer.

    `party_append` appends to gPlayerParty at slot == gPlayerPartyCount and raises the count, never
    the save block's party [decomp:src/load_save.c:160]; `destination` is an absolute address. Both
    are live writes, gated like an unsafe save-write."""
    from pokeldn.frlg.rom import rom_map
    party_base = rom_map.GPLAYER_PARTY if party_base is None else int(party_base)
    party_count = rom_map.GPLAYER_PARTY_COUNT if party_count is None else int(party_count)
    function, species, level = int(function), int(species), int(level)
    fixed_iv, ot_id_type = int(fixed_iv), int(ot_id_type)
    has_fixed_personality = int(has_fixed_personality)
    fixed_personality, fixed_ot_id = int(fixed_personality), int(fixed_ot_id)
    destination = int(destination)
    if party_append is True:
        party_append = PARTY_APPEND_WRITE
    elif party_append is False or party_append is None:
        party_append = PARTY_APPEND_NO
    party_append = int(party_append)
    if party_append not in (PARTY_APPEND_NO, PARTY_APPEND_WRITE, PARTY_APPEND_DRY_RUN):
        raise BufferScriptError(
            f"party_append is {PARTY_APPEND_NO} (no), {PARTY_APPEND_WRITE} (append) or "
            f"{PARTY_APPEND_DRY_RUN} (dry run), got {party_append}")
    if party_append:
        for name, address in (("gPlayerParty", party_base),
                              ("gPlayerPartyCount", party_count)):
            if not EWRAM_BASE <= address < EWRAM_BASE + EWRAM_SIZE:
                raise BufferScriptError(
                    f"{name} at 0x{address:X} is not in EWRAM; these are link-time globals "
                    f"[rom_map.py], not something to guess at")
        if not party_base + PARTY_SIZE * PARTY_MON_SIZE <= EWRAM_BASE + EWRAM_SIZE:
            raise BufferScriptError(
                f"gPlayerParty at 0x{party_base:X} does not have "
                f"{PARTY_SIZE * PARTY_MON_SIZE} bytes of EWRAM after it")
    if party_append and destination:
        raise BufferScriptError(
            "a party append computes its own destination from gSaveBlock1Ptr; an absolute address "
            "as well would be two answers to the same question")
    if party_append == PARTY_APPEND_WRITE and not function:
        raise BufferScriptError(
            "with no function to call the mon is a hundred zero bytes, and appending those would "
            "put a corrupt entry in the player's party")
    if function:
        if not function & 1:
            raise BufferScriptError(
                f"0x{function:X} is an ARM pointer; the ROM is THUMB, so a callable address has "
                "bit 0 set (the `bx` selects the state from it)")
        if not ROM_BASE <= function < SCAN_MAX_ADDRESS:
            raise BufferScriptError(
                f"0x{function:X} is not in the cartridge; calling it would run whatever is there")
    if not 0 < species <= MAX_SPECIES:
        raise BufferScriptError(
            f"species must be 1..{MAX_SPECIES}; CreateBoxMon indexes gLevelUpLearnsets, a table "
            f"of pointers, by it [decomp:src/pokemon.c:1861], so {species} is a dereference of "
            "whatever follows the table")
    if not 0 < level <= MAX_LEVEL:
        raise BufferScriptError(f"level must be 1..{MAX_LEVEL}, got {level}")
    if not 0 <= fixed_iv <= 0xFF:
        raise BufferScriptError(f"fixedIV is a u8, got {fixed_iv}")
    if ot_id_type not in OT_ID_TYPES:
        raise BufferScriptError(
            f"otIdType is {OT_ID_PLAYER_ID} (the player's own id), {OT_ID_PRESET} (fixedOtId) or "
            f"{OT_ID_RANDOM_NO_SHINY} (rolled until not shiny), got {ot_id_type}")
    if destination and not SCAN_MIN_ADDRESS <= destination <= SCAN_MAX_ADDRESS - PARTY_MON_SIZE:
        raise BufferScriptError(
            f"0x{destination:X} is not somewhere {PARTY_MON_SIZE} bytes can be written: "
            f"0x{SCAN_MIN_ADDRESS:X}..0x{SCAN_MAX_ADDRESS:X}")
    if ROM_BASE <= destination:
        raise BufferScriptError(
            f"0x{destination:X} is the cartridge, which is read-only; the copy would do nothing "
            "and the answer would look exactly as if it had worked")
    code = bytearray(payload(CREATE_MON))
    for offset, value in (
            (CREATE_MON_FUNCTION_OFFSET, function),
            (CREATE_MON_DESTINATION_OFFSET, destination),
            (CREATE_MON_PARTY_APPEND_OFFSET, party_append),
            (CREATE_MON_PARTY_BASE_OFFSET, party_base),
            (CREATE_MON_PARTY_COUNT_OFFSET, party_count),
            (CREATE_MON_SPECIES_OFFSET, species),
            (CREATE_MON_LEVEL_OFFSET, level),
            (CREATE_MON_FIXED_IV_OFFSET, fixed_iv),
            (CREATE_MON_HAS_FIXED_PERSONALITY_OFFSET, has_fixed_personality),
            (CREATE_MON_FIXED_PERSONALITY_OFFSET, fixed_personality),
            (CREATE_MON_OT_ID_TYPE_OFFSET, ot_id_type),
            (CREATE_MON_FIXED_OT_ID_OFFSET, fixed_ot_id)):
        code[offset:offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


def create_mon_parameters(code):
    """-> the eight arguments and the destination, read back out of a built payload."""
    code = bytes(code)
    def word(offset):
        return int.from_bytes(code[offset:offset + 4], "little")
    return {"function": word(CREATE_MON_FUNCTION_OFFSET),
            "destination": word(CREATE_MON_DESTINATION_OFFSET),
            "party_append": word(CREATE_MON_PARTY_APPEND_OFFSET),
            "party_base": word(CREATE_MON_PARTY_BASE_OFFSET),
            "party_count": word(CREATE_MON_PARTY_COUNT_OFFSET),
            "species": word(CREATE_MON_SPECIES_OFFSET),
            "level": word(CREATE_MON_LEVEL_OFFSET),
            "fixed_iv": word(CREATE_MON_FIXED_IV_OFFSET),
            "has_fixed_personality": word(CREATE_MON_HAS_FIXED_PERSONALITY_OFFSET),
            "fixed_personality": word(CREATE_MON_FIXED_PERSONALITY_OFFSET),
            "ot_id_type": word(CREATE_MON_OT_ID_TYPE_OFFSET),
            "fixed_ot_id": word(CREATE_MON_FIXED_OT_ID_OFFSET)}


def read_create_mon(dump):
    """-> what the call left; `party` is None for a pre-party-word answer."""
    dump = bytes(dump)
    body = CREATE_MON_HEADER_SIZE + PARTY_MON_SIZE
    if len(dump) < body:
        raise BufferScriptError(
            f"create-mon answers with {CREATE_MON_ANSWER_SIZE} bytes, got {len(dump)}")
    words = [int.from_bytes(dump[i:i + 4], "little")
             for i in range(0, CREATE_MON_HEADER_SIZE, 4)]
    calls, destination, function, built_at = words
    party = None
    if len(dump) >= body + 4:
        raw = int.from_bytes(dump[body:body + 4], "little")
        party = {"count_before": raw & 0xFF, "slot": (raw >> 8) & 0xFF,
                 "status": (raw >> 16) & 0xFF}
    return {"calls": calls, "destination": destination, "function": function,
            "built_at": built_at, "party": party,
            "mon": dump[CREATE_MON_HEADER_SIZE:body]}


def describe_create_mon(dump, expected=None):
    """The create-mon answer as log lines, the mon decoded and checked against `expected`
    (create_mon_parameters of the payload sent)."""
    from pokeldn.frlg.save import mon as monlib  # reads the decomp at import
    result = read_create_mon(dump)
    raw = result["mon"]
    party = result["party"]
    dry = bool(party and party["status"] == PARTY_WRITE_DRY_RUN)
    lines = [f"create-mon: {result['calls']} call(s), built at 0x{result['built_at']:08X}"
             + (f", calling 0x{result['function']:08X}" if result["function"]
                else ", calling nothing")
             + ((f", WOULD have written 0x{result['destination']:08X}" if dry else
                 f", written to 0x{result['destination']:08X}") if result["destination"] else "")]
    if party and party["status"] != PARTY_WRITE_NONE:
        lines.append(
            f"   party: {PARTY_WRITE_STATUS.get(party['status'], party['status'])}"
            f" - the console held {party['count_before']} mon(s)"
            + (f" and this one is slot {party['slot'] + 1} of {PARTY_SIZE}"
               if party["status"] == PARTY_WRITE_APPENDED else
               f", so a real run would write slot {party['slot'] + 1} of {PARTY_SIZE}"
               if party["status"] == PARTY_WRITE_DRY_RUN else ""))
    if party and party["status"] == PARTY_WRITE_DRY_RUN:
        slot = result["mon"]
        if is_empty_party_slot(slot):
            lines.append(
                "   the slot a real run would write is EMPTY exactly as ZeroMonData leaves one "
                "(every byte 0, mail 0xFF at offset 85) - nothing would be overwritten")
        else:
            live = [i for i, b in enumerate(slot) if b]
            lines.append(
                f"   the slot a real run would write HOLDS SOMETHING - {len(live)} non-zero "
                f"byte(s) at {live[:12]}{'...' if len(live) > 12 else ''} - DO NOT APPEND until "
                "this is understood")
        return lines
    if not result["function"]:
        lines.append("   nothing was called, so the 100 bytes are the buffer as it was sent")
        return lines
    info = monlib.decode_mon(raw)
    if info is None:
        return lines + ["   the answer is too short to decode as a struct Pokemon"]
    pid, ot_id = info["pid"], info["otid"]
    lines.append(f"   personality 0x{pid:08X}  otId 0x{ot_id:08X}  "
                 f"checksum {'VALID' if info['checksum_ok'] else 'WRONG'}"
                 + ("  SHINY" if is_shiny(ot_id, pid) else ""))
    lines.append(f"   species {info['species']} {info['species_name']}  Lv{info['level']}  "
                 f"nickname {info['nickname']!r}  OT {info['otName']!r}  "
                 f"moves {info['moves']}")
    ivs = create_mon_ivs(raw)
    if ivs is not None:
        lines.append(f"   IVs (HP ATK DEF SPE SPA SPD) {ivs}")
    lines.append("   stats (maxHP ATK DEF SPE SPA SPD) "
                 + str([int.from_bytes(raw[o:o + 2], "little")
                        for o in (0x58, 0x5A, 0x5C, 0x5E, 0x60, 0x62)]))
    if expected:
        lines.extend("   " + line for line in check_create_mon(raw, expected))
    return lines


def create_mon_substructs(raw):
    """The decrypted, unshuffled 48 bytes as {G,A,E,M}."""
    from pokeldn.frlg.save import mon as monlib
    raw = bytes(raw)
    if len(raw) < monlib.BOX_SIZE:
        return None
    pid = int.from_bytes(raw[0:4], "little")
    key = pid ^ int.from_bytes(raw[4:8], "little")
    sec = bytearray(raw[32:80])
    for i in range(12):
        value = int.from_bytes(sec[i * 4:i * 4 + 4], "little") ^ key
        sec[i * 4:i * 4 + 4] = (value & 0xFFFFFFFF).to_bytes(4, "little")
    order = monlib.SUBSTRUCT_ORDER[pid % 24]
    return {k: bytes(sec[order.index(k) * 12:][:12]) for k in "GAEM"}


def create_mon_ivs(raw):
    """-> [HP, ATK, DEF, SPE, SPA, SPD], or None if the 100 bytes are not there."""
    subs = create_mon_substructs(raw)
    if subs is None:
        return None
    word = int.from_bytes(subs["M"][4:8], "little")
    return [(word >> (5 * i)) & 31 for i in range(6)]


def check_create_mon(raw, expected):
    """-> lines saying, field by field, whether the eight arguments reached the ROM."""
    from pokeldn.frlg.save import mon as monlib
    raw = bytes(raw)
    info = monlib.decode_mon(raw)
    lines = []
    if info is None:
        return ["the answer is too short to check"]
    def verdict(name, want, got):
        lines.append(f"{name}: asked {want}, got {got}"
                     + ("  OK" if want == got else "  <<< MISMATCH"))
    verdict("species", expected["species"], info["species"])
    verdict("level", expected["level"], info["level"])
    if expected["has_fixed_personality"]:
        verdict("personality", f"0x{expected['fixed_personality']:08X}", f"0x{info['pid']:08X}")
    if expected["ot_id_type"] == OT_ID_PRESET:
        verdict("otId", f"0x{expected['fixed_ot_id']:08X}", f"0x{info['otid']:08X}")
    if expected["fixed_iv"] < USE_RANDOM_IVS:
        ivs = create_mon_ivs(raw)
        verdict("IVs", [expected["fixed_iv"]] * 6, ivs)
    lines.append("checksum: " + ("VALID - the ROM encrypted it with its own key"
                                 if info["checksum_ok"] else
                                 "WRONG - these 100 bytes are not a mon the ROM built"))
    return lines


SCRIPT_REGISTRY = {
    TRAINER_ID_PROBE: BufferScriptSpec(
        TRAINER_ID_PROBE,
        "read playerTrainerId out of gSaveBlock2Ptr and return it (reads only, writes nothing)",
        EXPECT_TRAINER_ID),
    SAVE_DUMP: BufferScriptSpec(
        SAVE_DUMP,
        "read out any part of either save block, using the pointers the console hands us - no "
        "absolute address needed (reads only, writes nothing)",
        None),
    MEMORY_DUMP: BufferScriptSpec(
        MEMORY_DUMP,
        "read out any region of the console's memory by repointing the console's own outgoing "
        "message at it (needs --dump-address; reads only, writes nothing)",
        None),
    MEMORY_DUMP_MULTI: BufferScriptSpec(
        MEMORY_DUMP_MULTI,
        "the same, but SEVERAL consecutive blocks in one session (--dump-address --dump-blocks N): "
        "the client script runs the payload once per block and each pass sends the next kilobyte",
        None),
    MEMORY_DUMP_SCATTER: BufferScriptSpec(
        MEMORY_DUMP_SCATTER,
        "the same, but the blocks are UNRELATED addresses (--dump-scatter A,B,C): the payload "
        "carries a table of bases and the cursor indexes it, so one session reads the sixteen "
        "kilobytes a plan actually asked for rather than sixteen consecutive ones",
        None),
    SAVE_WRITE: BufferScriptSpec(
        SAVE_WRITE,
        "write bytes into a save block and read the same region back in the same run; the console "
        "saves afterwards, so the write reaches flash (--write-hex, --dump-block, --dump-offset)",
        None),
    RNG_TRACE: BufferScriptSpec(
        RNG_TRACE,
        "sample one word of memory once a frame, optionally calling a ROM function between the two "
        "halves of each sample, and check the LCG recurrence on what comes back (--trace-address, "
        "--trace-call, --trace-samples; reads only, plus whatever the callee does)",
        None),
    MEMORY_SCAN: BufferScriptSpec(
        MEMORY_SCAN,
        "search memory for a 32-bit value and send back where it is; it returns 0 to be called again "
        "next frame, so one run covers a range no dump could (--scan-word, --scan-start, "
        "--scan-end, --scan-blocks; reads only, writes nothing)",
        None),
    TABLE_SCAN: BufferScriptSpec(
        TABLE_SCAN,
        "search memory for a table by its shape, a run of N words each exactly D above the one before "
        "it, and send back where each run starts and what value it starts with; this is how a table "
        "of pointers is found when no constant in it is known (--table-delta, --table-runlen, "
        "--table-start, --table-end, --table-blocks; reads only, writes nothing)",
        None),
    ROM_CHECKSUM: BufferScriptSpec(
        ROM_CHECKSUM,
        "checksum a range of memory in up to 128 blocks and send back one sum per block; the host "
        "sets them beside the same sums over a ROM image and names the blocks that differ "
        "(--sum-start, --sum-end, --sum-block, --sum-budget, --sum-reference; reads only, writes "
        "nothing)",
        None),
    ANCHORS: BufferScriptSpec(
        ANCHORS,
        "ask the machine where it is: our own load address, the return address into ROM, the stack "
        "and the client's five buffers (writes only its own outgoing buffer)",
        None),
    CREATE_MON: BufferScriptSpec(
        CREATE_MON,
        "call CreateMon, a ROM function taking eight arguments, and send back the 100-byte struct "
        "Pokemon it built; the mon is built inside our own image, so nothing on the console is "
        "written unless --create-mon-append or --create-mon-destination asks for it "
        "(--create-mon-call, --create-mon-species, --create-mon-level, --create-mon-personality)",
        None),
    STRING_GATHER: BufferScriptSpec(
        STRING_GATHER,
        "follow an array of pointers and send back the strings themselves, back to back, instead of "
        "a window of mostly-pointers: a whole Easy Chat group in one run (--gather-address, "
        "--gather-count, --gather-stride; reads only, writes nothing)",
        None),
    CALL: BufferScriptSpec(
        CALL,
        "call any ROM function with arguments we choose, up to eight words in r0..r3 then the stack, "
        "and send back its r0 with one address read either side of the call (--call-address, "
        "--call-arg, --call-watch); the payload writes nothing itself, but the callee may, so the "
        "address has to have been read as code first",
        None),
    FLASH_READ: BufferScriptSpec(
        FLASH_READ,
        "select the flash bank, byte-copy a save sector out of the 64 KiB window into EWRAM with "
        "the CPU, and send the COPY: the console's outgoing message cannot be pointed at flash "
        "itself (--flash-sector, --flash-read-offset, --dump-size; reads only, writes nothing)",
        None),
    FLASH_PATCH: BufferScriptSpec(
        FLASH_PATCH,
        "read a save sector out of flash through the banked window, change one field, "
        "recompute the checksum and write it back with swi 0x48, then bump the counter-bearing "
        "sector so the loader adopts the band. Nothing is rebuilt from RAM, so a field the save "
        "routine serializes cannot be lost (--flash-id, --flash-patch-offset, --flash-patch-hex; "
        "needs --write-unsafe)",
        None),
    FLASH_WRITE: BufferScriptSpec(
        FLASH_WRITE,
        "compose 4 KB in EWRAM on the console and write it straight into a flash sector with "
        "swi 0x48, bypassing the game's save code entirely - no counter, checksum or signature "
        "(--flash-sector, --flash-fill-base, --flash-fill-step, --flash-words; a sector inside "
        "the save bands needs --write-unsafe)",
        None),
    CALL_CHAIN: BufferScriptSpec(
        CALL_CHAIN,
        "run a LIST of ROM calls and memory accesses in one frame and send back a word for each, "
        "any step able to use the previous step's result as its address - which is how a function "
        "that returns a pointer (GetVarPointer) becomes a write (--chain-step, repeatable; a write "
        "step needs --write-unsafe)",
        None),
    SLOOP_SVC: BufferScriptSpec(
        SLOOP_SVC,
        "issue one Sloop syscall (swi 0x40..0x62) with r0..r3 we choose, optionally pointing r0 or "
        "r1 at up to 256 bytes we send, and send back the registers and the bytes as the syscall "
        "left them (--svc-number, --svc-arg, --svc-text/--svc-hex, --svc-data-in; a number outside "
        "the read-only set needs --write-unsafe)",
        None),
    INSTALL_RESIDENT: BufferScriptSpec(
        INSTALL_RESIDENT,
        "copy a resident hook into the top of EWRAM and install it in gIntrTable[4], where it runs "
        "every frame until a soft reset; answers with the V-blank handler it found "
        "(--resident turbo, --resident-param extra=N field=N battle=N hold=0x100 budget=228; needs --write-unsafe)",
        None),
    INSTALL_KEPT: BufferScriptSpec(
        INSTALL_KEPT,
        "install the resident hook kept in the save's filler_B20 (written by save-write --resident), "
        "after checking its sum; answers with the V-blank handler it found, 0xBAD0BAD0 when nothing "
        "was installed",
        None),
}


def build_save_dump(block=SAVE_BLOCK_2, offset=0, size=MAX_BUFFER_SCRIPT_SIZE):
    """The save-dump payload, reading `size` bytes at `offset` of one save block through the
    pointers Client_RunBufferScript passes [decomp:src/mystery_gift_client.c:276]."""
    if block not in SAVE_BLOCKS:
        raise BufferScriptError(f"block is one of {SAVE_BLOCKS}, got {block!r}")
    offset, size = int(offset), int(size)
    if not 0 < size <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a dump is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes (MG_LINK_BUFFER_SIZE), got {size}")
    if offset < 0 or offset % 2:
        raise BufferScriptError(f"offset {offset} must be positive and halfword aligned")
    code = bytearray(payload(SAVE_DUMP))
    code[SAVE_DUMP_WHICH_OFFSET:SAVE_DUMP_WHICH_OFFSET + 4] = (
        (0 if block == SAVE_BLOCK_2 else 1).to_bytes(4, "little"))
    code[SAVE_DUMP_OFFSET_OFFSET:SAVE_DUMP_OFFSET_OFFSET + 4] = offset.to_bytes(4, "little")
    code[SAVE_DUMP_SIZE_OFFSET:SAVE_DUMP_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
    return bytes(code)


def scratch_regions(block):
    """-> the (offset, length) spans of that block the game never reads."""
    return SAVE_SCRATCH.get(block, ())


def is_scratch(block, offset, size):
    return any(start <= offset and offset + size <= start + length
               for start, length in scratch_regions(block))


def build_save_write(data, block=SAVE_BLOCK_2, offset=0xB20, *, unsafe=False):
    """The save-write payload. Refuses anything outside the scratch regions unless `unsafe`: this is
    the player's live save and the console commits it to flash."""
    if block not in SAVE_BLOCKS:
        raise BufferScriptError(f"block is one of {SAVE_BLOCKS}, got {block!r}")
    data = bytes(data)
    offset = int(offset)
    if not 0 < len(data) <= MAX_SAVE_WRITE_BYTES:
        raise BufferScriptError(
            f"a save write carries 1..{MAX_SAVE_WRITE_BYTES} bytes of data (the payload itself "
            f"takes the first {SAVE_WRITE_DATA_OFFSET}), got {len(data)}")
    if offset < 0 or offset % 2:
        raise BufferScriptError(f"offset {offset} must be positive and halfword aligned")
    if not unsafe and not is_scratch(block, offset, len(data)):
        spans = ", ".join(f"0x{start:X}..0x{start + length:X}"
                          for start, length in scratch_regions(block)) or "nothing"
        raise BufferScriptError(
            f"writing {len(data)} bytes at {block} 0x{offset:X} touches a field the game reads. "
            f"The scratch region of {block} is {spans} (struct SaveBlock2's u8 filler[], never "
            f"referenced in src/). Pass unsafe=True only if you mean to edit a live field.")
    code = bytearray(payload(SAVE_WRITE))
    code[SAVE_WRITE_WHICH_OFFSET:SAVE_WRITE_WHICH_OFFSET + 4] = (
        (0 if block == SAVE_BLOCK_2 else 1).to_bytes(4, "little"))
    code[SAVE_WRITE_OFFSET_OFFSET:SAVE_WRITE_OFFSET_OFFSET + 4] = offset.to_bytes(4, "little")
    code[SAVE_WRITE_SIZE_OFFSET:SAVE_WRITE_SIZE_OFFSET + 4] = len(data).to_bytes(4, "little")
    code[SAVE_WRITE_DATA_OFFSET:] = data.ljust((len(data) + 3) & ~3, b"\x00")
    return bytes(code)


# asm/flash-write.s's image; offsets fixed by construction.
FLASH_WRITE_SECTOR_OFFSET = 0x04
FLASH_WRITE_SOURCE_OFFSET = 0x08
FLASH_WRITE_FILL_BASE_OFFSET = 0x0C
FLASH_WRITE_FILL_STEP_OFFSET = 0x10
FLASH_WRITE_WORDS_OFFSET = 0x14
FLASH_WRITE_FOOTER_OFFSET = 0x18
FLASH_WRITE_ID_OFFSET = 0x1C
FLASH_WRITE_COUNTER_OFFSET = 0x20
FLASH_WRITE_SIGNATURE_OFFSET = 0x24
FLASH_WRITE_DERIVE_LWS_OFFSET = 0x28
FLASH_WRITE_DERIVE_SC_OFFSET = 0x2C
FLASH_WRITE_BIAS_OFFSET = 0x30
FLASH_WRITE_PHYS_RESULT_OFFSET = 0x40
FLASH_WRITE_ID_RESULT_OFFSET = 0x44
FLASH_WRITE_POSITION_OFFSET = 0x48
FLASH_WRITE_THUNK_OFFSET = 0x4C
# Save globals in IWRAM, French build; the builders patch the build's own [builds.py].
GLASTWRITTENSECTOR = 0x030045A0
GLASTSAVECOUNTER = 0x030045A4
GLASTKNOWNGOODSECTOR = 0x030045A8
GDAMAGEDSAVESECTORS = 0x030045AC
GSAVECOUNTER = 0x030045B0
SECTORS_PER_BAND = 14
# flash-write/flash-patch refusals, nothing written: gLastWrittenSector past 13, gSaveCounter 0, or
# sector A carrying another id.
FLASH_REFUSED_LWS = 0xBAE00000
FLASH_REFUSED_SC = 0xBAE10000
FLASH_REFUSED_ID = 0xBAE20000


def flash_refusal(status):
    """-> why a derived flash payload wrote nothing, or None if `status` is not a refusal."""
    mark, low = status & 0xFFFF0000, status & 0xFFFF
    if mark == FLASH_REFUSED_LWS:
        return (f"refused, nothing written: gLastWrittenSector read {low}, not a band position "
                "0..13; the payload was built for another cartridge")
    if mark == FLASH_REFUSED_SC:
        return ("refused, nothing written: gSaveCounter read 0, which no saved game holds; the "
                "payload was built for another cartridge")
    if mark == FLASH_REFUSED_ID:
        return (f"refused, nothing written: sector {low >> 8} carries id {low & 0xFF}, not the "
                "one the rotation named")
    return None


# The last band position supplies the slot's counter to GetSaveValidStatus.
COUNTER_BEARING_POSITION = SECTORS_PER_BAND - 1
# struct SaveSector [decomp:include/save.h]: data[3968], unused[116], then the footer.
SECTOR_DATA_SIZE = 3968
SECTOR_FOOTER_AT = 0xFF4
SECTOR_SIGNATURE = 0x08012025
SECTOR_DATA_WORDS = SECTOR_DATA_SIZE // 4
# Bytes each sector id checksums, from sSaveSlotLayout at 0x083F58C4 [decomp:src/save.c:43]. Trap: a
# real save zero-fills past the chunk, so summing all 3968 bytes agrees there and fails on a
# composed sector. docs/frlg_rom.md.
SECTOR_CHUNK_SIZES = {0: 3876, 1: 3968, 2: 3968, 3: 3968, 4: 3816, 5: 3968, 6: 3968,
                      7: 3968, 8: 3968, 9: 3968, 10: 3968, 11: 3968, 12: 3968, 13: 2000}
SAVE_SLOT_LAYOUT_ADDRESS = 0x083F58C4
# A pattern stopping here, zero after, checksums the same under every id's chunk size: composable
# when the id is decided on the console.
SECTOR_CHUNK_MIN = 2000


def sector_chunk_size(sector_id):
    """-> how many bytes of sector `sector_id` the game's checksum covers."""
    try:
        return SECTOR_CHUNK_SIZES[int(sector_id)]
    except KeyError:
        raise BufferScriptError(
            f"sector id {sector_id} is not one of the {len(SECTOR_CHUNK_SIZES)} a save slot "
            "carries") from None
# Scratch for the fill: 0x400 above the payload's own image.
FLASH_WRITE_SCRATCH = GDECOMPRESSION_BUFFER + 0x400
FLASH_WRITE_WORDS = FLASH_SECTOR_SIZE // 4
# Sectors 0..27 are the two save bands; 28..31 (Hall of Fame, Trainer Tower) sit outside
# [decomp:include/save.h].
SAVE_BAND_SECTORS = 28


def build_flash_write(sector, *, source=FLASH_WRITE_SCRATCH, fill_base=0x46570000, fill_step=1,
                      words=FLASH_WRITE_WORDS, number=SWI_WRITE_SECTOR, unsafe=False,
                      footer=False, sector_id=0, counter=0, signature=SECTOR_SIGNATURE,
                      derive=False, counter_bias=0, position=None, build=None):
    """The flash-write payload: fill `words` words at `source`, then swi `number` into `sector`,
    bypassing the game's save code. Refuses a save-band sector unless `unsafe`. `derive` reads
    `build`'s save globals."""
    build = builds.resolve(build)
    sector = int(sector)
    if not 0 <= sector < FLASH_SIZE // FLASH_SECTOR_SIZE:
        raise BufferScriptError(
            f"a flash sector is 0..{FLASH_SIZE // FLASH_SECTOR_SIZE - 1}, got {sector}")
    if not unsafe and not derive and sector < SAVE_BAND_SECTORS:
        raise BufferScriptError(
            f"sector {sector} is inside a save band (0..{SAVE_BAND_SECTORS - 1}), so the write "
            "lands on a live save block with no counter, checksum or signature maintained. "
            f"Sectors {SAVE_BAND_SECTORS}..{FLASH_SIZE // FLASH_SECTOR_SIZE - 1} are outside both "
            "bands. Pass unsafe=True only if damaging the save is the experiment.")
    if number not in (SWI_WRITE_SECTOR, SWI_REPLACE_SECTOR):
        raise BufferScriptError(
            f"the sector syscalls are 0x{SWI_WRITE_SECTOR:02X} and 0x{SWI_REPLACE_SECTOR:02X}, "
            f"got 0x{number:02X}")
    if number == SWI_REPLACE_SECTOR and not unsafe:
        raise BufferScriptError(
            f"swi 0x{SWI_REPLACE_SECTOR:02X} voids the destination's signature at +0xFF8 and "
            "aborts outright if the destination is rejected. Pass unsafe=True to mean it.")
    words = int(words)
    if footer and words == FLASH_WRITE_WORDS:
        # Fill the id's own chunk and leave the rest zero, as the game does; a full fill would fail
        # the game's chunk checksum.
        words = (sector_chunk_size(sector_id) if position is None
                 else SECTOR_CHUNK_MIN) // 4
    if not 1 <= words <= FLASH_WRITE_WORDS:
        raise BufferScriptError(
            f"the source is one sector, 1..{FLASH_WRITE_WORDS} words, got {words}")
    if footer and words > SECTOR_DATA_WORDS:
        raise BufferScriptError(
            f"a composed sector's pattern fills the data area, 1..{SECTOR_DATA_WORDS} words, "
            f"got {words}; the rest is zeroed and the footer follows")
    if not footer and (sector_id or counter):
        raise BufferScriptError("an id and a counter are only meaningful with footer=True")
    if position is not None:
        if not derive:
            raise BufferScriptError(
                "aiming at a band position means deriving the id from it, which needs derive=True")
        if not 0 <= position < SECTORS_PER_BAND:
            raise BufferScriptError(
                f"a band position is 0..{SECTORS_PER_BAND - 1}, got {position}")
        if sector_id:
            raise BufferScriptError(
                "a position derives the id on the console, so an explicit id would be ignored")
    if derive:
        if not footer:
            raise BufferScriptError(
                "deriving the position only makes sense for a composed sector: the id is what the "
                "rotation is computed from")
        if position is None and not 0 <= sector_id < SECTORS_PER_BAND:
            raise BufferScriptError(
                f"a derived position needs a real save id, 0..{SECTORS_PER_BAND - 1}, "
                f"got {sector_id}")
        if counter:
            raise BufferScriptError(
                "a derived write takes its counter from gSaveCounter plus counter_bias, so an "
                "explicit counter would be ignored")
        if not unsafe:
            raise BufferScriptError(
                "a derived write lands inside a save band by construction, on the sector the id "
                "actually occupies. Pass unsafe=True to mean it.")
    elif counter_bias:
        raise BufferScriptError("counter_bias only applies to a derived write")
    source = int(source)
    if source % 4:
        raise BufferScriptError(f"the source 0x{source:X} must be word aligned")
    if not (EWRAM_BASE <= source and source + FLASH_SECTOR_SIZE <= EWRAM_BASE + EWRAM_SIZE):
        raise BufferScriptError(
            f"the source 0x{source:X} plus a sector must lie inside EWRAM "
            f"(0x{EWRAM_BASE:X}..0x{EWRAM_BASE + EWRAM_SIZE:X})")
    code = bytearray(payload(FLASH_WRITE))
    if source < GDECOMPRESSION_BUFFER + len(code):
        raise BufferScriptError(
            f"the source 0x{source:X} overlaps the payload's own image at "
            f"0x{GDECOMPRESSION_BUFFER:X}..0x{GDECOMPRESSION_BUFFER + len(code):X}")
    for offset, value in ((FLASH_WRITE_SECTOR_OFFSET, sector),
                          (FLASH_WRITE_SOURCE_OFFSET, source),
                          (FLASH_WRITE_FILL_BASE_OFFSET, fill_base),
                          (FLASH_WRITE_FILL_STEP_OFFSET, fill_step),
                          (FLASH_WRITE_WORDS_OFFSET, words),
                          (FLASH_WRITE_FOOTER_OFFSET, 1 if footer else 0),
                          (FLASH_WRITE_ID_OFFSET, sector_id),
                          (FLASH_WRITE_COUNTER_OFFSET, counter),
                          (FLASH_WRITE_SIGNATURE_OFFSET, signature if footer else 0),
                          (FLASH_WRITE_DERIVE_LWS_OFFSET,
                           build.last_written_sector if derive else 0),
                          (FLASH_WRITE_DERIVE_SC_OFFSET, build.save_counter if derive else 0),
                          (FLASH_WRITE_BIAS_OFFSET, counter_bias),
                          (FLASH_WRITE_POSITION_OFFSET,
                           0xFFFFFFFF if position is None else position)):
        code[offset:offset + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    # The thunk is THUMB `swi N ; bx lr`; N is the first byte.
    code[FLASH_WRITE_THUNK_OFFSET] = int(number) & 0xFF
    return bytes(code)


def sector_checksum(data, size=SECTOR_DATA_SIZE):
    """CalculateChecksum [decomp:src/save.c] over `size` bytes. Pass the id's own
    chunk size (`sector_chunk_size`) when data past the chunk might be non-zero."""
    total = 0
    for i in range(int(size) // 4):
        total = (total + int.from_bytes(data[i * 4:i * 4 + 4], "little")) & 0xFFFFFFFF
    return ((total >> 16) + total) & 0xFFFF


# asm/flash-patch.s's image, offsets from _start.
FLASH_PATCH_SCRATCH_OFFSET = 0x04
FLASH_PATCH_LWS_OFFSET = 0x08
FLASH_PATCH_SC_OFFSET = 0x0C
FLASH_PATCH_ID_OFFSET = 0x10
FLASH_PATCH_OFF_OFFSET = 0x14
FLASH_PATCH_LEN_OFFSET = 0x18
FLASH_PATCH_CHUNK_OFFSET = 0x1C
FLASH_PATCH_BIAS_OFFSET = 0x20
FLASH_PATCH_SIG_OFFSET = 0x24
FLASH_PATCH_DATA_OFFSET = 0x38
FLASH_PATCH_MAX_BYTES = 16
FLASH_PATCH_BAD_MARK = 0xBAD00000


# asm/flash-read.s's image.
FLASH_READ_BANK_OFFSET = 0x04
FLASH_READ_WINDOW_OFFSET = 0x08
FLASH_READ_LENGTH_OFFSET = 0x0C
FLASH_READ_SCRATCH_OFFSET = 0x10
# The 64 KiB flash aperture; a 1 Mbit chip is two banks. A wrong-bank address aliases rather than
# faulting.
FLASH_WINDOW_BASE = 0x0E000000
FLASH_WINDOW_SIZE = 0x10000
FLASH_SECTORS_PER_BANK = FLASH_WINDOW_SIZE // FLASH_SECTOR_SIZE


def flash_window_address(sector):
    """-> (bank, window address) for a physical sector [decomp:src/agb_flash.c ReadFlash]."""
    sector = int(sector)
    if not 0 <= sector < FLASH_SIZE // FLASH_SECTOR_SIZE:
        raise BufferScriptError(f"a flash sector is 0..{FLASH_SIZE // FLASH_SECTOR_SIZE - 1}")
    return (sector // FLASH_SECTORS_PER_BANK,
            FLASH_WINDOW_BASE + (sector % FLASH_SECTORS_PER_BANK) * FLASH_SECTOR_SIZE)


def build_flash_read(sector, *, offset=0, length=252, scratch=FLASH_WRITE_SCRATCH):
    """The flash-read payload: select the bank, byte-copy the window into EWRAM, send the copy.
    The send cannot be pointed at flash itself (measured)."""
    bank, window = flash_window_address(sector)
    offset, length = int(offset), int(length)
    if not 0 <= offset < FLASH_SECTOR_SIZE:
        raise BufferScriptError(f"an offset into a sector is 0..{FLASH_SECTOR_SIZE - 1}")
    if not 1 <= length <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(f"a read is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes, got {length}")
    if window + offset + length > FLASH_WINDOW_BASE + FLASH_WINDOW_SIZE:
        raise BufferScriptError(
            f"sector {sector} at +{offset:#x} for {length} bytes runs past the 64 KiB window; the "
            "read would alias to the start of the window and return another sector")
    code = bytearray(payload(FLASH_READ))
    for at, value in ((FLASH_READ_BANK_OFFSET, bank),
                      (FLASH_READ_WINDOW_OFFSET, window + offset),
                      (FLASH_READ_LENGTH_OFFSET, length),
                      (FLASH_READ_SCRATCH_OFFSET, scratch)):
        code[at:at + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(code)


# sloop-svc: up to eight Sloop syscalls [asm/sloop-svc.s, docs/frlg_rom.md, Calling the wrapper].
SLOOP_FLAGS_OFFSET = 0x04
SLOOP_REGS_OFFSET = 0x08
SLOOP_SCRATCH_OFFSET = 0x18
SLOOP_LENGTH_OFFSET = 0x1C
SLOOP_THUNK_OFFSET = 0x20
SLOOP_COUNT_OFFSET = 0x24
SLOOP_NUMBERS_OFFSET = 0x28
SLOOP_DATA_OFFSET = 0x30
SLOOP_DATA_MAX = 256
SLOOP_MAX_CALLS = 8
SLOOP_R0_IS_DATA, SLOOP_R1_IS_DATA = 1, 2
SLOOP_REACHED, SLOOP_RETURNED = 0x53565331, 0x53565332
SLOOP_RECORD_SIZE = 20
SLOOP_HEADER_SIZE = 0x10 + SLOOP_MAX_CALLS * SLOOP_RECORD_SIZE      # where the data comes back
# [decomp:src/sloopsvc.c:194] r0 = an ASCII string, r1 = 0.
SWI_BAD_WORD_CHECK = 0x4D
# Filled bkpt hook slots: 0x52 the librfu patches, 0xFF quits the application [docs/frlg_rom.md].
SLOOP_BKPT_RFU, SLOOP_BKPT_APP = 0x52, 0xFF
# From the wrapper's jump table [main+0x17D7F6]: safe with any operands. The rest take a pointer or
# change link, save or telemetry state and need --write-unsafe.
SLOOP_SAFE_NUMBERS = frozenset({0x46, 0x49, 0x4A, 0x4B, 0x4D, 0x4E, 0x50, 0x51, 0x52, 0x53,
                                0x54, 0x58, 0x59, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60})
# Never: flash-write owns sector writes; 0x55 (SaveBlock2 pointer) and 0x4C (finished save) outlive
# the session.
SLOOP_REFUSED_NUMBERS = frozenset({SWI_WRITE_SECTOR, SWI_REPLACE_SECTOR, 0x4C, 0x55})


def _check_sloop_number(number, *, flags, unsafe, bkpt):
    if bkpt:
        if number == SLOOP_BKPT_RFU:
            raise BufferScriptError(
                "bkpt #0x52 from any other address re-keys the wrapper's second RFU hook to it "
                "[main+0x3e8d0], which outlives the session")
        if not 0 <= number <= 0xFF or not unsafe:
            raise BufferScriptError("a bkpt is 0..0xFF and needs --write-unsafe")
        return
    if not 0x40 <= number <= 0x62:
        raise BufferScriptError(
            f"swi 0x{number:02X} is not a Sloop syscall; the wrapper dispatches 0x40..0x62 and "
            "below 0x2B is the BIOS")
    if number in SLOOP_REFUSED_NUMBERS:
        raise BufferScriptError(
            f"swi 0x{number:02X} writes the save or re-points SaveBlock2; flash-write is the "
            "payload for sectors and nothing here needs the other two")
    if number not in SLOOP_SAFE_NUMBERS and not unsafe:
        raise BufferScriptError(
            f"swi 0x{number:02X} takes a pointer or changes link or telemetry state; "
            "pass --write-unsafe to issue it")
    if number == SWI_BAD_WORD_CHECK and not flags & SLOOP_R0_IS_DATA and not unsafe:
        raise BufferScriptError(
            "swi 0x4D rewrites the string r0 points at, 256 bytes of it; point r0 at the copy "
            "(--svc-data-in r0) or pass --write-unsafe")


def build_sloop_svc(numbers, args=(), data=b"", *, flags=0, scratch=FLASH_WRITE_SCRATCH,
                    unsafe=False, bkpt=False):
    """The sloop-svc payload: `swi N` for each of `numbers` with r0..r3 = `args`, `data` re-copied
    before each call (`flags` bit 0/1 points r0/r1 at it). With `bkpt` the thunk is `bkpt N`, the
    wrapper's hook table at cpu+0x170."""
    numbers = [int(numbers)] if isinstance(numbers, int) else [int(n) for n in numbers]
    if not 1 <= len(numbers) <= SLOOP_MAX_CALLS:
        raise BufferScriptError(f"1..{SLOOP_MAX_CALLS} numbers per session, got {len(numbers)}")
    if flags & ~(SLOOP_R0_IS_DATA | SLOOP_R1_IS_DATA):
        raise BufferScriptError(f"flags are bits 0 and 1, got {flags:#x}")
    for number in numbers:
        _check_sloop_number(number, flags=flags, unsafe=unsafe, bkpt=bkpt)
    args = [int(a) & 0xFFFFFFFF for a in args]
    if len(args) > 4:
        raise BufferScriptError(f"a syscall takes r0..r3, got {len(args)} words")
    data = bytes(data)
    if len(data) > SLOOP_DATA_MAX:
        raise BufferScriptError(f"at most {SLOOP_DATA_MAX} bytes of data, got {len(data)}")
    code = bytearray(payload(SLOOP_SVC))

    def put(at, value):
        code[at:at + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    put(SLOOP_FLAGS_OFFSET, flags)
    for index, value in enumerate(args + [0] * (4 - len(args))):
        put(SLOOP_REGS_OFFSET + 4 * index, value)
    put(SLOOP_SCRATCH_OFFSET, scratch)
    put(SLOOP_LENGTH_OFFSET, len(data))
    if bkpt:
        code[SLOOP_THUNK_OFFSET + 1] = 0xBE
    put(SLOOP_COUNT_OFFSET, len(numbers))
    code[SLOOP_NUMBERS_OFFSET:SLOOP_NUMBERS_OFFSET + len(numbers)] = bytes(numbers)
    code[SLOOP_DATA_OFFSET:SLOOP_DATA_OFFSET + len(data)] = data
    return bytes(code)


def sloop_svc_answer_size(data_length):
    return SLOOP_HEADER_SIZE + data_length + 1


def parse_sloop_svc(answer):
    """-> dict(returned, calls=[(number, (r0, r1, r2, r3))], data) from a sloop-svc result block."""
    answer = bytes(answer)
    if len(answer) < SLOOP_HEADER_SIZE:
        raise BufferScriptError(f"a sloop-svc answer is at least {SLOOP_HEADER_SIZE} bytes")

    def word(at):
        return int.from_bytes(answer[at:at + 4], "little")
    if word(0) != SLOOP_REACHED:
        raise BufferScriptError(f"no reached marker: 0x{word(0):08X}")
    count, length = min(word(4), SLOOP_MAX_CALLS), word(12)
    calls = []
    for index in range(count):
        at = 0x10 + SLOOP_RECORD_SIZE * index
        thunk = word(at)
        if not thunk:
            break
        calls.append((thunk & 0xFF, tuple(word(at + 4 + 4 * r) for r in range(4))))
    return {"returned": word(8) == SLOOP_RETURNED, "calls": calls,
            "data": answer[SLOOP_HEADER_SIZE:SLOOP_HEADER_SIZE + length]}


# install-resident [asm/install-resident.s, docs/frlg_rom.md, Code that outlives the session].
INSTALL_DEST_OFFSET = 0x04
INSTALL_LENGTH_OFFSET = 0x08
INSTALL_TABLE_OFFSET = 0x0C
INSTALL_ENTRY_OFFSET = 0x10
INSTALL_ORIGINAL_OFFSET = 0x14
INSTALL_BLOB_OFFSET = 0x18
# Entry symbol and tunable parameters per hook.
RESIDENT_HOOKS = {
    "turbo": ("turbo_hook", {"extra": 4, "field": 0, "battle": 0, "overlay": 0, "hold": 0,
                             "help": 0, "budget": 0, "ring": 0,
                             "watch": 0x02024028, "frames": 0x0203FF60}),
    # turbo with no overlay and no RNG history [asm/resident/turbo-lite.s]
    "turbo-lite": ("turbo_hook", {"extra": 4, "field": 0, "battle": 0, "hold": 0, "help": 0, "budget": 0,
                                  "frames": 0x0203FF60}),
    "shiny": ("shiny_hook", {"method": 0, "offset": 4, "search": 16, "slow": 0x100,
                             "slow_frames": 3, "help": 0x0203F171, "state": 0x0203FF80,
                             "overlay": 0x0203FF98}),
    "ivs": ("ivs_hook", {"mon": 0x02024280, "words": 0x0203FF80, "overlay": 0x0203FF80,
                         "overlay2": 0x0203FF84}),
    "noencounter": ("noencounter_hook", {"flag": 0x020386D8}),
    "noclip": ("noclip_hook", {"hold": 0x100, "help": 0x0203F171, "state": 0x0203FF80}),
    "follower": ("follower_hook", {"state": 0x0203FFDC, "images": 0x0203FBB4, "deoxys": None}),
}
# A hook's IWRAM and ROM words are the build's [Build.hook_literals]. RESIDENT_DATA: the data a hook
# keeps past its code, in bytes.
RESIDENT_DATA = {"p_frames": 20, "p_ring": 140, "p_state": 36, "p_words": 12, "p_images": 72}
# Above the highest EWRAM symbol's end, 0x0203FBAC, and below the kept handler at 0x0203FBFC.
RESIDENT_DATA_FLOOR = 0x0203FBB4
# The follower's line when A is pressed facing it, by cartridge language: FD 02 is STR_VAR_1, the
# lead's nickname; FE a line break [charmap.txt]. asm/resident/follower.s, p_text.
FOLLOWER_TEXT = {"french": ("saute", "de joie !"), "english": ("jumps", "for joy!")}
FOLLOWER_TEXT_SIZE = 20
R_BUTTON = 0x100
# gHelpSystemToggleWithRButtonDisabled, French [RunHelpSystemCallback's literal, 0x0813F6FC].
HELP_R_DISABLED = 0x0203F171


# Several hooks resident at once: "turbo+noencounter", settings as "turbo.field=2". Laid out back to
# back from RESIDENT_BASE, each one's p_original the next one's entry, so the installers see one hook.
CHAIN = "+"
CHAIN_ORDER = ("turbo", "turbo-lite", "noclip", "shiny", "ivs", "noencounter")   # turbo's passes last
# Data a hook keeps outside its code, by parameter, and its size.
CHAIN_DATA = {"turbo": {"frames": 20}, "turbo-lite": {"frames": 20}, "shiny": {"state": 36}, "ivs": {"words": 12}, "noclip": {"state": 24}}
# The free word range under the kept handler: RESIDENT_DATA_FLOOR..0x0203FBFC.
CHAIN_LOW = (RESIDENT_DATA_FLOOR, 0x0203FBFC)


def chain_names(name):
    """The hooks a --resident value names, in the order they run."""
    names = name.split(CHAIN)
    if len(names) == 1:
        return names
    unknown = [n for n in names if n not in CHAIN_ORDER]
    if unknown:
        runs_alone = [n for n in unknown if n in RESIDENT_HOOKS]
        raise BufferScriptError(f"{', '.join(runs_alone)} runs alone" if runs_alone else
                                f"unknown resident hook {unknown[0]!r}; have {sorted(RESIDENT_HOOKS)}")
    if len(set(names)) != len(names):
        raise BufferScriptError(f"{name} names a hook twice")
    return sorted(names, key=CHAIN_ORDER.index)


def _chain_blob(names, build, params):
    """-> (THUMB bytes, entry offset, p_original offset, [(data address, size)]) for hooks run in turn."""
    from pokeldn.frlg.rom import native_script
    from pokeldn.frlg.rom.resident_stubs import STUBS
    own = {n: {} for n in names}
    for key, value in params.items():
        hook, _, field = key.partition(".")
        if hook not in own or not field:
            raise BufferScriptError(f"{key}: a setting of a chain is HOOK.NAME, HOOK one of {names}")
        own[hook][field] = value
    drawing = [n for n in names if n in ("shiny", "ivs") or (n == "turbo" and own[n].get("overlay"))]
    if len(drawing) > 1:
        raise BufferScriptError(f"{' and '.join(drawing)} both draw in the screen's top-right corner")
    sizes = [len(STUBS[n][0]) for n in names]
    end = native_script.RESIDENT_BASE + sum(sizes)
    if end > 0x02040000:
        raise BufferScriptError(f"{CHAIN.join(names)} is {sum(sizes)} bytes; the resident area holds "
                                f"{0x02040000 - native_script.RESIDENT_BASE}")
    free = [list(CHAIN_LOW), [end, 0x02040000]]
    data = []
    for n in names:
        for field, size in CHAIN_DATA.get(n, {}).items():
            if field in own[n]:
                continue
            region = next((r for r in free if r[1] - r[0] >= size), None)
            if region is None:
                raise BufferScriptError(f"{CHAIN.join(names)} leaves no room for {n}'s {field}")
            own[n][field] = region[0]
            data.append((region[0], size))
            region[0] += size
    blob, at, links = bytearray(), 0, []
    for n, size in zip(names, sizes):
        part, entry, original = resident_blob(n, build=build, **own[n])
        links.append((at + entry, at + original))
        blob += part
        at += size
    for (_, original), (entry, _) in zip(links, links[1:]):
        blob[original:original + 4] = (native_script.RESIDENT_BASE + entry + 1).to_bytes(4, "little")
    return bytes(blob), links[0][0], links[-1][1], data


def resident_blob(name, *, build=None, **params):
    """-> (THUMB bytes, entry offset, p_original offset) for one of RESIDENT_HOOKS, or a chain of
    them (CHAIN), on `build`."""
    from pokeldn.frlg.rom import native_script
    from pokeldn.frlg.rom.resident_stubs import STUBS
    names = chain_names(name)
    if len(names) > 1:
        return _chain_blob(names, build, params)[:3]
    if name not in RESIDENT_HOOKS:
        raise BufferScriptError(f"unknown resident hook {name!r}; have {sorted(RESIDENT_HOOKS)}")
    entry, defaults = RESIDENT_HOOKS[name]
    explicit = set(params)
    unknown = set(params) - set(defaults)
    if unknown:
        raise BufferScriptError(f"{name} takes {sorted(defaults)}, not {sorted(unknown)}")
    params = {**defaults, **params}
    if name in ("turbo", "turbo-lite") and params["hold"] & R_BUTTON and "help" not in explicit:
        params["help"] = HELP_R_DISABLED  # held R would open the Help System
    if name == "shiny" and "state" in explicit and "overlay" not in explicit:
        params["overlay"] = params["state"] + 24  # the word the hook shows
    if name == "follower" and params["deoxys"] is None:
        # the version's form: Attack on FireRed, Defense on LeafGreen [asm/resident/follower.s]
        firered = builds.resolve(build).version == "firered"
        params["deoxys"] = 0x00FDFCFD if firered else 0x00FDFDFC
    if name == "ivs" and "words" in explicit:
        params["overlay"], params["overlay2"] = params["words"], params["words"] + 4
    symbols = STUBS[name][2]
    literals = {key: value for key, value in builds.resolve(build).hook_literals().items()
                if f"p_{key}" in symbols}
    words = native_script.resident_words(name, **params, **literals)
    blob = b"".join(w.to_bytes(4, "little") for w in words)
    if name == "follower":
        from pokeldn.frlg.text import charmap
        first, second = FOLLOWER_TEXT[builds.resolve(build).language]
        text = (b"\xFD\x02" + charmap.encode(" " + first) + b"\xFE" + charmap.encode(second)
                + b"\xFF").ljust(FOLLOWER_TEXT_SIZE, b"\x00")
        at = symbols["p_text"]
        blob = blob[:at] + text[:FOLLOWER_TEXT_SIZE] + blob[at + FOLLOWER_TEXT_SIZE:]
        if len(text) > FOLLOWER_TEXT_SIZE:
            raise BufferScriptError(f"the follower's line is {len(text)} bytes, past {FOLLOWER_TEXT_SIZE}")
    return blob, symbols[entry], symbols["p_original"]


def _check_resident_layout(name, blob, dest):
    """Refuse a hook outside 0x0203FC00..0x02040000, or whose data overlaps its code, the kept
    handler below it, a claimed symbol, or another hook's data in a chain."""
    from pokeldn.frlg.rom import native_script
    from pokeldn.frlg.rom.resident_stubs import STUBS
    if dest % 4 or not (0x0203FC00 <= dest and dest + len(blob) <= 0x02040000):
        raise BufferScriptError(
            f"0x{dest:08X} is not word-aligned space inside 0x0203FC00..0x02040000, the only EWRAM "
            "no symbol claims")
    names = chain_names(name)
    if len(names) > 1 and dest != native_script.RESIDENT_BASE:
        raise BufferScriptError(f"a chain links its hooks at 0x{native_script.RESIDENT_BASE:08X}")
    taken, at = [], 0
    for n in names:
        part = blob[at:at + len(STUBS[n][0])]
        for data, size in RESIDENT_DATA.items():  # the hook's data lies outside its code
            where = STUBS[n][2].get(data)
            address = int.from_bytes(part[where:where + 4], "little") if where is not None else 0
            if not address:
                continue
            size = CHAIN_DATA.get(n, {}).get(data[2:], size) if len(names) > 1 else size
            if (dest - 4 < address + size and address < dest + len(blob)
                    or address + size > 0x02040000 or address < RESIDENT_DATA_FLOOR
                    or any(a < address + size and address < a + s for a, s in taken)):
                raise BufferScriptError(
                    f"{name} is {len(blob)} bytes from 0x{dest:08X} and runs into its {data[2:]} "
                    f"at 0x{address:08X}, or that leaves the unclaimed EWRAM")
            taken.append((address, size))
        at += len(part)


def build_install_resident(name, *, dest=None, table=None, build=None, **params):
    """The install-resident payload carrying hook `name` for `build`, parameters patched."""
    from pokeldn.frlg.rom import native_script
    build = builds.resolve(build)
    dest = native_script.RESIDENT_BASE if dest is None else dest
    table = build.intr_vblank if table is None else table
    blob, entry, original = resident_blob(name, build=build, **params)
    code = bytearray(payload(INSTALL_RESIDENT))
    if len(code) + len(blob) > MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"{name} is {len(blob)} bytes; with the installer that is past the "
            f"{MAX_BUFFER_SCRIPT_SIZE}-byte receive buffer. save-write --resident {name} keeps it "
            "in the save and installs it in one session")
    _check_resident_layout(name, blob, dest)

    def put(at, value):
        code[at:at + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    put(INSTALL_DEST_OFFSET, dest)
    put(INSTALL_LENGTH_OFFSET, len(blob))
    put(INSTALL_TABLE_OFFSET, table)
    put(INSTALL_ENTRY_OFFSET, entry)
    put(INSTALL_ORIGINAL_OFFSET, original)
    put(INSTALL_BLOB_OFFSET, len(code))
    return bytes(code) + blob


# A resident hook kept in the save: header, hook and sum in filler_B20, installed in place by
# install-kept, sent after the save-write in one session and run by MOM's RAM script after a boot
# [asm/install-kept.s, docs/frlg_rom.md].
RESIDENT_SAVE_MAGIC = 0x32524B50  # "PKR2"; the older loaders want "PKLD" or "PKRS"
RESIDENT_SAVE_SIZE = 0x400              # filler_B20
RESIDENT_SAVE_HEADER = 16
INSTALL_KEPT_THUMB_ENTRY = 8            # MOM's entry: everything before it is the ARM one
INSTALL_REFUSED = 0xBAD0BAD0            # install-resident's and install-kept's "nothing installed"


def build_resident_save_blob(name, *, build=None, **params):
    """-> the bytes save-write puts at SaveBlock2 + 0xB20 for install-kept to install `name`."""
    from pokeldn.frlg.rom import native_script
    blob, entry, original = resident_blob(name, build=build, **params)
    _check_resident_layout(name, blob, native_script.RESIDENT_BASE)
    head = (RESIDENT_SAVE_MAGIC.to_bytes(4, "little") + len(blob).to_bytes(4, "little")
            + native_script.RESIDENT_BASE.to_bytes(4, "little")
            + entry.to_bytes(2, "little") + original.to_bytes(2, "little"))
    data = head + blob
    checksum = sum(int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4))
    data += (checksum & 0xFFFFFFFF).to_bytes(4, "little")
    if len(data) > RESIDENT_SAVE_SIZE:
        raise BufferScriptError(
            f"{name} in the save is {len(data)} bytes; filler_B20 holds {RESIDENT_SAVE_SIZE}")
    return data


def build_install_kept(build=None):
    """The install-kept payload for `build`: its last two words are &gSaveBlock2Ptr and
    &gIntrTable[4]."""
    build = builds.resolve(build)
    code = bytearray(payload(INSTALL_KEPT))
    code[-8:] = build.sb2ptr.to_bytes(4, "little") + build.intr_vblank.to_bytes(4, "little")
    return bytes(code)


def build_resident_save_session(name, *, build=None, **params):
    """-> (the save-writes, install-kept): one session that keeps `name` in the save and installs it
    from there. A blob past one save-write takes two, run in turn before install-kept."""
    data = build_resident_save_blob(name, build=build, **params)
    writes = tuple(build_save_write(data[at:at + MAX_SAVE_WRITE_BYTES], SAVE_BLOCK_2, 0xB20 + at)
                   for at in range(0, len(data), MAX_SAVE_WRITE_BYTES))
    return writes, build_install_kept(build)


def build_flash_patch(sector_id, patch_offset, data, *, scratch=FLASH_WRITE_SCRATCH,
                      counter_bias=2, unsafe=False, build=None):
    """The flash-patch payload: read the id's sector out of flash, patch `data` at `patch_offset`,
    fix the checksum, write it back, bump the counter-bearing sector. Nothing is rebuilt from
    RAM."""
    build = builds.resolve(build)
    data = bytes(data)
    sector_id = int(sector_id)
    patch_offset = int(patch_offset)
    if not unsafe:
        raise BufferScriptError(
            "flash-patch edits a live save sector in place. Pass unsafe=True to mean it.")
    if sector_id not in SECTOR_CHUNK_SIZES:
        raise BufferScriptError(f"sector id {sector_id} is not one a save slot carries")
    chunk = sector_chunk_size(sector_id)
    if not 1 <= len(data) <= FLASH_PATCH_MAX_BYTES:
        raise BufferScriptError(
            f"a patch carries 1..{FLASH_PATCH_MAX_BYTES} bytes, got {len(data)}")
    if patch_offset < 0 or patch_offset + len(data) > chunk:
        raise BufferScriptError(
            f"{len(data)} bytes at {patch_offset:#x} runs past id {sector_id}'s chunk of "
            f"{chunk:#x}; the checksum only covers the chunk, so a field outside it would be "
            "written and not accounted for")
    code = bytearray(payload(FLASH_PATCH))
    for offset, value in ((FLASH_PATCH_SCRATCH_OFFSET, scratch),
                          (FLASH_PATCH_LWS_OFFSET, build.last_written_sector),
                          (FLASH_PATCH_SC_OFFSET, build.save_counter),
                          (FLASH_PATCH_ID_OFFSET, sector_id),
                          (FLASH_PATCH_OFF_OFFSET, patch_offset),
                          (FLASH_PATCH_LEN_OFFSET, len(data)),
                          (FLASH_PATCH_CHUNK_OFFSET, chunk),
                          (FLASH_PATCH_BIAS_OFFSET, counter_bias),
                          (FLASH_PATCH_SIG_OFFSET, SECTOR_SIGNATURE)):
        code[offset:offset + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "little")
    code[FLASH_PATCH_DATA_OFFSET:FLASH_PATCH_DATA_OFFSET + len(data)] = data
    return bytes(code)


def flash_write_source(fill_base=0x46570000, fill_step=1, words=FLASH_WRITE_WORDS,
                       footer=False, sector_id=0, counter=0, signature=SECTOR_SIGNATURE,
                       position=None):
    """-> the exact bytes build_flash_write makes the console compose, for verifying the sector."""
    if footer and words == FLASH_WRITE_WORDS:
        words = (sector_chunk_size(sector_id) if position is None else SECTOR_CHUNK_MIN) // 4
    pattern = b"".join(((int(fill_base) + i * int(fill_step)) & 0xFFFFFFFF).to_bytes(4, "little")
                       for i in range(int(words)))
    if not footer:
        return pattern
    out = bytearray(FLASH_SECTOR_SIZE)  # zeroed, as the game zeroes its buffer
    out[0:len(pattern)] = pattern
    out[SECTOR_FOOTER_AT:SECTOR_FOOTER_AT + 2] = (int(sector_id) & 0xFFFF).to_bytes(2, "little")
    out[SECTOR_FOOTER_AT + 2:SECTOR_FOOTER_AT + 4] = sector_checksum(
        out, sector_chunk_size(sector_id)).to_bytes(2, "little")
    out[SECTOR_FOOTER_AT + 4:SECTOR_FOOTER_AT + 8] = (int(signature) & 0xFFFFFFFF).to_bytes(4, "little")
    out[SECTOR_FOOTER_AT + 8:SECTOR_FOOTER_AT + 12] = (int(counter) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


# Trap: never dump a region that moves between frames. MGL_Send takes the header CRC one frame and
# sends the next [decomp:src/mystery_gift_link.c:155]; a mismatch is LinkRfu_FatalError, "erreur de
# connexion". gRngValue is the only known mover. docs/frlg_leafgreen.md.
def moving_regions(build=None):
    return ((builds.resolve(build).rng, 4, "gRngValue, which advances two turns every frame"),)


def _refuse_a_moving_region(address, size, build=None):
    for base, length, what in moving_regions(build):
        if address < base + length and base < address + size:
            raise BufferScriptError(
                f"0x{address:X}..0x{address + size - 1:X} overlaps {what}. MGL_Send takes the "
                "header CRC one frame and sends the bytes the next "
                "[decomp:src/mystery_gift_link.c:155], so a region that moves between them makes "
                "the console call LinkRfu_FatalError, 'erreur de connexion' mid transmission. "
                "Dump around it, or read it with rng-trace, which returns it through the 4-byte "
                "channel instead of the block.")


def _refuse_the_save_window(address, size):
    # The header CRC reads the window a byte at a time and sees flash; memcpy's word loads do not
    # [decomp:src/link_rfu_2.c:1357]. docs/frlg_rom.md, Reading flash.
    if address < FLASH_WINDOW_BASE + 0x02000000 and FLASH_WINDOW_BASE < address + size:
        raise BufferScriptError(
            f"0x{address:X}..0x{address + size - 1:X} is in the save flash window. The console "
            "sends a body that fails its own header CRC and the gift menu waits forever. Use "
            "flash-read, which byte-copies a sector into EWRAM and sends the copy.")


def build_memory_dump_multi(address, size=MAX_BUFFER_SCRIPT_SIZE, blocks=1, *, build=None):
    """The multi-block dump payload, patched with the base and the per-block length. The client
    script decides the count; `blocks` only widens the readability guard to the whole span."""
    address = int(address)
    size = int(size)
    blocks = int(blocks)
    if not 0 < size <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a block is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes (MG_LINK_BUFFER_SIZE), got {size}")
    if not 0 <= address <= 0xFFFFFFFF:
        raise BufferScriptError(f"0x{address:X} is not a 32-bit address")
    if address % 2:
        raise BufferScriptError(f"0x{address:X} is not halfword aligned")
    _refuse_a_moving_region(address, size * blocks, build)
    _refuse_the_save_window(address, size * blocks)
    code = bytearray(payload(MEMORY_DUMP_MULTI))
    code[DUMP_MULTI_BASE_OFFSET:DUMP_MULTI_BASE_OFFSET + 4] = address.to_bytes(4, "little")
    code[DUMP_MULTI_SIZE_OFFSET:DUMP_MULTI_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
    return bytes(code)


def build_memory_dump_scatter(addresses, size=MAX_BUFFER_SCRIPT_SIZE, *, build=None):
    """The scattered dump payload: one block per address, in order. Unused table slots repeat the
    last address, so an extra pass re-sends a held block rather than reading 0x00000000."""
    addresses = [int(address) for address in addresses]
    size = int(size)
    if not addresses:
        raise BufferScriptError("a scattered dump needs at least one address")
    if len(addresses) > DUMP_SCATTER_TABLE_SLOTS:
        raise BufferScriptError(
            f"the table holds {DUMP_SCATTER_TABLE_SLOTS} bases, got {len(addresses)}")
    if not 0 < size <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a block is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes (MG_LINK_BUFFER_SIZE), got {size}")
    for address in addresses:
        if not 0 <= address <= 0xFFFFFFFF:
            raise BufferScriptError(f"0x{address:X} is not a 32-bit address")
        if address % 2:
            raise BufferScriptError(f"0x{address:X} is not halfword aligned")
        # Guarded per block: the blocks are unrelated regions.
        _refuse_a_moving_region(address, size, build)
        _refuse_the_save_window(address, size)
    code = bytearray(payload(MEMORY_DUMP_SCATTER))
    code[DUMP_SCATTER_SIZE_OFFSET:DUMP_SCATTER_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
    table = addresses + [addresses[-1]] * (DUMP_SCATTER_TABLE_SLOTS - len(addresses))
    for slot, address in enumerate(table):
        at = DUMP_SCATTER_TABLE_OFFSET + 4 * slot
        code[at:at + 4] = address.to_bytes(4, "little")
    return bytes(code)


def build_memory_dump(address, size=MAX_BUFFER_SCRIPT_SIZE, *, build=None):
    """The memory-dump payload. `size` becomes link->sendSize; MGL_Receive rejects anything past
    MG_LINK_BUFFER_SIZE [decomp:src/mystery_gift_link.c:102]."""
    address = int(address)
    size = int(size)
    if not 0 < size <= MAX_BUFFER_SCRIPT_SIZE:
        raise BufferScriptError(
            f"a dump is 1..{MAX_BUFFER_SCRIPT_SIZE} bytes (MG_LINK_BUFFER_SIZE), got {size}")
    if not 0 <= address <= 0xFFFFFFFF:
        raise BufferScriptError(f"0x{address:X} is not a 32-bit address")
    if address % 2:
        raise BufferScriptError(f"0x{address:X} is not halfword aligned")
    _refuse_a_moving_region(address, size, build)
    _refuse_the_save_window(address, size)
    code = bytearray(payload(MEMORY_DUMP))
    code[DUMP_TARGET_OFFSET:DUMP_TARGET_OFFSET + 4] = address.to_bytes(4, "little")
    code[DUMP_SIZE_OFFSET:DUMP_SIZE_OFFSET + 4] = size.to_bytes(4, "little")
    return bytes(code)


def script_choices():
    return tuple(sorted(SCRIPT_REGISTRY))


# Payloads answering with bytes on ident 19 rather than the 4-byte channel, and those the log
# decodes. A new payload goes in here, or the host asks it for 4 bytes.
DUMP_SCRIPTS = frozenset({
    MEMORY_DUMP, MEMORY_DUMP_MULTI, MEMORY_DUMP_SCATTER, SAVE_DUMP, ANCHORS, SAVE_WRITE,
    MEMORY_SCAN, TABLE_SCAN, RNG_TRACE, STRING_GATHER, CREATE_MON, CALL, CALL_CHAIN,
    FLASH_READ, SLOOP_SVC, ROM_CHECKSUM,
})
DECODED_SCRIPTS = frozenset({
    MEMORY_SCAN, TABLE_SCAN, RNG_TRACE, STRING_GATHER, CREATE_MON, CALL, CALL_CHAIN, SLOOP_SVC,
    ROM_CHECKSUM,
})
assert DECODED_SCRIPTS <= DUMP_SCRIPTS
assert DUMP_SCRIPTS <= set(SCRIPT_REGISTRY)


def format_script_help():
    return "; ".join(f"{spec.name}: {spec.description}"
                     for spec in SCRIPT_REGISTRY.values())

# The spans each builder patches, so a built payload is still recognised by `describe`.
PATCHED_SPANS = {
    MEMORY_DUMP: ((DUMP_TARGET_OFFSET, 8),),
    MEMORY_DUMP_MULTI: ((DUMP_MULTI_BASE_OFFSET, 8),),
    MEMORY_DUMP_SCATTER: ((DUMP_SCATTER_SIZE_OFFSET,
                           4 + 4 * DUMP_SCATTER_TABLE_SLOTS),),
    SAVE_DUMP: ((SAVE_DUMP_WHICH_OFFSET, 12),),
    SAVE_WRITE: ((SAVE_WRITE_WHICH_OFFSET, MAX_BUFFER_SCRIPT_SIZE),),
    RNG_TRACE: ((TRACE_ADDRESS_OFFSET,
                 TRACE_RESULT_OFFSET - TRACE_ADDRESS_OFFSET + TRACE_HEADER_SIZE
                 + 8 * TRACE_SAMPLE_CAPACITY),),
    MEMORY_SCAN: ((SCAN_CURSOR_OFFSET,
                   SCAN_HITS_OFFSET - SCAN_CURSOR_OFFSET + 8 * SCAN_HIT_CAPACITY),),
    TABLE_SCAN: ((TABLE_CURSOR_OFFSET, TABLE_EXPECT_OFFSET + 4 - TABLE_CURSOR_OFFSET),),
    ROM_CHECKSUM: ((ROM_CHECKSUM_CURSOR_OFFSET,
                    ROM_CHECKSUM_SUMS_OFFSET + 4 * ROM_CHECKSUM_CAPACITY
                    - ROM_CHECKSUM_CURSOR_OFFSET),),
    STRING_GATHER: ((GATHER_SRC_OFFSET,
                     GATHER_STRINGS_OFFSET - GATHER_SRC_OFFSET + GATHER_STRING_AREA),),
    # Includes the 100 bytes CreateMon writes into the image itself.
    CREATE_MON: ((CREATE_MON_FUNCTION_OFFSET,
                  CREATE_MON_PARTY_OFFSET - CREATE_MON_FUNCTION_OFFSET + 4),),
    CALL: ((CALL_FUNCTION_OFFSET,
            CALL_RESULT_OFFSET - CALL_FUNCTION_OFFSET + CALL_ANSWER_SIZE),),
    CALL_CHAIN: ((CHAIN_COUNT_OFFSET,
                  CHAIN_RESULT_OFFSET - CHAIN_COUNT_OFFSET + CHAIN_ANSWER_SIZE),),
    FLASH_READ: ((FLASH_READ_BANK_OFFSET,
                  FLASH_READ_SCRATCH_OFFSET + 4 - FLASH_READ_BANK_OFFSET),),
    FLASH_PATCH: ((FLASH_PATCH_SCRATCH_OFFSET,
                   FLASH_PATCH_DATA_OFFSET + FLASH_PATCH_MAX_BYTES
                   - FLASH_PATCH_SCRATCH_OFFSET),),
    FLASH_WRITE: ((FLASH_WRITE_SECTOR_OFFSET,
                   FLASH_WRITE_THUNK_OFFSET + 4 - FLASH_WRITE_SECTOR_OFFSET),),
    SLOOP_SVC: ((SLOOP_FLAGS_OFFSET, SLOOP_DATA_OFFSET + SLOOP_DATA_MAX - SLOOP_FLAGS_OFFSET),),
    INSTALL_RESIDENT: ((INSTALL_DEST_OFFSET, INSTALL_BLOB_OFFSET + 4 - INSTALL_DEST_OFFSET),),
    INSTALL_KEPT: ((len(PAYLOADS[INSTALL_KEPT][0]) - 8, 8),),
}


def describe(code):
    """Name a payload from its bytes, operands and all."""
    code = bytes(code)
    for name, (committed, _) in PAYLOADS.items():
        # save-write and install-resident vary in length; a received image is the whole buffer.
        longer_is_fine = name in (SAVE_WRITE, INSTALL_RESIDENT, INSTALL_KEPT)
        if len(code) != len(committed) and not (longer_is_fine and len(code) > len(committed)):
            continue
        image, reference = bytearray(code[:len(committed)]), bytearray(committed)
        for offset, length in PATCHED_SPANS.get(name, ()):
            image[offset:offset + length] = reference[offset:offset + length]
        if bytes(image) == bytes(reference):
            return f"{name} ({len(code)} bytes of ARM)"
    return f"unknown buffer script ({len(code)} bytes of ARM, head {bytes(code[:8]).hex()})"


# struct MysteryGiftClient [decomp:include/mystery_gift_client.h:71], offsets from r0 =
# &client->param. MysteryGiftLink_InitSend stores the pointer and the CRC is taken at send time
# [mystery_gift_link.c:59,166], so repointing sendBuffer/sendSize reads out any address.
CLIENT_UNUSED = 0x00
CLIENT_PARAM = 0x04                 # what r0 points at
CLIENT_FUNC_ID = 0x08
CLIENT_FUNC_STATE = 0x0C
CLIENT_CMDIDX = 0x10
CLIENT_SEND_BUFFER = 0x14
CLIENT_RECV_BUFFER = 0x18
CLIENT_SCRIPT = 0x1C
CLIENT_MSG = 0x20
CLIENT_LINK = 0x24

# struct MysteryGiftLink [decomp:include/mystery_gift_link.h].
LINK_STATE = 0x00
LINK_SEND_IDENT = 0x0E
LINK_SEND_COUNTER = 0x10
LINK_SEND_CRC = 0x12
LINK_SEND_SIZE = 0x14
LINK_RECV_BUFFER = 0x18
LINK_SEND_BUFFER = 0x1C

# Offsets measured from r0.
FROM_PARAM_SEND_BUFFER = CLIENT_SEND_BUFFER - CLIENT_PARAM            # 0x10
FROM_PARAM_LINK_SEND_SIZE = CLIENT_LINK + LINK_SEND_SIZE - CLIENT_PARAM    # 0x34
FROM_PARAM_LINK_SEND_BUFFER = CLIENT_LINK + LINK_SEND_BUFFER - CLIENT_PARAM  # 0x3C


# The GBA map, as much as a payload can touch, at the real addresses.
EWRAM_BASE, EWRAM_SIZE = 0x02000000, 0x00040000
IWRAM_BASE, IWRAM_SIZE = 0x03000000, 0x00008000
# The 32 MB cartridge window; FireRed fills the first 16.
ROM_BASE, ROM_SIZE = 0x08000000, 0x02000000
# [GBA cartridge header] 0xA0 title, 0xAC game code, 0xB0 maker, 0xBC software version.
ROM_HEADER_TITLE = ROM_BASE + 0xA0
ROM_HEADER_GAME_CODE = ROM_BASE + 0xAC
STACK_POINTER = 0x03007F00          # SP_usr as the BIOS leaves it
_RETURN_ADDRESS = 0x0F000000  # sentinel: where bx lr lands and emulation stops
# The client is AllocZeroed in gHeap, below the code buffer [mystery_gift_client.c:72].
_CLIENT_ADDRESS = 0x02001000
_SEND_BUFFER_ADDRESS = 0x02002000
_RECV_BUFFER_ADDRESS = 0x02003000
SAV2_ADDRESS = 0x02025000           # clear of the code buffer at 0x0201C000
SAV1_ADDRESS = 0x0202C000
_SAV2_ADDRESS = SAV2_ADDRESS
_SAV1_ADDRESS = SAV1_ADDRESS
_INSTRUCTION_LIMIT = 100000


@dataclass
class ClientState:
    """struct MysteryGiftClient as the payload left it."""
    param: int
    send_buffer: int
    send_size: int
    send_ident: int
    armed_buffer: int = _SEND_BUFFER_ADDRESS  # what CLI_LOAD_TOSS_RESPONSE's InitSend left
    armed_size: int = 4

    @property
    def send_repointed(self):
        """The payload aimed the outgoing message at another address."""
        return self.send_buffer != self.armed_buffer

    @property
    def send_resized(self):
        """It changed the size only; `anchors` fills client->sendBuffer itself."""
        return self.send_size != self.armed_size

    @property
    def send_changed(self):
        """MGL_Send reads both fields at send time [mystery_gift_link.c:166]."""
        return self.send_repointed or self.send_resized


@dataclass
class BufferScriptRun:
    """What one call of a payload did."""
    returned: int           # r0: BUFFER_SCRIPT_DONE ends the call
    param: int  # *param, which CLI_LOAD_TOSS_RESPONSE ships back
    sav2: bytes             # the save blocks as the payload left them
    sav1: bytes
    instructions: int
    client: ClientState
    pending_send: bytes  # what a following CLI_SEND_LOADED would put on the wire

    @property
    def done(self):
        return self.returned == BUFFER_SCRIPT_DONE


IO_BASE, IO_SIZE = 0x04000000, 0x1000
_UC_EXCP_BKPT = 7                   # unicorn's ARM EXCP_BKPT, the intno a bkpt raises


def emulation_available():
    try:
        import unicorn  # noqa: F401
    except ImportError:
        return False
    return True


# Enough of a cartridge header for a ROM dump to identify.
def _default_rom_header(build):
    return (b"\x00" * 0xA0
            + (b"POKEMON FIRE" if build.version == "firered" else b"POKEMON LEAF")  # 0xA0 title
            + build.game_code.encode()                                           # 0xAC game code
            + b"01"                                                              # 0xB0 maker code
            + b"\x96")                                                           # 0xB2 fixed value


# Offline stand-ins for CreateMon, placed with `memory={address: stub}`. CREATE_MON_ARG_MODEL writes
# r0..r3 and the four stack arguments into the destination as eight words: str r1..r3,[r0,#4..12];
# ldr/str [sp,#0..12] -> [r0,#16..28]; str r0,[r0]; bx lr.
CREATE_MON_ARG_MODEL = bytes.fromhex(
    "41608260c3600099016101994161029981610399c16100607047")
CREATE_MON_ARG_FIELDS = ("mon", "species", "level", "fixedIV", "hasFixedPersonality",
                         "fixedPersonality", "otIdType", "fixedOtId")

# create_mon_copy_model copies 100 prepared bytes over the destination: a byte loop, then pop {r4};
# pop {r0}; bx r0, then .Lsource.
_CREATE_MON_COPY_MODEL = bytes.fromhex(
    "10b5054964220c78047001310130013af9d110bc01bc0047")
CREATE_MON_COPY_MODEL_SOURCE = len(_CREATE_MON_COPY_MODEL)  # where the .word goes


def create_mon_copy_model(source):
    """A model of CreateMon that copies the 100 bytes at `source` into its first argument."""
    return _CREATE_MON_COPY_MODEL + (int(source) & 0xFFFFFFFF).to_bytes(4, "little")


class _Machine:
    """The console's memory across a whole CLI_RUN_BUFFER_SCRIPT: the image is copied once
    [decomp:src/mystery_gift_client.c:239] and then called every frame until it returns 1. `call`
    is one frame."""

    def __init__(self, code, *, param=0, sav2=b"", sav1=b"", memory=None, send_size=4,
                 send_ident=0, rom=None, build=None):
        try:
            import unicorn
            from unicorn import arm_const
        except ImportError:  # pragma: no cover - exercised only on a machine without unicorn
            raise BufferScriptError(
                "offline execution needs unicorn (pip install unicorn)") from None
        self._unicorn = unicorn
        self._arm = arm_const

        validate(code)
        uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM | unicorn.UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(EWRAM_BASE, EWRAM_SIZE)
        uc.mem_map(IWRAM_BASE, IWRAM_SIZE)
        uc.mem_map(ROM_BASE, ROM_SIZE)
        uc.mem_map(IO_BASE, IO_SIZE)  # plain memory: REG_IME and friends read back
        uc.mem_map(0x05000000, 0x400)         # palette
        uc.mem_map(0x06000000, 0x18000)       # VRAM
        uc.mem_map(0x07000000, 0x400)         # OAM
        build = builds.resolve(build)
        uc.mem_write(ROM_BASE, bytes(rom if rom is not None else _default_rom_header(build)))
        uc.mem_map(_RETURN_ADDRESS, 0x1000)
        # The chip is 128 KiB, erased; the CPU sees a 64 KiB window one bank at a time. swi 0x48
        # addresses the chip linearly, a guest load the window, so both are modelled.
        self.uc = uc  # _show_bank needs it before the rest
        self.flash = bytearray(b"\xFF" * FLASH_SIZE)
        self.flash_bank = 0
        uc.mem_map(FLASH_WINDOW_BASE, FLASH_WINDOW_SIZE)
        self.flash_writes = []          # (number, sector, source, accepted, why)
        self.flash_reads = []           # (sector, offset, dest, length)
        self.bkpts = []                 # the immediate of each bkpt executed
        uc.hook_add(unicorn.UC_HOOK_MEM_WRITE, self._on_flash_store,
                    begin=FLASH_WINDOW_BASE, end=FLASH_WINDOW_BASE + FLASH_WINDOW_SIZE - 1)
        uc.hook_add(unicorn.UC_HOOK_INTR, self._on_swi)
        entry = build.read_flash
        uc.hook_add(unicorn.UC_HOOK_CODE, self._on_readflash, begin=entry, end=entry)

        def word(offset, value):
            uc.mem_write(_CLIENT_ADDRESS + offset, (value & 0xFFFFFFFF).to_bytes(4, "little"))

        def half(offset, value):
            uc.mem_write(_CLIENT_ADDRESS + offset, (value & 0xFFFF).to_bytes(2, "little"))

        uc.mem_write(GDECOMPRESSION_BUFFER, bytes(code))
        word(CLIENT_PARAM, int(param))
        word(CLIENT_SEND_BUFFER, _SEND_BUFFER_ADDRESS)
        word(CLIENT_RECV_BUFFER, _RECV_BUFFER_ADDRESS)
        uc.mem_write(_RECV_BUFFER_ADDRESS, bytes(code))  # the console copies from here
        # As CLI_LOAD_TOSS_RESPONSE leaves it: the send armed at client->sendBuffer.
        word(CLIENT_LINK + LINK_SEND_BUFFER, _SEND_BUFFER_ADDRESS)
        half(CLIENT_LINK + LINK_SEND_SIZE, send_size)
        half(CLIENT_LINK + LINK_SEND_IDENT, send_ident)
        word(CLIENT_LINK + LINK_RECV_BUFFER, _RECV_BUFFER_ADDRESS)
        uc.mem_write(_SEND_BUFFER_ADDRESS, int(param).to_bytes(4, "little"))

        sav2, sav1 = bytes(sav2), bytes(sav1)
        if sav2:
            uc.mem_write(_SAV2_ADDRESS, sav2)
        if sav1:
            uc.mem_write(_SAV1_ADDRESS, sav1)
        # As on the console: the save block pointers, and VBlankIntr in gIntrTable[4].
        uc.mem_write(build.sb2ptr, _SAV2_ADDRESS.to_bytes(4, "little"))
        uc.mem_write(build.sb1ptr, _SAV1_ADDRESS.to_bytes(4, "little"))
        uc.mem_write(build.intr_vblank, (build.vblank_intr | 1).to_bytes(4, "little"))
        for address, blob in (memory or {}).items():
            if address == FLASH_BASE:
                self.flash[:len(blob)] = bytes(blob)     # the chip, not the aperture
            else:
                uc.mem_write(address, bytes(blob))
        self._show_bank()

        self.uc = uc
        self.armed_size = send_size
        self._sav2_len, self._sav1_len = len(sav2), len(sav1)
        self.calls = 0

    def _show_bank(self):
        """Put the selected bank in the aperture, undoing the command bytes a bank select stores."""
        at = self.flash_bank * FLASH_WINDOW_SIZE
        self.uc.mem_write(FLASH_WINDOW_BASE, bytes(self.flash[at:at + FLASH_WINDOW_SIZE]))

    def _on_flash_store(self, uc, access, address, size, value, user_data=None):
        """A store into the aperture is a command. Only the bank select is modelled
        [decomp:src/agb_flash.c SwitchFlashBank]."""
        if address == FLASH_WINDOW_BASE and size == 1 and value in (0, 1):
            self.flash_bank = value
        self._show_bank()

    def _on_readflash(self, uc, address, size, user_data=None):
        """Model ReadFlash: copy `size` bytes of sector `sectorNum` into `dest`. Its REG_WAITCNT
        write is not modelled."""
        arm = self._arm
        sector = uc.reg_read(arm.UC_ARM_REG_R0) & 0xFFFF
        offset = uc.reg_read(arm.UC_ARM_REG_R1)
        dest = uc.reg_read(arm.UC_ARM_REG_R2)
        length = uc.reg_read(arm.UC_ARM_REG_R3)
        at = sector * FLASH_SECTOR_SIZE + offset
        uc.mem_write(dest, bytes(self.flash[at:at + length]))
        self.flash_reads.append((sector, offset, dest, length))
        link = uc.reg_read(arm.UC_ARM_REG_LR)
        cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
        uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr | (1 << 5) if link & 1 else cpsr & ~(1 << 5))
        uc.reg_write(arm.UC_ARM_REG_PC, link & ~1)

    def _on_swi(self, uc, intno, user_data=None):
        """Model the Sloop sector syscalls, as measured on the FR emulator: swi 0x48 copies 0x1000
        bytes from r1 into sector r0 and touches no register; a rejected side writes nothing.
        swi 0x56 also stores 0xFF at +0xFF8 with no null check [docs/frlg_rom.md]. Other numbers
        are left alone."""
        arm = self._arm
        cpsr = uc.reg_read(arm.UC_ARM_REG_CPSR)
        pc = uc.reg_read(arm.UC_ARM_REG_PC)
        if intno == _UC_EXCP_BKPT:
            # The wrapper's bkpt handler [main+0x1efc0] runs slot N and returns: a NOP to the guest.
            self.bkpts.append(int.from_bytes(uc.mem_read(pc, 2), "little") & 0xFF)
            uc.reg_write(arm.UC_ARM_REG_PC, (pc + 2) | 1 if cpsr & (1 << 5) else pc + 4)
            return
        if cpsr & (1 << 5):  # THUMB: the swi is the halfword just executed
            number = int.from_bytes(uc.mem_read(pc - 2, 2), "little") & 0xFF
        else:
            number = int.from_bytes(uc.mem_read(pc - 4, 4), "little") & 0xFFFFFF
        if number not in (SWI_WRITE_SECTOR, SWI_REPLACE_SECTOR):
            return
        sector = uc.reg_read(arm.UC_ARM_REG_R0)
        source = uc.reg_read(arm.UC_ARM_REG_R1)
        offset = (sector * FLASH_SECTOR_SIZE) & 0xFFFFFFFF
        why = None
        if offset >= FLASH_SIZE or FLASH_SIZE - offset < FLASH_SECTOR_SIZE:
            why = f"destination sector {sector} folds to 0x{offset:X}, outside {FLASH_SIZE:#x}"
        payload_bytes = None
        if why is None:
            try:
                payload_bytes = bytes(uc.mem_read(source, FLASH_SECTOR_SIZE))
            except self._unicorn.UcError:
                why = f"source 0x{source:08X} is not {FLASH_SECTOR_SIZE:#x} bytes of mapped memory"
        if why is None:
            self.flash[offset:offset + FLASH_SECTOR_SIZE] = payload_bytes
            if number == SWI_REPLACE_SECTOR:
                self.flash[offset + SECTOR_SIGNATURE_OFFSET_IN_SECTOR] = 0xFF
            self._show_bank()
        elif number == SWI_REPLACE_SECTOR:
            raise BufferScriptError(
                f"swi 0x56 with a rejected destination aborts: {why}. On the console that is the "
                "strb at main+0x573F8 going to a null pointer.")
        self.flash_writes.append((number, sector, source, why is None, why))

    def call(self, instruction_limit=_INSTRUCTION_LIMIT):
        """One frame: Client_RunBufferScript calling the payload once."""
        uc, unicorn, arm_const = self.uc, self._unicorn, self._arm
        uc.reg_write(arm_const.UC_ARM_REG_R0, _CLIENT_ADDRESS + CLIENT_PARAM)
        uc.reg_write(arm_const.UC_ARM_REG_R1, _SAV2_ADDRESS)
        uc.reg_write(arm_const.UC_ARM_REG_R2, _SAV1_ADDRESS)
        uc.reg_write(arm_const.UC_ARM_REG_SP, STACK_POINTER)
        uc.reg_write(arm_const.UC_ARM_REG_LR, _RETURN_ADDRESS | 1)

        executed = [0]

        def count(uc_, address, size, user_data):
            executed[0] += 1

        handle = uc.hook_add(unicorn.UC_HOOK_CODE, count)
        try:
            uc.emu_start(GDECOMPRESSION_BUFFER, _RETURN_ADDRESS, count=instruction_limit)
        except unicorn.UcError as exc:
            pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
            raise BufferScriptError(
                f"the payload faulted at pc=0x{pc:08X} (offset "
                f"{pc - GDECOMPRESSION_BUFFER}): {exc}") from None
        finally:
            uc.hook_del(handle)
        pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
        if pc != _RETURN_ADDRESS:
            raise BufferScriptError(
                f"the payload never returned: stopped at pc=0x{pc:08X} after {executed[0]} "
                "instructions. On the console that is a hang inside the Mystery Gift menu.")
        self.calls += 1

        def read_word(offset):
            return int.from_bytes(uc.mem_read(_CLIENT_ADDRESS + offset, 4), "little")

        def read_half(offset):
            return int.from_bytes(uc.mem_read(_CLIENT_ADDRESS + offset, 2), "little")

        client = ClientState(
            param=read_word(CLIENT_PARAM),
            send_buffer=read_word(CLIENT_LINK + LINK_SEND_BUFFER),
            send_size=read_half(CLIENT_LINK + LINK_SEND_SIZE),
            send_ident=read_half(CLIENT_LINK + LINK_SEND_IDENT),
            armed_buffer=_SEND_BUFFER_ADDRESS, armed_size=self.armed_size)
        try:
            pending = bytes(uc.mem_read(client.send_buffer, client.send_size))
        except unicorn.UcError:
            raise BufferScriptError(
                f"the payload left link->sendBuffer at 0x{client.send_buffer:08X} for "
                f"{client.send_size} bytes, which is not readable memory. The console would fault "
                "computing the CRC over it [mystery_gift_link.c:166].") from None
        return BufferScriptRun(
            returned=uc.reg_read(arm_const.UC_ARM_REG_R0),
            param=client.param,
            sav2=bytes(uc.mem_read(_SAV2_ADDRESS, self._sav2_len)) if self._sav2_len else b"",
            sav1=bytes(uc.mem_read(_SAV1_ADDRESS, self._sav1_len)) if self._sav1_len else b"",
            instructions=executed[0],
            client=client,
            pending_send=pending,
        )


def emulate(code, *, param=0, sav2=b"", sav1=b"", memory=None, send_size=4,
            send_ident=0, rom=None, build=None, instruction_limit=_INSTRUCTION_LIMIT):
    """Run a payload once, as Client_RunBufferScript does, on a model of the console's memory.

    `send_size`/`send_ident` are the armed send (4 bytes after CLI_LOAD_TOSS_RESPONSE); `memory` is
    {address: bytes}; `rom` seeds 0x08000000. `pending_send` is what CLI_SEND_LOADED would transmit.
    lr has bit 0 set, so a return other than `bx lr` crashes here as on the console."""
    return _Machine(code, param=param, sav2=sav2, sav1=sav1, memory=memory,
                    send_size=send_size, send_ident=send_ident,
                    rom=rom, build=build).call(instruction_limit=instruction_limit)


@dataclass
class RepeatedRun:
    """A whole multi-frame payload: every call it took, and what the last one left."""
    calls: int
    final: BufferScriptRun
    instructions: int  # summed over the calls

    @property
    def done(self):
        return self.final.done


def emulate_repeating(code, *, max_calls=MAX_SCAN_CALLS + 2,
                      instruction_limit=_INSTRUCTION_LIMIT, **kwargs):
    """Call a payload until it returns 1, once a frame; `max_calls` is this side's bound, so a hang
    is a BufferScriptError here."""
    machine = _Machine(code, **kwargs)
    instructions = 0
    for _ in range(int(max_calls)):
        run = machine.call(instruction_limit=instruction_limit)
        instructions += run.instructions
        if run.done:
            return RepeatedRun(calls=machine.calls, final=run, instructions=instructions)
    raise BufferScriptError(
        f"the payload had not returned {BUFFER_SCRIPT_DONE} after {max_calls} calls. On the "
        "console that is the Mystery Gift menu calling it every frame for ever, with no way out.")
