#!/usr/bin/env python3
"""Assemble AArch64 or ARM/Thumb source to raw bytes with LLVM's assembler.

    ./.venv/bin/python tools/switch/assemble.py source.s out.bin [--triple aarch64-none-elf]

The GBA payloads use `armv4t-none-eabi` (ARM7TDMI); native title payloads use `aarch64-none-elf`.
LLVM_HOME overrides the tool directory, which defaults to Homebrew's LLVM.
"""
import argparse
import os
import shutil
import subprocess
import tempfile

DEFAULT_LLVM = "/opt/homebrew/opt/llvm/bin"


def _tool(name):
    home = os.environ.get("LLVM_HOME", DEFAULT_LLVM)
    local = os.path.join(home, name)
    return local if os.path.exists(local) else (shutil.which(name) or local)


def assemble(source, triple="aarch64-none-elf"):
    """-> the .text bytes of `source` assembled for `triple`."""
    with tempfile.TemporaryDirectory() as d:
        s = os.path.join(d, "in.s")
        o = os.path.join(d, "out.o")
        b = os.path.join(d, "out.bin")
        with open(s, "w") as f:
            f.write(source)
        subprocess.run([_tool("llvm-mc"), f"-triple={triple}", "-filetype=obj", s, "-o", o],
                       check=True)
        subprocess.run([_tool("llvm-objcopy"), "-O", "binary", o, b], check=True)
        return open(b, "rb").read()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--triple", default="aarch64-none-elf")
    args = ap.parse_args()
    data = assemble(open(args.source).read(), args.triple)
    open(args.output, "wb").write(data)
    print(f"{args.output}: {len(data)} bytes")


if __name__ == "__main__":
    main()
