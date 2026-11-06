#!/usr/bin/env python3
"""Run a whole LZMA ROM stream through asm/rom-transfer.s under unicorn and log each frame's work
[docs/rse_switch_build.md, The LZMA stream]. Message for message, it is what the session sends.

    ./.venv/bin/python tools/rse/rom_stream_cost.py ROM --base scratchpad/frlg_languages/FireRed_e.gba \
        --out scratchpad/rom_stream/cost.jsonl

One line per message: index, op, blocks done so far, frames (calls) it took, the most instructions
in one call and the total. Nothing here touches a console.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.gift import rom_transfer as rt  # noqa: E402
from pokeldn.frlg.rom import buffer_script  # noqa: E402
from pokeldn.frlg.rom.buffer_payloads import THUMB_CODE  # noqa: E402


COUNT_LIMIT = 1_000_000     # past the session's own limit: this tool measures a heavy call and goes on


def stream(image, base, code, console=b""):
    """-> (the copy's bytes with decoder and order table written, emission order, [lz_messages]).
    `console`: what the copy holds when the host has no `base`."""
    server = rt.RomTransferServer(image, live=rt.live_blocks()[code], base=base, encoder_process=False)
    server.blocks, server.hashes = server._patched(server._raw, server._raw_hashes, code)
    if server.base:
        server.base, server._base_patched_hashes = server._patched(server.base, server._base_hashes, code)
    empty = b"\xff" * rt.BLOCK
    held = server.base or rt.with_wrapper_patches(rt.blocks_of(console), code)
    copy = [held[n] if n < len(held) else empty for n in range(rt.BLOCKS)]
    hashes = [rt.block_hash(raw) for raw in copy]
    direct, staged, start, moved = server.plan(hashes)
    slot_of = {n: start + i for i, n in enumerate(moved)}
    top = max([n for n, _ in direct] + [n for n in moved if slot_of[n] in dict(staged)])
    slots = {n: s for n, s in slot_of.items() if n <= top}
    order, chunks = rt._worker_encode(code, server._sources(hashes, start, moved), top, slots)
    table = b"".join(b.to_bytes(2, "little") for b in order).ljust(len(rt.ORDER_BLOCKS) * rt.BLOCK, b"\xff")
    for k, n in enumerate(rt.ORDER_BLOCKS):
        copy[n] = table[k * rt.BLOCK:(k + 1) * rt.BLOCK]
    copy[rt.DECODER_BLOCK] = THUMB_CODE["rom-lzma"][0].ljust(rt.BLOCK, b"\xff")
    return b"".join(copy), order, rt.lz_messages(chunks, 0, start, sorted(slots))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--base", required=True, help="the console's own cartridge ROM, or none")
    ap.add_argument("--console", help="with --base none: the ROM the console's copy holds")
    ap.add_argument("--code", default="BPRE")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.image, "rb") as handle:
        image = handle.read()
    base = b""
    if args.base != "none":
        with open(args.base, "rb") as handle:
            base = handle.read()
    console = b""
    if args.console:
        with open(args.console, "rb") as handle:
            console = handle.read()
    rom, order, messages = stream(image, base, args.code, console)
    print(f"{len(messages)} messages, {sum(len(m[0]) for m in messages)} bytes, {len(order)} blocks", flush=True)
    machine = buffer_script.session_machine(rt.code(), memory={buffer_script.ROM_BASE: rom})
    machine.call()
    done = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for index, (message, blocks, *quiet) in enumerate(messages):
            machine.load(message, param=0)
            calls, peak, total = 0, 0, 0
            while True:
                run = machine.call(instruction_limit=COUNT_LIMIT)
                calls, peak, total = calls + 1, max(peak, run.instructions), total + run.instructions
                if run.done:
                    break
            done += blocks
            out.write(json.dumps({"i": index, "op": message[4], "len": len(message), "blocks": done,
                                  "quiet": quiet[0] if quiet else 0, "calls": calls, "peak": peak,
                                  "total": total}) + "\n")
            if index % 500 == 0:
                print(index, done, flush=True)
    print("failed blocks:", int.from_bytes(machine.uc.mem_read(0x0201D800, 4), "little"))


if __name__ == "__main__":
    main()
