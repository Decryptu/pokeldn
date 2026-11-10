#!/usr/bin/env python3
"""Native code in the FRLG title through the Sloop component, driven by an emulator's GDB stub.

    ./.venv/bin/python tools/frlg/sloop_native.py asm PAYLOAD.s --run
    ./.venv/bin/python tools/frlg/sloop_native.py stage PAYLOAD.bin
    ./.venv/bin/python tools/frlg/sloop_native.py map
    ./.venv/bin/python tools/frlg/sloop_native.py ldr [--source block|heap]

The stage writes the title's component vtable and the last 4 KB of the ROM copy, enters a Thumb
stub (`swi 0x40 ; bkpt #0x52 ; b .`) in EWRAM, and runs one AArch64 payload. It restores the
component, the block and the guest CPU when the payload returns; a payload that does not return
leaves the title frozen. The `map` probe reads the alias region and maps one page with
`svcMapPhysicalMemory`. The `ldr` probe initializes `ldr:ro` with the current-process pseudo-handle,
loads a one-segment NRO and reports `LoadNro`'s result. `--source heap` copies the NRO to an
`_Znwm` allocation; that path ended this emulator in a data abort.

The component sits at ROM + 0x1000000, the block at ROM + 0x3F6000, and the EWRAM backing at a
stable title VA. See NOTES.console-runtime-research.local.md, "Native execution layer", for the
addresses and the measurement.
"""
import argparse
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "switch"))
from assemble import assemble  # noqa: E402
from gdb_remote import GdbRemote  # noqa: E402
from nro import build_nro, build_nrr  # noqa: E402

ROM = 0x661F9FA000
COMPONENT = ROM + 0x1000000
BLOCK = ROM + 0x3F6000
EWRAM = 0x655E61E000
STUB_GBA = 0x0203FC00
STUB = EWRAM + (STUB_GBA - 0x02000000)
VTABLE_LEN = 0xF0
THUMB = struct.pack("<HHH", 0xDF40, 0xBE52, 0xE7FE)   # swi 0x40 ; bkpt #0x52 ; b .
BRK = 0xD4201320


def map_source():
    return f'''
.text
.global _start
_start:
    ldr x19, =0x{BLOCK:x}
    mov w0, #0x4D50
    movk w0, #0x3031, lsl #16
    str w0, [x19, #0x300]
    ldr x2, =0xFFFF8001
    mov x0, #0
    mov x1, #2
    mov x3, #0
    svc #0x29
    str x0, [x19, #0x310]
    str x1, [x19, #0x318]
    mov x21, x1
    ldr x2, =0xFFFF8001
    mov x0, #0
    mov x1, #3
    mov x3, #0
    svc #0x29
    str x0, [x19, #0x320]
    str x1, [x19, #0x328]
    add x22, x21, #0x100000
    str x22, [x19, #0x358]
    mov x0, x22
    mov x1, #0x1000
    svc #0x2C
    str x0, [x19, #0x330]
    cbnz x0, 1f
    ldr w9, =0xCAFEBABE
    str w9, [x22]
    ldr w9, [x22]
    str w9, [x19, #0x338]
    add x0, x19, #0x380
    add x1, x19, #0x3B0
    mov x2, x22
    svc #0x06
    str x0, [x19, #0x340]
    mov x0, x22
    mov x1, #0x1000
    svc #0x2D
    str x0, [x19, #0x348]
1:
    mov w9, #0x4D45
    movk w9, #0x4E44, lsl #16
    str w9, [x19, #0x304]
    ret
'''


