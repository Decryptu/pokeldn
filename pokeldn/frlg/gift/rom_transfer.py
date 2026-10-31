"""Write a ROM image into a FireRed or LeafGreen console's running ROM copy over Mystery Gift, then
boot it, through asm/rom-transfer.s [docs/rse_switch_build.md, Delivery without Atmosphere]. The
server speaks MysteryGiftServer's contract to HostMysteryGiftEngine, as save_transfer's servers do.

The session runs the cartridge's own link and Mystery Gift code from the ROM copy it overwrites, so
the blocks that code needs (`live`) are written last: their new bytes go to staging blocks past both
images, and the boot op moves them into place with interrupts off, fills the tail with 0xFF and
soft-resets. A cut session resumes: every session starts by hashing the console's blocks."""

import itertools

from pokeldn.frlg.gift import save_transfer
from pokeldn.frlg.gift.mg_server import SVR_MSG_NOTHING_SENT, _encode_message
from pokeldn.frlg.gift.mystery_gift import (
    MG_LINK_BUFFER_SIZE, MG_LINKID_CLIENT_SCRIPT, MG_LINKID_NEWS, MG_LINKID_RAM_SCRIPT,
    MG_LINKID_RESPONSE,
)
from pokeldn.frlg.rom.buffer_payloads import PAYLOADS
from pokeldn.frlg.save import sav

C = save_transfer.C
BLOCK = 0x1000
BLOCKS = 0x1000                        # the fold reaches 16 MB [docs/frlg_rom.md, The flash sector path]
OP_DATA, OP_SURVEY, OP_BOOT = 1, 3, 4
DATA_HEADER = 12
BOOT_HEADER = 16
SURVEY_PER_RUN = 32                    # 128 KB hashed per frame; 32 words answered
MAX_BOOT_BLOCKS = (MG_LINK_BUFFER_SIZE - BOOT_HEADER) // 2
_EMPTY = b"\xff" * BLOCK

NOT_WRITTEN = _encode_message("The ROM could not be written.\nNothing was started.", None)


def code():
    return PAYLOADS["rom-transfer"][0]


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


def batches(writes):
    """[(block, raw)] -> [[messages]] of at most save_transfer.MAX_BATCH_MESSAGES each."""
    out, batch = [], []
    for n, raw in writes:
        messages = block_messages(n, raw)
        if batch and len(batch) + len(messages) > save_transfer.MAX_BATCH_MESSAGES:
            out.append(batch)
            batch = []
        batch += messages
    if batch:
        out.append(batch)
    return out


class RomTransferServer(save_transfer._Server):
    """Write `image` into the ROM copy, then boot it. `live` are the blocks the console's own session
    runs from; `boot=False` stops before the boot op, with everything written and checked."""

    def __init__(self, image, *, live=(), boot=True, **kwargs):
        self.blocks = blocks_of(image)
        self.hashes = [block_hash(raw) for raw in self.blocks]
        self.live = frozenset(live)
        self.boot = boot
        self.failed = None
        self.written = 0
        self._tags = itertools.count(1)
        super().__init__(**kwargs)

    def plan(self, hashes):
        """-> (direct writes, staged writes, staging start) given the console's block hashes."""
        moved = sorted(n for n in self.live if n < len(self.blocks))
        start = staging_start(len(moved), len(self.blocks), self.live)
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

    def _write(self, writes, total):
        """Send the writes in batches; -> False after ending the session on a block that failed."""
        for batch in batches(writes):
            yield self.send(MG_LINKID_CLIENT_SCRIPT, save_transfer.batch_script(len(batch)))
            for message in batch:
                yield self.send(MG_LINKID_NEWS, message)
                if message[5] & 1:
                    self.written += 1
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

    def _script(self):
        build = yield from self._game_data()
        if build is None:
            yield from self._finished()
        yield self.send(MG_LINKID_CLIENT_SCRIPT, C.client_script(*save_transfer._reporting(MG_LINKID_RAM_SCRIPT)))
        yield self.send(MG_LINKID_RAM_SCRIPT, code())
        yield ("recv", MG_LINKID_RESPONSE)

        hashes = yield from self._survey()
        direct, staged, start, moved = self.plan(hashes)
        total = len(direct) + len(staged)
        self.info(f"{len(self.blocks)} blocks: {len(direct)} to write in place, {len(staged)} of the "
                  f"{len(moved)} live ones to stage at 0x{start:03X}; "
                  f"{len(self.blocks) - len(moved) - len(direct)} already there.")
        self.progress(0, total)
        if not (yield from self._write(direct + staged, total)):
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
