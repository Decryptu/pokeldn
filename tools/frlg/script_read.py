#!/usr/bin/env python3
"""Read a ROM dump as field scripts: disassemble, follow every goto and call, and say what to dump
next.

    ./.venv/bin/python tools/frlg/script_read.py DUMP.bin --base 0x081A7600 [--start ADDR ...]
    ./.venv/bin/python tools/frlg/script_read.py DUMP.bin --base 0x081640EC --std-scripts
    ./.venv/bin/python tools/frlg/script_read.py DUMP.bin --base ADDR --with-every-dump

`--base` is the run's `--dump-address`; without `--start` the dump is walked as back-to-back scripts.
`--with-every-dump` adds one cartridge's other ROM dumps from `scratchpad/`, placed by their launcher
logs. An operand of 0x4000 or more is a variable [decomp:src/event_data.c:235]. docs/frlg_rom.md.
"""
import argparse
import gzip
import os
import pathlib
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.rom import rom_map, scrcmd


def dump_console(tag, log_text):
    """-> which cartridge a run was against: its `--expect-console`, else the tag (`lgNN` is LeafGreen)."""
    match = re.search(r"--expect-console\s+(\w+)", log_text)
    if match:
        return match.group(1).lower()
    return "leafgreen" if re.match(r"^lg\d", tag) else "firered"


def dumps(directory):
    """-> [(tag, console, base, data)] for every ROM dump in `directory`, placed by its launcher log's
    argv. A `--dump-scatter` run comes back as one segment per block, tagged `run[n]`."""
    directory = pathlib.Path(directory)
    found = []
    # The archived logs are `*_launcher.log.gz`: a glob for the plain name matched none and every
    # reader built on this came back empty.
    logs = sorted((directory / "launcher_logs").glob("*_launcher.log*"))
    for log in logs:
        name = log.name[: -len(".gz")] if log.suffix == ".gz" else log.name
        tag = name[: -len("_launcher.log")]
        dump = directory / f"{tag}_dump.bin"
        if not dump.exists():
            continue
        text = (gzip.decompress(log.read_bytes()).decode("utf-8", "replace")
                if log.suffix == ".gz" else log.read_text())
        data, console = dump.read_bytes(), dump_console(tag, text)
        scatter = re.search(r"--dump-scatter\s+([0-9A-Fa-fx,]+)", text)
        if scatter:
            size = int((re.search(r"--dump-size\s+(\d+)", text) or [None, "1024"])[1])
            for index, base in enumerate(int(part, 0) for part in scatter.group(1).split(",")
                                         if part):
                block = data[index * size:(index + 1) * size]
                if block:
                    found.append((f"{tag}[{index}]", console, base, block))
            continue
        match = re.search(r"--dump-address\s+(0x[0-9A-Fa-f]+)", text)
        if match:
            found.append((tag, console, int(match.group(1), 0), data))
    return found


def every_dump(directory, console="firered"):
    """-> [(base, data)] for the dumps of ONE cartridge; `console=None` for all. A mixed image answers
    LeafGreen bodies at FireRed addresses: gSpecials[54] read 0x08083C34, the +0x2C twin."""
    return [(base, data) for _tag, its_console, base, data in dumps(directory)
            if console is None or its_console == console]


def entry_points(data, base, args):
    if args.std_scripts:
        # gStdScripts is ten pointers [decomp:data/event_scripts.s]; a dump of it starts with them.
        return list(struct.unpack_from("<10I", data, rom_map.G_STD_SCRIPTS - base))
    if args.start:
        return args.start
    starts, cursor = [], 0
    while cursor < len(data):
        measured = scrcmd.shape(data, base, cursor)
        if measured is None:
            cursor += 1
            continue
        starts.append(base + cursor)
        while cursor < len(data):
            measured = scrcmd.shape(data, base, cursor)
            if measured is None:
                cursor += 1
                break
            opcode = data[cursor]
            cursor += measured[2]
            if opcode in scrcmd.TERMINATORS:
                break
    return starts


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--base", type=lambda v: int(v, 0), required=True,
                    help="the --dump-address the run used")
    ap.add_argument("--start", type=lambda v: int(v, 0), action="append",
                    help="an entry point to follow; repeatable. Default: walk the whole dump")
    ap.add_argument("--std-scripts", action="store_true",
                    help="the dump IS gStdScripts: follow its ten pointers")
    ap.add_argument("--window", type=lambda v: int(v, 0), default=1024,
                    help="the dump size the plan should propose (default 1024)")
    ap.add_argument("--quiet", action="store_true", help="the plan only, no disassembly")
    ap.add_argument("--with-every-dump", action="store_true",
                    help="add every other ROM dump in scratchpad/, placed by its launcher log")
    ap.add_argument("--dump", action="append", default=[], metavar="PATH@0xADDR",
                    help="add another dump at an address; repeatable")
    ap.add_argument("--scratchpad", default="scratchpad",
                    help="where the dumps and launcher logs live (default scratchpad)")
    ap.add_argument("--console", choices=("firered", "leafgreen", "both"), default="firered",
                    help="which cartridge's dumps --with-every-dump may add (default firered); "
                         "`both` puts two cartridges' code at one set of addresses, so use it only "
                         "to compare them, never to read one")
    args = ap.parse_args()

    data = open(args.path, "rb").read()
    segments = [(args.base, data)]
    if args.with_every_dump:
        segments += every_dump(args.scratchpad,
                               None if args.console == "both" else args.console)
    for spec in args.dump:
        path, _, address = spec.rpartition("@")
        segments.append((int(address, 0), open(path, "rb").read()))
    memory = scrcmd.Memory(segments)

    starts = entry_points(data, args.base, args)
    reached, referenced = scrcmd.follow(memory, starts)

    if not args.quiet:
        for address in sorted(reached):
            print(f"0x{address:08X}:")
            for line in reached[address]:
                print(line)
            print()

    strings = scrcmd.data_pointers(memory, reached)
    if strings and not args.quiet:
        print("the data these scripts point at, as the dumps hold it:")
        for address in sorted(strings):
            why = ", ".join(sorted({kind for kind, _source in strings[address]}))
            text = scrcmd.read_string(memory, address)
            shown = repr(text) if text is not None else "<runs off the end of the dump>"
            print(f"  0x{address:08X}  {why:10s} {shown}")
        print()

    print(f"{len(memory)} bytes in {len(memory.segments)} region"
          f"{'s' if len(memory.segments) != 1 else ''}: {len(starts)} entry points, "
          f"{len(reached)} blocks read, {len(strings)} data addresses held, "
          f"{len(referenced)} wanted and not held")
    if referenced:
        print("\nreached for, and not in this dump:")
        for address in sorted(referenced):
            why = ", ".join(f"{kind} at 0x{source:08X}"
                            for kind, source in sorted(referenced[address]))
            print(f"  0x{address:08X}  {why}")
        print("\nwhat to dump next:")
        for line in scrcmd.dump_plan(referenced, args.window):
            print(line)


if __name__ == "__main__":
    main()