def ldr_source(nro_addr, nrr_addr, heap=False):
    heap_code = ""
    nro_load = f"    ldr x9, =0x{nro_addr:x}"
    if heap:
        heap_code = f'''
    ldr x9, =0x86D9010
    ldr x9, [x9]
    mov x0, #0x2000
    blr x9
    mov x26, x0
    str x26, [x19, #0x378]
    add x10, x19, #0x1000
    mov x11, x26
    mov w12, #0x200
1:
    ldp x13, x14, [x10], #16
    stp x13, x14, [x11], #16
    subs w12, w12, #1
    b.ne 1b
'''
        nro_load = "    mov x9, x26"
    return f'''
.text
.global _start
_start:
    ldr x19, =0x{BLOCK:x}
    ldr x9, =0x003A6D73
    str x9, [x19, #0x3C0]
    mov x0, #0
    add x1, x19, #0x3C0
    svc #0x1F
    str x0, [x19, #0x308]
    mov x24, x1
    str x24, [x19, #0x310]

    mrs x20, tpidrro_el0

    // sm Initialize
    stp xzr, xzr, [x20]
    stp xzr, xzr, [x20, #0x10]
    stp xzr, xzr, [x20, #0x20]
    stp xzr, xzr, [x20, #0x30]
    stp xzr, xzr, [x20, #0x40]
    mov w9, #4
    str w9, [x20]
    mov w9, #6
    str w9, [x20, #4]
    movz w9, #0x4653
    movk w9, #0x4943, lsl #16
    str w9, [x20, #0x10]
    mov x0, x24
    svc #0x21
    str x0, [x19, #0x318]
    ldr w9, [x20, #0x18]
    str w9, [x19, #0x31C]

    // sm GetService("ldr:ro")
    stp xzr, xzr, [x20]
    stp xzr, xzr, [x20, #0x10]
    stp xzr, xzr, [x20, #0x20]
    stp xzr, xzr, [x20, #0x30]
    stp xzr, xzr, [x20, #0x40]
    mov w9, #4
    str w9, [x20]
    mov w9, #8
    str w9, [x20, #4]
    movz w9, #0x4653
    movk w9, #0x4943, lsl #16
    str w9, [x20, #0x10]
    mov w9, #1
    str w9, [x20, #0x18]
    ldr x9, =0x00006F723A72646C
    str x9, [x20, #0x20]
    mov x0, x24
    svc #0x21
    str x0, [x19, #0x320]
    ldr w9, [x20, #0x18]
    str w9, [x19, #0x324]
    ldr w9, [x20, #0x8]
    str w9, [x19, #0x328]
    ldr w9, [x20, #0xC]
    str w9, [x19, #0x32C]
    mov x25, x9

    // current pid
    ldr x1, =0xFFFF8001
    svc #0x24
    str x0, [x19, #0x340]
    str x1, [x19, #0x348]

    // ldr:ro Initialize(PID descriptor, 0xFFFF8001)
    stp xzr, xzr, [x20]
    stp xzr, xzr, [x20, #0x10]
    stp xzr, xzr, [x20, #0x20]
    stp xzr, xzr, [x20, #0x30]
    stp xzr, xzr, [x20, #0x40]
    mov w9, #4
    str w9, [x20]
    mov w9, #8
    movk w9, #0x8000, lsl #16
    str w9, [x20, #4]
    mov w9, #3
    str w9, [x20, #0x8]
    str x1, [x20, #0xC]
    ldr w9, =0xFFFF8001
    str w9, [x20, #0x14]
    movz w9, #0x4653
    movk w9, #0x4943, lsl #16
    str w9, [x20, #0x20]
    mov w9, #4
    str w9, [x20, #0x28]
    mov x0, x25
    svc #0x21
    str x0, [x19, #0x350]
    ldr w9, [x20, #0x18]
    str w9, [x19, #0x354]
    ldr w9, [x20, #0x8]
    str w9, [x19, #0x358]
    ldr w9, [x20, #0xC]
    str w9, [x19, #0x35C]

    // ldr:ro LoadNrr(0, nrr, 0x1000)
    stp xzr, xzr, [x20]
    stp xzr, xzr, [x20, #0x10]
    stp xzr, xzr, [x20, #0x20]
    stp xzr, xzr, [x20, #0x30]
    stp xzr, xzr, [x20, #0x40]
    mov w9, #4
    str w9, [x20]
    mov w9, #12
    str w9, [x20, #4]
    movz w9, #0x4653
    movk w9, #0x4943, lsl #16
    str w9, [x20, #0x10]
    mov w9, #2
    str w9, [x20, #0x18]
    ldr x9, =0x{nrr_addr:x}
    str x9, [x20, #0x28]
    mov w9, #0x1000
    str w9, [x20, #0x30]
    mov x0, x25
    svc #0x21
    str x0, [x19, #0x360]
    ldr w9, [x20, #0x18]
    str w9, [x19, #0x364]

    {heap_code}
    // ldr:ro LoadNro(0, nro, 0x2000, 0, 0)
    stp xzr, xzr, [x20]
    stp xzr, xzr, [x20, #0x10]
    stp xzr, xzr, [x20, #0x20]
    stp xzr, xzr, [x20, #0x30]
    stp xzr, xzr, [x20, #0x40]
    stp xzr, xzr, [x20, #0x50]
    mov w9, #4
    str w9, [x20]
    mov w9, #16
    str w9, [x20, #4]
    movz w9, #0x4653
    movk w9, #0x4943, lsl #16
    str w9, [x20, #0x10]
    str wzr, [x20, #0x18]
    {nro_load}
    str x9, [x20, #0x28]
    mov w9, #0x2000
    str w9, [x20, #0x30]
    mov x0, x25
    svc #0x21
    str x0, [x19, #0x368]
    ldr w9, [x20, #0x18]
    str w9, [x19, #0x36C]
    ldr x9, [x20, #0x20]
    str x9, [x19, #0x370]
    mov w9, #0x4C44
    movk w9, #0x2121, lsl #16
    str w9, [x19, #0x300]
    ret
'''


