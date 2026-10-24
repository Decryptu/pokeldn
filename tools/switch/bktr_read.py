#!/usr/bin/env python3
"""Read a game update's RomFS in place: a BKTR section over the base game's RomFS.

    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp --list
    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp \\
        --extract /Data/Managed/Metadata/global-metadata.dat --out global-metadata.dat

Layouts are hactool's (nca.h, bktr.c). docs/switch_re.md "Reading a game update's RomFS".
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.switch.container import (  # noqa: E402,F401
    BUCKET, RELOC_ENTRY, SUBSEC_ENTRY, BktrSection, load_keys, open_update_romfs, program_nca)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("update", help="the update NSP/XCI, read in place")
    ap.add_argument("--base", required=True, help="the base game's NSP/XCI, read in place")
    ap.add_argument("--keys", default=os.path.expanduser("~/.switch/prod.keys"))
    ap.add_argument("--nca", help="only the update NCA whose name starts with this")
    ap.add_argument("--base-nca", help="only the base NCA whose name starts with this")
    ap.add_argument("--list", action="store_true", help="print every file")
    ap.add_argument("--grep", help="only paths containing this (case-insensitive)")
    ap.add_argument("--extract", help="path of one file to write out")
    ap.add_argument("--out", help="where --extract writes")
    args = ap.parse_args(argv)

    keys = load_keys(args.keys)
    virt, romfs = open_update_romfs(args.update, args.base, keys, args.nca, args.base_nca)
    print(f"romfs ok: header_size 0x50, virtual section {virt.size:,} bytes, "
          f"{len(virt.reloc[0])} relocation buckets, {len(virt.subsec[0])} subsection buckets",
          file=sys.stderr)

    if args.list or args.grep:
        want = args.grep.lower() if args.grep else None
        total = shown = 0
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
