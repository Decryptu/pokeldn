"""Write a ROM image into a FireRed or LeafGreen console's running ROM copy over Mystery Gift, then
boot it, through asm/rom-transfer.s [docs/rse_switch_build.md, Delivery without Atmosphere]. The
server speaks MysteryGiftServer's contract to HostMysteryGiftEngine, as save_transfer's servers do.

The session runs the cartridge's own link and Mystery Gift code from the ROM copy it overwrites, so
the blocks that code needs (`live`) are written last: their new bytes go to staging blocks past both
images, and the boot op moves them into place with interrupts off, fills the tail with 0xFF and
soft-resets. A cut session resumes: every session starts by hashing the console's blocks."""

import concurrent.futures
import itertools

from pokeldn.frlg.gift import rom_lzma, save_transfer
from pokeldn.frlg.gift.mg_server import SVR_MSG_NOTHING_SENT, _encode_message
from pokeldn.frlg.gift.mystery_gift import (
    MG_LINK_BUFFER_SIZE, MG_LINKID_CLIENT_SCRIPT, MG_LINKID_NEWS, MG_LINKID_RAM_SCRIPT,
    MG_LINKID_RESPONSE,
)
from pokeldn.frlg.rom import builds
from pokeldn.frlg.rom.buffer_payloads import PAYLOADS, THUMB_CODE
from pokeldn.frlg.save import sav

C = save_transfer.C
BLOCK = 0x1000
BLOCKS = 0x1000                        # the fold reaches 16 MB [docs/frlg_rom.md, The flash sector path]
OP_DATA, OP_SURVEY, OP_BOOT, OP_FILL = 1, 3, 4, 5
DATA_HEADER = 12
BOOT_HEADER = 16
SURVEY_PER_RUN = 32                    # 128 KB hashed per frame; 32 words answered
DECODER_BLOCK = 0xFFF                  # asm/rom-lzma.c runs from here; the boot's fill clears it
LZ_DATA_HEADER = 10
LZ_PIECE = MG_LINK_BUFFER_SIZE - LZ_DATA_HEADER
# The decoding a data message may cause: 10 frames. The console drops a message's second link block
# when it arrives, about 20 frames after the last message, before the decoding ends.
LZ_MESSAGE_FRAMES = 10
# asm/rom-lzma.c decodes a symbol only with LOOKAHEAD (20) bytes past its read position, which runs
# 5 bytes ahead of the encoder's output count.
LOOKAHEAD = 25
FILL_PER_MESSAGE = 8                   # a write and a read-back are about 6000 instructions
SOUND_INFO_AT = 0x008                  # asm/rom-transfer.s: &gSoundInfo, the engine stopped at install
MAX_BOOT_BLOCKS = (MG_LINK_BUFFER_SIZE - BOOT_HEADER) // 2
_EMPTY = b"\xff" * BLOCK

NOT_WRITTEN = _encode_message("The ROM could not be written.\nNothing was started.", None)


def live_blocks(path=None):
    """-> {game code: [block]} from `path`, or the measured ones in pokeldn/frlg/data."""
    import json
    if path is None:
        from importlib import resources
        source = resources.files("pokeldn.frlg").joinpath("data/rom_live_blocks.json")
        if not source.is_file():
            return {}
        text = source.read_text()
    else:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    return {code: sorted(int(n) for n in blocks) for code, blocks in json.loads(text).items()
            if not code.startswith("_")}


def code(build=None):
    """The payload image; with a build, it stops that cartridge's sound engine at install."""
    image = bytearray(PAYLOADS["rom-transfer"][0])
    if build is not None:
        image[SOUND_INFO_AT:SOUND_INFO_AT + 4] = build.sound_info.to_bytes(4, "little")
    return bytes(image)