def nro_text():
    return f'''
.text
.global _start
_start:
    ldr x19, =0x{BLOCK:x}
    mov w9, #0x524E
    movk w9, #0x214F, lsl #16
    str w9, [x19, #0x380]
    ret
'''


class Stage:
    """One native payload entered through the component's vtable."""

    def __init__(self, g, rom=ROM):
        self.g = g
        self.rom = rom
        self.component = rom + 0x1000000
        self.block = rom + 0x3F6000
        self.cpu = g.u64(self.component + 0xE0) + 0xB20

    def run(self, payload=None, image=None, span=0x1000, wait=1.0):
        g = self.g
        print("interrupt", (g.interrupt() or b"").decode(errors="replace"))
        if g.read(self.rom, 4) != b"\x7f\x00\x00\xea":
            raise SystemExit(f"no ROM copy at 0x{self.rom:x}")
        comp = g.read(self.component, 8)
        vt = struct.unpack("<Q", comp)[0]
        if not 0x8506000 <= vt < 0x8700000:
            raise SystemExit(f"unexpected component vtable 0x{vt:x}")
        cpu = self.cpu
        regs = g.read(cpu + 0x48, 0x44)
        stub = g.read(STUB, len(THUMB))
        block = g.read(self.block, span)
        vtable = g.read(vt, VTABLE_LEN)
        old_pc, old_cpsr = struct.unpack_from("<II", regs, 0x84 - 0x48)
        try:
            if image is None:
                image = bytearray(struct.pack("<I", BRK) * (span // 4))
                image[0x400:0x400 + len(payload)] = payload
            else:
                image = bytearray(image)
                if len(image) < span:
                    image += bytes(span - len(image))
            image[0x108:0x108 + VTABLE_LEN] = vtable
            struct.pack_into("<Q", image, 0x1A0, self.block + 0x400)
            g.write(self.block, bytes(image))
            g.write(self.component, struct.pack("<Q", self.block + 0x108))
            g.write(STUB, THUMB)
            g.write(cpu + 0x84, struct.pack("<I", STUB_GBA))
            g.write(cpu + 0x88, struct.pack("<I", (old_cpsr & ~0x20) | 0x20))
            g.cont()
            time.sleep(wait)
            print("stop", (g.interrupt() or b"").decode(errors="replace"))
            now_pc, now_cpsr = struct.unpack("<II", g.read(cpu + 0x84, 8))
            print(f"guest pc 0x{now_pc:x} cpsr 0x{now_cpsr:x} (was 0x{old_pc:x} 0x{old_cpsr:x})")
            return g.read(self.block, span)
        finally:
            try:
                g.write(STUB, stub)
                g.write(cpu + 0x48, regs)
                g.write(self.component, comp)
                g.write(self.block, block)
            except Exception as e:
                print("restore failed:", e)
            try:
                g.cont()
            except Exception:
                pass


def report_map(result):
    def u32(off):
        return struct.unpack_from("<I", result, off)[0]
    def u64(off):
        return struct.unpack_from("<Q", result, off)[0]
    print(f"GetInfo(2) result 0x{u32(0x310):x} -> 0x{u64(0x318):x}")
    print(f"GetInfo(3) result 0x{u32(0x320):x} -> 0x{u64(0x328):x}")
    print(f"MapPhysicalMemory(0x{u64(0x358):x}, 0x1000) -> 0x{u32(0x330):x}")
    if u32(0x330) == 0:
        print(f"pattern 0x{u32(0x338):08x}")
        print(f"QueryMemory -> 0x{u32(0x340):x}")
        info = result[0x380:0x3A8]
        base, size, state, perm = (struct.unpack_from("<Q", info, i)[0] for i in (0, 8, 0x10, 0x18))
        print(f"  base 0x{base:x} size 0x{size:x} state 0x{state:x} perm 0x{perm:x}")
        print(f"UnmapPhysicalMemory -> 0x{u32(0x348):x}")


def report_ldr(result):
    def u32(off):
        return struct.unpack_from("<I", result, off)[0]
    def u64(off):
        return struct.unpack_from("<Q", result, off)[0]
    print(f"sm handle 0x{u64(0x310):x}")
    print(f"sm Initialize -> 0x{u32(0x318):x} service 0x{u32(0x31C):x}")
    print(f"GetService(ldr:ro) -> 0x{u32(0x320):x} service 0x{u32(0x324):x} handle 0x{u32(0x32C):x}")
    print(f"GetProcessId -> 0x{u32(0x340):x} pid 0x{u64(0x348):x}")
    print(f"ldr:ro Initialize -> 0x{u32(0x350):x} service 0x{u32(0x354):x}")
    print(f"LoadNrr -> 0x{u32(0x360):x} service 0x{u32(0x364):x}")
    print(f"LoadNro -> 0x{u32(0x368):x} service 0x{u32(0x36C):x} mapped 0x{u64(0x370):x}")
    if u64(0x378):
        print(f"heap NRO 0x{u64(0x378):x}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=55556)
    ap.add_argument("--rom-base", type=lambda v: int(v, 0), default=ROM)
    ap.add_argument("--wait", type=float, default=1.0)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sa = sub.add_parser("asm", help="assemble a source and optionally run it")
    sa.add_argument("source")
    sa.add_argument("--run", action="store_true")
    sa.add_argument("--out")
    st = sub.add_parser("stage", help="run a raw AArch64 payload")
    st.add_argument("payload")
    st.add_argument("--span", type=lambda v: int(v, 0), default=0x1000)
    st.add_argument("--dump-start", type=lambda v: int(v, 0), default=0x300)
    st.add_argument("--dump-len", type=lambda v: int(v, 0), default=0xC0)
    sub.add_parser("map", help="svcMapPhysicalMemory probe")
    ld = sub.add_parser("ldr", help="ldr:ro Initialize/LoadNrr/LoadNro probe")
    ld.add_argument("--source", choices=("block", "heap"), default="block")
    args = ap.parse_args()

    g = GdbRemote(args.host, args.port)
    stage = Stage(g, args.rom_base)
    try:
        if args.cmd == "asm":
            payload = assemble(open(args.source).read())
            if args.out:
                open(args.out, "wb").write(payload)
                print(f"{args.out}: {len(payload)} bytes")
            if args.run:
                result = stage.run(payload)
                for off in range(0x300, 0x300 + 0x60, 0x10):
                    print(f"  block+{off:03x}  {result[off:off + 0x10].hex()}")
        elif args.cmd == "stage":
            result = stage.run(open(args.payload, "rb").read(), span=args.span)
            for off in range(args.dump_start, args.dump_start + args.dump_len, 0x10):
                print(f"  block+{off:03x}  {result[off:off + 0x10].hex()}")
        elif args.cmd == "map":
            result = stage.run(assemble(map_source()))
            report_map(result)
        elif args.cmd == "ldr":
            text = assemble(nro_text())
            nro = build_nro(text)
            nrr = build_nrr(nro)
            image = bytearray(0x4000)
            image[0x1000:0x1000 + len(nro)] = nro
            image[0x3000:0x3000 + len(nrr)] = nrr
            heap = args.source == "heap"
            payload = assemble(ldr_source(BLOCK + 0x1000, BLOCK + 0x3000, heap))
            image[0x400:0x400 + len(payload)] = payload
            result = stage.run(None, image=image, span=0x4000)
            report_ldr(result)
    finally:
        g.close()


if __name__ == "__main__":
    main()
