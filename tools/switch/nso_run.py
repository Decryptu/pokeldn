#!/usr/bin/env python3
"""Run a function out of a title's main NSO image under unicorn, with its nnSdk imports intercepted.

An NSO's imported symbols are resolved at load time, so in the static image every PLT stub jumps
through a zero GOT slot. This maps the stubs by name (nso_imports) and services the handful a
self-contained routine needs in Python. Used to execute the game's own validators offline before
spending a hardware run; bin/swsh_gift_host.py runs the Wonder Card validator with it."""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nso_imports import imports
from nso_relocs import relatives
from unicorn import *
from unicorn.arm64_const import *

SCRATCH = 0x40000000
STACK = SCRATCH + 0x8000
RETURN = SCRATCH + 0xF000


def load(path):
    img = bytearray(open(path, "rb").read())
    off = struct.unpack_from("<I", img, 4)[0]
    bss_start, bss_end = struct.unpack_from("<ii", img, off + 8)
    bss_start += off; bss_end += off
    if bss_end > len(img):
        img.extend(b"\0" * (bss_end - len(img)))
    for slot, addend in relatives(bytes(img)):
        if slot + 8 <= len(img):
            struct.pack_into("<Q", img, slot, addend)
    return img


def _plt_stubs(img, got):
    """PLT stub address -> import name, by the adrp/ldr/add/br shape."""
    n = len(img) // 4
    w = struct.unpack(f"<{n}I", bytes(img[:n * 4]))
    out = {}
    for i in range(n - 3):
        if (w[i] & 0x9F00001F) == 0x90000010 and (w[i + 1] & 0xFFC003FF) == 0xF9400211 \
           and w[i + 3] == 0xD61F0220:
            immlo, immhi = (w[i] >> 29) & 3, (w[i] >> 5) & 0x7FFFF
            imm = (immhi << 2 | immlo)
            imm -= (1 << 21) if imm & (1 << 20) else 0
            slot = ((i * 4) & ~0xFFF) + (imm << 12) + (((w[i + 1] >> 10) & 0xFFF) * 8)
            if slot in got:
                out[i * 4] = got[slot]
    return out


class Runner:
    def __init__(self, path):
        self.img = load(path)
        self.uc = uc = Uc(UC_ARCH_ARM64, UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(0, (len(self.img) + 0xFFFFF) & ~0xFFFFF)
        uc.mem_write(0, bytes(self.img))
        uc.mem_map(SCRATCH, 0x200000)
        self.stubs = _plt_stubs(self.img, dict(imports(bytes(self.img))))
        self.stops = set()
        self.hit = None
        uc.hook_add(UC_HOOK_CODE, self._code)

    def _code(self, uc, addr, size, _):
        if addr in self.stops:
            self.hit = addr
            uc.emu_stop()
            return
        name = self.stubs.get(addr)
        if name is None:
            return
        x0, x1, x2 = (uc.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2))
        if name == "memcpy":
            uc.mem_write(x0, bytes(uc.mem_read(x1, x2)))
        elif name == "memset":
            uc.mem_write(x0, bytes([x1 & 0xFF]) * x2)
        elif name == "memcmp":
            a, b = bytes(uc.mem_read(x0, x2)), bytes(uc.mem_read(x1, x2))
            uc.reg_write(UC_ARM64_REG_X0, 0 if a == b else (1 if a > b else 0xFFFFFFFF))
        elif name.startswith("nn::os::"):
            uc.reg_write(UC_ARM64_REG_X0, 0)          # mutexes and TLS: inert here
        else:
            uc.reg_write(UC_ARM64_REG_X0, 0)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    def call(self, addr, args=(), stops=()):
        """-> (x0, the stop address hit or None). args are placed in x0.. in order."""
        self.stops, self.hit = set(stops), None
        self.uc.reg_write(UC_ARM64_REG_SP, STACK)
        self.uc.reg_write(UC_ARM64_REG_LR, RETURN)
        for i, v in enumerate(args):
            self.uc.reg_write(UC_ARM64_REG_X0 + i, v)
        try:
            self.uc.emu_start(addr, RETURN)
        except UcError:
            pass
        return self.uc.reg_read(UC_ARM64_REG_X0), self.hit

    def write(self, addr, data):
        self.uc.mem_write(addr, bytes(data))
        return addr