def block_hash(data):
    """asm/rom-transfer.s OP_SURVEY: h = rotl(h, 1) ^ word over the block's words."""
    h = 0
    for word in memoryview(bytes(data)).cast("I"):
        h = (((h << 1) | (h >> 31)) & 0xFFFFFFFF) ^ word
    return h


def blocks_of(image):
    """-> the image as 4 KB blocks, the last padded with 0xFF; refuses one past 16 MB."""
    image = bytes(image).rstrip(b"\xff")
    if len(image) > BLOCKS * BLOCK:
        raise ValueError(f"a {len(image)}-byte image does not fit the 16 MB ROM copy")
    return [image[at:at + BLOCK].ljust(BLOCK, b"\xff") for at in range(0, len(image), BLOCK)]


def with_wrapper_patches(blocks, code):
    """-> `blocks` carrying the application's librfu patches for cartridge `code`, as the ROM copy
    does once loaded; a librfu the patches do not match is refused [builds.wrapper_patches]."""
    blocks = list(blocks)
    for at, original, guest in builds.wrapper_patches(code):
        raw = bytearray(blocks[at // BLOCK]) if at // BLOCK < len(blocks) else None
        if raw is None or raw[at % BLOCK:at % BLOCK + len(original)] not in (original, guest):
            raise ValueError(f"the image has no {code} librfu at 0x{0x08000000 + at:08X}: the "
                             "application's link patches would land on other code")
        raw[at % BLOCK:at % BLOCK + len(guest)] = guest
        blocks[at // BLOCK] = bytes(raw)
    return blocks


def staging_start(count, used, live):
    """-> the first of `count` consecutive blocks at or past `used` that no live block occupies."""
    live = set(live)
    for start in range(used, BLOCKS - count + 1):
        if not live.intersection(range(start, start + count)):
            return start
    raise ValueError(f"{count} live blocks do not fit in the ROM copy's free tail past block {used}")


def block_messages(n, raw):
    """-> the OP_DATA messages that fill STAGING with `raw` and write it to ROM block `n`."""
    messages, tokens, offset, i = [], sav.deflate(raw), 0, 0
    while i < len(tokens):
        start, body = offset, bytearray()
        while i < len(tokens) and DATA_HEADER + len(body) + len(tokens[i][0]) <= MG_LINK_BUFFER_SIZE:
            body += tokens[i][0]
            offset += tokens[i][1]
            i += 1
        messages.append(save_transfer._branch_word().to_bytes(4, "little")
                        + bytes((OP_DATA, 1 if i == len(tokens) else 0)) + n.to_bytes(2, "little")
                        + start.to_bytes(2, "little") + len(body).to_bytes(2, "little") + bytes(body))
    return messages


def fill_message(value, first, count):
    return (save_transfer._branch_word().to_bytes(4, "little") + bytes((OP_FILL, value))
            + first.to_bytes(2, "little") + count.to_bytes(2, "little"))


def write_messages(writes):
    """[(block, raw)] -> [(message, blocks it completes)]: a run of blocks of one byte is one fill."""
    out, i = [], 0
    while i < len(writes):
        n, raw = writes[i]
        if raw == raw[:1] * BLOCK:
            j = i
            while (j + 1 < len(writes) and j + 1 - i < FILL_PER_MESSAGE
                   and writes[j + 1] == (writes[j][0] + 1, raw)):
                j += 1
            out.append((fill_message(raw[0], n, j - i + 1), j - i + 1))
            i = j + 1
            continue
        messages = block_messages(n, raw)
        out += [(message, 0) for message in messages[:-1]] + [(messages[-1], 1)]
        i += 1
    return out


def lz_start_message(start, blocks, staging, base, emitted, live):
    """A chunk's model reset: the stream's first block, the chunk's blocks, the first staging block,
    where the stream begins in the dictionary, the bytes emitted before the chunk, the live blocks."""
    return (save_transfer._branch_word().to_bytes(4, "little") + bytes((6, 0))
            + b"".join(v.to_bytes(2, "little") for v in (start, blocks, staging))
            + base.to_bytes(4, "little") + emitted.to_bytes(4, "little") + len(live).to_bytes(2, "little")
            + b"".join(n.to_bytes(2, "little") for n in live))


def lz_cost(marks, at, end):
    """The decoding the stream bytes [at, end) cause, from the encoder's marks."""
    before = [cost for byte, cost in marks if byte <= at]
    upto = [cost for byte, cost in marks if byte <= end]
    return (upto[-1] if upto else 0) - (before[-1] if before else 0)


def lz_cuts(length, marks):
    """-> where each data message of a chunk ends: at most LZ_PIECE bytes, and at most about
    LZ_MESSAGE_FRAMES * rom_lzma.BUDGET of decoding, as the encoder's marks give it."""
    cuts, at, k = [], 0, 0
    while at < length:
        end = min(length, at + LZ_PIECE)
        while k < len(marks) and marks[k][0] <= at:
            k += 1
        base = marks[k - 1][1] if k else 0
        j = k
        while j < len(marks) and marks[j][0] < end:
            if marks[j][1] - base > LZ_MESSAGE_FRAMES * rom_lzma.BUDGET:
                end = max(at + 1, marks[j][0] - 1)       # before the byte that brings the mark in
                break
            j += 1
        cuts.append(end)
        at = end
    return cuts


def lz_plan(length, marks):
    """-> [(start, end, heavy)] for a chunk's data messages. A symbol decodes once LOOKAHEAD more
    bytes are in, so its work falls on the message holding those; a heavy message decodes for longer
    than the next one may wait, and its batch ends after it."""
    marks = [(byte + LOOKAHEAD, cost) for byte, cost in marks]
    limit, plan, at = LZ_MESSAGE_FRAMES * rom_lzma.BUDGET, [], 0
    for end in lz_cuts(length, marks):
        plan.append((at, end, lz_cost(marks, at, 1 << 30 if end >= length else end) > limit))
        at = end
    return plan


def lz_messages(chunks, start, staging, live):
    """[(emitted, blocks, data, marks)] -> [(message, blocks it completes, heavy)]."""
    out, seq = [], 0
    for emitted, count, data, marks in chunks:
        out.append((lz_start_message(start, count, staging, rom_lzma.BASE, emitted, live), 0))
        for at, end, heavy in lz_plan(len(data), marks):
            piece, last = data[at:end], end >= len(data)
            out.append((save_transfer._branch_word().to_bytes(4, "little") + bytes((7, last))
                        + (seq & 0xFFFF).to_bytes(2, "little") + len(piece).to_bytes(2, "little") + piece,
                        count if last else 0, heavy))
            seq += 1
    return out


_WORKER = {}


class _Inline:
    """An executor that runs the job in place, for a caller with no link to keep alive."""

    @staticmethod
    def submit(fn, *args):
        future = concurrent.futures.Future()
        future.set_result(fn(*args))
        return future

    @staticmethod
    def shutdown(wait=True):
        pass


def _worker_load(image, base, code):
    """The encoder process's copy of both images, sent once at its start, before any session."""
    _WORKER.update(blocks=with_wrapper_patches(blocks_of(image), code),
                   base=with_wrapper_patches(blocks_of(base), code))


def _worker_encode(sources, top, slots):
    """sources[m]: ("target", n), ("base", m), ("ff",) or None: what block m of the copy holds."""
    blocks, base = _WORKER["blocks"], _WORKER["base"]
    copy, known = bytearray(BLOCKS * BLOCK), [False] * BLOCKS
    for m, source in enumerate(sources):
        if source is not None:
            raw = _EMPTY if source[0] == "ff" else (blocks if source[0] == "target" else base)[source[1]]
            copy[m * BLOCK:(m + 1) * BLOCK] = raw
            known[m] = True
    return rom_lzma.Stream(copy, known, {b: blocks[b] for b in range(top + 1)}, top, slots).chunks()


def survey_message(first, count, tag):
    return (save_transfer._branch_word().to_bytes(4, "little") + bytes((OP_SURVEY, 0))
            + first.to_bytes(2, "little") + count.to_bytes(2, "little")
            + SURVEY_PER_RUN.to_bytes(2, "little") + tag.to_bytes(4, "little"))


def boot_message(targets, staged, fill, fill_count):
    """Staged block staged + i goes to targets[i]; fill_count blocks from `fill` become 0xFF."""
    if len(targets) > MAX_BOOT_BLOCKS:
        raise ValueError(f"the boot message moves at most {MAX_BOOT_BLOCKS} blocks, asked for {len(targets)}")
    return (save_transfer._branch_word().to_bytes(4, "little") + bytes((OP_BOOT, 0))
            + b"".join(v.to_bytes(2, "little") for v in (len(targets), staged, fill, fill_count))
            + bytes(2) + b"".join(n.to_bytes(2, "little") for n in targets))


def batches(items):
    """[(message, blocks it completes)] -> batches of at most MAX_BATCH_MESSAGES; a block's messages
    stay in one batch when it fits."""
    out, batch, group = [], [], []
    for item in items:
        group.append(item[:2])
        heavy = len(item) > 2 and item[2]
        if not item[1] and not heavy and len(group) < save_transfer.MAX_BATCH_MESSAGES:
            continue
        if batch and len(batch) + len(group) > save_transfer.MAX_BATCH_MESSAGES:
            out.append(batch)
            batch = []
        batch += group
        group = []
        if heavy:
            out.append(batch)
            batch = []
    if batch and len(batch) + len(group) > save_transfer.MAX_BATCH_MESSAGES:
        out.append(batch)
        batch = []
    batch += group
    if batch:
        out.append(batch)
    return out


class RomTransferServer(save_transfer._Server):
    """Write `image` into the ROM copy, then boot it. `live` are the blocks the console's own session
    runs from, or {game code: blocks}, picked once the console names its cartridge; `boot=False`
    stops before the boot op, with everything written and checked."""

    def __init__(self, image, *, live=(), boot=True, base=None, encoder_process=True, **kwargs):
        # Every hash is taken here, before the link: the session's loop cannot stop for seconds.
        self.blocks = self._raw = blocks_of(image)
        self.hashes = self._raw_hashes = [block_hash(raw) for raw in self.blocks]
        self.base, self._pool = None, None
        if base is not None:
            self.base = blocks_of(base)
            self._base_hashes = [block_hash(raw) for raw in self.base]
            self.base_code = bytes(base[0xAC:0xB0]).decode("ascii", "replace")
            if encoder_process:
                self._pool = concurrent.futures.ProcessPoolExecutor(
                    max_workers=1, initializer=_worker_load, initargs=(bytes(image), bytes(base), self.base_code))
                self._pool.submit(int).result()
            else:
                _worker_load(bytes(image), bytes(base), self.base_code)
                self._pool = _Inline()
        self.live_by_code = live if isinstance(live, dict) else None
        self.live = frozenset(() if self.live_by_code is not None else live)
        self.boot = boot
        self.failed = None
        self.written = 0
        self._tags = itertools.count(1)
        super().__init__(**kwargs)

    def plan(self, hashes):
        """-> (direct writes, staged writes, staging start) given the console's block hashes."""
        moved = sorted(n for n in self.live if n < len(self.blocks))
        start = staging_start(len(moved), len(self.blocks), self.live | {DECODER_BLOCK})
        direct = [(n, raw) for n, raw in enumerate(self.blocks)
                  if n not in self.live and hashes[n] != self.hashes[n]]
        staged = [(start + i, self.blocks[n]) for i, n in enumerate(moved)
                  if hashes[start + i] != self.hashes[n]]
        return direct, staged, start, moved

    def _survey(self):
        """-> the hash of every block of the console's ROM copy."""
        tag, hashes = next(self._tags), []
        runs = -(-BLOCKS // SURVEY_PER_RUN)
        while runs:
            count = min(runs, save_transfer.MAX_PASSES)
            yield self.send(MG_LINKID_CLIENT_SCRIPT, save_transfer.passes_script(count))
            yield self.send(MG_LINKID_RAM_SCRIPT, survey_message(0, BLOCKS, tag))
            for _ in range(count):
                answer = yield ("recv", MG_LINKID_RESPONSE)
                hashes += [int.from_bytes(answer[at:at + 4], "little") for at in range(0, len(answer), 4)]
            runs -= count
        return hashes

    def _write(self, items, total):
        """Send [(message, blocks it completes)] in batches; -> False after ending the session on a
        block that failed."""
        for batch in batches(items):
            yield self.send(MG_LINKID_CLIENT_SCRIPT, save_transfer.batch_script(len(batch)))
            for message, blocks in batch:
                yield self.send(MG_LINKID_NEWS, message)
                if blocks:
                    self.written += blocks
                    self.progress(self.written, total)
            status = yield ("recv", MG_LINKID_RESPONSE)
            failed, first, overflowed = (int.from_bytes(status[at:at + 4], "little") for at in (0, 4, 8))
            if failed or overflowed:
                self.failed = first
                self.outcome = "not-written"
                self.info(f"{failed} blocks read back wrong (the first: 0x{first:03X}), {overflowed} "
                          "overflowed; the ROM copy is not booted.")
                yield from self._end(NOT_WRITTEN, False, SVR_MSG_NOTHING_SENT)
                return False
        return True

    @staticmethod
    def _patched(raw, raw_hashes, code):
        """-> (blocks, hashes) with the application's patches; only the patched blocks are rehashed."""
        blocks = with_wrapper_patches(raw, code)
        return blocks, [h if b is r else block_hash(b) for b, r, h in zip(blocks, raw, raw_hashes)]

    def _sources(self, hashes, start, moved):
        """What each block of the console's copy holds, as the survey shows it."""
        staged = {start + i: n for i, n in enumerate(moved)}
        empty, out = block_hash(_EMPTY), []
        for m in range(BLOCKS):
            if m < len(self.blocks) and hashes[m] == self.hashes[m]:
                out.append(("target", m))
            elif m < len(self.base) and hashes[m] == self._base_patched_hashes[m]:
                out.append(("base", m))
            elif m in staged and hashes[m] == self.hashes[staged[m]]:
                out.append(("target", staged[m]))
            elif hashes[m] == empty:
                out.append(("ff",))
            else:
                out.append(None)
        return out

    def _lz_items(self, hashes, direct, staged, start, moved, build):
        """The decoder into block 0xFFF, then the LZMA stream from the highest block still to write
        down to 0; encoded in another process while survey runs keep the link busy."""
        decoder = THUMB_CODE["rom-lzma"][0].ljust(BLOCK, b"\xff")
        if hashes[DECODER_BLOCK] != block_hash(decoder):
            items = [(message, 0) for message, _ in write_messages([(DECODER_BLOCK, decoder)])]
            if not (yield from self._write(items, 0)):
                return None
        slot_of = {n: start + i for i, n in enumerate(moved)}
        top = max([n for n, _ in direct] + [n for n in moved if slot_of[n] in dict(staged)])
        slots = {n: s for n, s in slot_of.items() if n <= top}
        self.info(f"Encoding blocks 0x{top:03X} to 0 as LZMA against the console's copy.")
        job = self._pool.submit(_worker_encode, self._sources(hashes, start, moved), top, slots)
        tag = next(self._tags)
        while not job.done():
            yield self.send(MG_LINKID_CLIENT_SCRIPT, save_transfer.passes_script(1))
            yield self.send(MG_LINKID_RAM_SCRIPT, survey_message(DECODER_BLOCK, 1, tag))
            yield ("recv", MG_LINKID_RESPONSE)
            tag = next(self._tags)
        chunks = job.result()
        self._pool.shutdown(wait=False)
        items = lz_messages(chunks, top, start, sorted(slots))
        self.info(f"LZMA stream: {sum(len(c[2]) for c in chunks)} bytes in {len(chunks)} chunks, "
                  f"{len(items)} messages.")
        return items

    def _script(self):
        build = yield from self._game_data()
        if build is None:
            yield from self._finished()
        if self.live_by_code is not None:
            if build.game_code not in self.live_by_code:
                self.outcome = "refused"
                self.info(f"Nothing was written: no live blocks are known for {build.game_code}, "
                          "and writing over the code the session runs from would end it.")
                yield from self._end(NOT_WRITTEN, False, SVR_MSG_NOTHING_SENT)
                yield from self._finished()
            self.live = frozenset(self.live_by_code[build.game_code])
        try:
            self.blocks, self.hashes = self._patched(self._raw, self._raw_hashes, build.game_code)
            if self.base is not None:
                if build.game_code != self.base_code:
                    raise ValueError(f"the base ROM is {self.base_code} and the console runs {build.game_code}")
                self.base, self._base_patched_hashes = self._patched(self.base, self._base_hashes, build.game_code)
        except ValueError as exc:
            self.outcome = "refused"
            self.info(f"Nothing was written: {exc}.")
            yield from self._end(NOT_WRITTEN, False, SVR_MSG_NOTHING_SENT)
            yield from self._finished()
        yield self.send(MG_LINKID_CLIENT_SCRIPT, C.client_script(*save_transfer._reporting(MG_LINKID_RAM_SCRIPT)))
        yield self.send(MG_LINKID_RAM_SCRIPT, code(build))
        yield ("recv", MG_LINKID_RESPONSE)

        hashes = yield from self._survey()
        direct, staged, start, moved = self.plan(hashes)
        total = len(direct) + len(staged)
        self.info(f"{len(self.blocks)} blocks: {len(direct)} to write in place, {len(staged)} of the "
                  f"{len(moved)} live ones to stage at 0x{start:03X}; "
                  f"{len(self.blocks) - len(moved) - len(direct)} already there.")
        self.progress(0, total)
        if self.base is not None and total:
            items = yield from self._lz_items(hashes, direct, staged, start, moved, build)
        else:
            items = write_messages(direct + staged)
        if items is None or not (yield from self._write(items, total)):
            yield from self._finished()

        hashes = yield from self._survey()
        direct, staged, _, _ = self.plan(hashes)
        if direct or staged:
            self.failed = (direct + staged)[0][0]
            self.outcome = "not-written"
            self.info(f"The check after writing found {len(direct) + len(staged)} blocks still wrong "
                      f"(the first: 0x{self.failed:03X}); the ROM copy is not booted.")
            yield from self._end(NOT_WRITTEN, False, SVR_MSG_NOTHING_SENT)
            yield from self._finished()
        if not self.boot:
            self.outcome = "written"
            self.info("Every block is written and checked; the boot was not asked for.")
            yield from self._end(_encode_message("The ROM is written.\nNot started.", None),
                                 False, SVR_MSG_NOTHING_SENT)
            yield from self._finished()
        yield self.send(MG_LINKID_CLIENT_SCRIPT, C.client_script((C.CLI_RECV, MG_LINKID_NEWS), C.CLI_RUN_BUFFER_SCRIPT))
        yield self.send(MG_LINKID_NEWS, boot_message(moved, start, len(self.blocks), BLOCKS - len(self.blocks)))
        self.outcome = "booted"
        self.info(f"Boot sent: {len(moved)} live blocks move into place, blocks 0x{len(self.blocks):03X} "
                  "on become 0xFF, then the console soft-resets into the new ROM.")
        yield from self._finished()
