#!/usr/bin/env python3
"""Read a retail Switch title's RomFS in place, without extracting it.

    ./.venv/bin/python tools/switch/romfs_read.py NSP --nca-offset N --romfs-offset N --title-key HEX --list

hactool's --listromfs segfaults on a sparse NCA. docs/switch_re.md "Reading the RomFS".
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.switch.romfs import SECTOR, CtrReader, RomFs, scan  # noqa: E402,F401


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("container", help="the NSP (or bare NCA) to read in place")
    ap.add_argument("--nca-offset", type=lambda s: int(s, 0), default=0,
                    help="where the program NCA starts inside the container")
    ap.add_argument("--romfs-offset", type=lambda s: int(s, 0), required=True,
                    help="NCA-relative start of the RomFS level-5 data")
    ap.add_argument("--title-key", required=True, help="the DECRYPTED title key, hex")
    ap.add_argument("--ctr-high", default="0000000200000000",
                    help="the section CTR's high 8 bytes, hex")
    ap.add_argument("--list", action="store_true", help="print every file")
    ap.add_argument("--grep", help="only paths containing this (case-insensitive)")
    ap.add_argument("--extract", help="path of one file to write out")
    ap.add_argument("--out", help="where --extract writes")
    ap.add_argument("--search", action="append", default=[],
                    help="hex bytes to look for in the file DATA; repeatable")
    ap.add_argument("--search-text", action="append", default=[],
                    help="ASCII to look for in the file DATA; repeatable")
    ap.add_argument("--search-in", help="comma-separated path substrings to limit --search")
    args = ap.parse_args(argv)

    reader = CtrReader(args.container, args.nca_offset,
                       bytes.fromhex(args.title_key), bytes.fromhex(args.ctr_high))
    romfs = RomFs(reader, args.romfs_offset)
    print(f"romfs ok: header_size 0x50, file_data at "
          f"{args.romfs_offset + romfs.file_data_off:#x}", file=sys.stderr)

    if args.list or args.grep:
        want = args.grep.lower() if args.grep else None
        total = 0
        shown = 0
        for path, off, size in romfs.walk():
            total += 1
            if want and want not in path.lower():
                continue
            shown += 1
            print(f"{size:12d}  {off:#014x}  {path}")
        print(f"{total} files, {shown} shown", file=sys.stderr)

    if args.extract:
        for path, off, size in romfs.walk():
            if path == args.extract:
                data = romfs.read_file(off, size)
                out = args.out or path.rsplit("/", 1)[-1]
                with open(out, "wb") as fh:
                    fh.write(data)
                print(f"{len(data)} bytes -> {out}", file=sys.stderr)
                break
        else:
            sys.exit(f"no such file in the romfs: {args.extract}")

    if args.search or args.search_text:
        needles = [bytes.fromhex(h) for h in args.search]
        needles += [t.encode() for t in args.search_text]
        names = [s.strip().lower() for s in args.search_in.split(",")] if args.search_in else None
        hits = 0
        for path, off, needle in scan(romfs, needles, names):
            hits += 1
            print(f"HIT {needle.hex()} {path} +{off:#x}", flush=True)
        print(f"{hits} hits", file=sys.stderr)

    reader.close()


if __name__ == "__main__":
    main()
