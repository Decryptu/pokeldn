#!/usr/bin/env python3
"""Run a function out of a title's main NSO image under unicorn, with its nnSdk imports intercepted.

In the static image every PLT stub jumps through a zero GOT slot: stubs are mapped by name
(nso_imports) and serviced in Python. bin/swsh_gift_host.py runs the Wonder Card validator with it."""
from pathlib import Path
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pokeldn.switch.nso import imports, load as _load, plt_stubs as _plt_stubs, relatives  # noqa: E402,F401
from unicorn import *
from unicorn.arm64_const import *

SCRATCH = 0x40000000
STACK = SCRATCH + 0x8000
RETURN = SCRATCH + 0xF000


def load(path):
    """-> the laid-out image at `path` with bss and its RELATIVE slots filled at base 0."""
    return _load(Path(path))


class Runner:
    def __init__(self, path):
        self.img = load(path)
        self.uc = uc = Uc(UC_ARCH_ARM64, UC_MODE_LITTLE_ENDIAN)
        uc.ctl_set_tcg_buffer_size(64 << 20)    # the default 1 GiB is committed up front on Windows
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
