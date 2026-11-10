#!/usr/bin/env python3
"""Build a minimal NRO and the NRR that registers its SHA-256.

    ./.venv/bin/python tools/switch/nro.py text.bin out.nro out.nrr [--title-id 0x...]

The NRO holds one text segment at file offset 0x1000; ro and data are empty, bss is zero. The NRR
is one 4 KB page with the header at 0 and the hash at 0x350. `ldr:ro` `LoadNrr` registers the hash
before `LoadNro` accepts the NRO.
"""
import argparse
import hashlib
import struct

NRO_MAGIC = 0x304F524E
NRR_MAGIC = 0x3052524E
TEXT_OFFSET = 0x1000
PAGE = 0x1000
NRR_SIZE = 0x1000
HASH_OFFSET = 0x350


def build_nro(text, text_offset=TEXT_OFFSET):
    """-> a page-aligned NRO whose single text segment starts at `text_offset`."""
    text_size = (len(text) + PAGE - 1) & ~(PAGE - 1)
    if text_size == 0:
        text_size = PAGE
    total = text_offset + text_size
    nro = bytearray(total)
    struct.pack_into("<II", nro, 0x00, 0, 0)                 # NroStart: unused, mod offset
    struct.pack_into("<I", nro, 0x10, NRO_MAGIC)
    struct.pack_into("<I", nro, 0x14, 0)
    struct.pack_into("<I", nro, 0x18, total)
    struct.pack_into("<I", nro, 0x1C, 0)
    struct.pack_into("<II", nro, 0x20, text_offset, text_size)
    struct.pack_into("<II", nro, 0x28, total, 0)             # ro: file offset, size
    struct.pack_into("<II", nro, 0x30, total, 0)             # data
    struct.pack_into("<I", nro, 0x38, 0)                     # bss
    nro[text_offset:text_offset + len(text)] = text
    return bytes(nro)


def build_nrr(nro, title_id=0x01004B3023412000, size=NRR_SIZE):
    """-> a one-page NRR registering `nro`'s SHA-256."""
    if size & (PAGE - 1) or size < HASH_OFFSET + 0x20:
        raise ValueError("the NRR size must be page-aligned and hold the hash")
    nrr = bytearray(size)
    struct.pack_into("<I", nrr, 0x00, NRR_MAGIC)
    struct.pack_into("<I", nrr, 0x04, 0)
    struct.pack_into("<Q", nrr, 0x330, title_id)
    struct.pack_into("<I", nrr, 0x338, size)
    struct.pack_into("<B", nrr, 0x33C, 0)
    struct.pack_into("<I", nrr, 0x340, HASH_OFFSET)
    struct.pack_into("<I", nrr, 0x344, 1)
    nrr[HASH_OFFSET:HASH_OFFSET + 0x20] = hashlib.sha256(nro).digest()
    return bytes(nrr)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("text")
    ap.add_argument("nro")
    ap.add_argument("nrr")
    ap.add_argument("--title-id", type=lambda v: int(v, 0), default=0x01004B3023412000)
    args = ap.parse_args()
    nro = build_nro(open(args.text, "rb").read())
    nrr = build_nrr(nro, args.title_id)
    open(args.nro, "wb").write(nro)
    open(args.nrr, "wb").write(nrr)
    print(f"{args.nro}: {len(nro)} bytes  sha256 {hashlib.sha256(nro).hexdigest()}")
    print(f"{args.nrr}: {len(nrr)} bytes")


if __name__ == "__main__":
    main()
