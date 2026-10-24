#!/usr/bin/env python3
"""List and extract files from a Trinity packed file system (Scarlet and Violet).

    ./.venv/bin/python tools/switch/trpfs_read.py --romfs-dir DIR --list [--grep personal]
    ./.venv/bin/python tools/switch/trpfs_read.py --update UPDATE.nsp --base BASE.xci --keys KEYS \\
        --nca 7e5b9bbf --base-nca d8c3a585 --extract avalon/data/personal_array.bin --out-dir OUT

`arc/data.trpfd` names the files (FNV-1a 64 path hashes) and the packs; `arc/data.trpfs` holds the
packs. An entry of compression type 3 is Oodle: it runs the title's own OodleLZ_Decompress from its
main image under unicorn (`--image`, `--oodle`; Scarlet 4.0.0 `0xcc8750`). docs/za.md "The personal table".
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trpfs import FNV_BASIS, FNV_PRIME, OODLE, Fb, Oodle, Trpfs, fnv1a64  # noqa: E402,F401
import trpfs  # noqa: E402


def Source(args):
    """arc/data.trpfd and arc/data.trpfs from --romfs-dir, or read in place from the containers."""
    if args.romfs_dir:
        return trpfs.Source.directory(args.romfs_dir)
    from pokeldn.switch.container import load_keys, open_update_romfs
    _virt, romfs = open_update_romfs(args.update, args.base, load_keys(args.keys), args.nca, args.base_nca)
    return trpfs.Source.romfs(romfs)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--romfs-dir", help="a directory holding arc/data.trpfd and arc/data.trpfs")
    ap.add_argument("--update", help="the update NSP, read in place with bktr_read.py")
    ap.add_argument("--base", help="the base game's XCI/NSP")
    ap.add_argument("--keys", default=os.path.expanduser("~/.switch/prod.keys"))
    ap.add_argument("--nca", help="update Program NCA name prefix")
    ap.add_argument("--base-nca", help="base Program NCA name prefix")
    ap.add_argument("--image", default="scratchpad/sv/main.bin", help="main image for Oodle")
    ap.add_argument("--oodle", type=lambda s: int(s, 0), default=0xCC8750,
                    help="OodleLZ_Decompress in --image (Scarlet 4.0.0 0xcc8750, Z-A 2.0.2 0x1a9c9e0)")
    ap.add_argument("--list", action="store_true", help="print the packs and file counts")
    ap.add_argument("--grep", help="with --list: only pack names containing this")
    ap.add_argument("--extract", nargs="*", default=[], help="paths or 0x hashes to extract")
    ap.add_argument("--out-dir", default=".", help="where --extract writes, under the file's path")
    args = ap.parse_args(argv)
    if not args.romfs_dir and not (args.update and args.base):
        ap.error("give --romfs-dir, or --update and --base")

    fs = Trpfs(Source(args))
    print(f"{len(fs.file_hashes)} files, {len(fs.pack_names)} packs", file=sys.stderr)
    if args.list:
        counts = {}
        for p in fs.file_pack:
            counts[p] = counts.get(p, 0) + 1
        for i, name in enumerate(fs.pack_names):
            if args.grep and args.grep.lower() not in name.lower():
                continue
            print(f"{i:6d}  {fs.pack_size[i]:12d}  {counts.get(i, 0):6d}  {name}")
    oodle = Oodle(args.image, args.oodle) if args.extract else None
    for want in args.extract:
        h = int(want, 16) if want.startswith("0x") else fnv1a64(want)
        if h not in fs.index:
            sys.exit(f"{want}: hash {h:016x} not in data.trpfd")
        p, ctype, dsize, data = fs.entry(h)
        out = fs.read(h, oodle)
        dest = os.path.join(args.out_dir, want if not want.startswith("0x") else f"{h:016x}.bin")
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(out)
        print(f"{want}  hash {h:016x}  pack {p} {fs.pack_names[p]}  type {ctype}  "
              f"{len(data)} -> {len(out)} bytes -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
