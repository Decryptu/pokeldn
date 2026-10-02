"""Custom console code: ARM source assembled with the GNU toolchain when it is installed, or a
prebuilt binary, then run once on the simulated console before anything is sent [buffer_script]."""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from pokeldn.frlg.rom import buffer_script

AS = "arm-none-eabi-as"
OBJCOPY = "arm-none-eabi-objcopy"
AS_FLAGS = ("-march=armv4t", "-mcpu=arm7tdmi")
# The trainer id the simulated console holds; a payload reading SaveBlock2 returns it.
SAMPLE_TRAINER_ID = 0xE5BBDF65
TEMPLATE = """\
@ Called once a frame until it returns 1.
@ r0 = &param (sent back to the host)
@ r1 = gSaveBlock2Ptr, r2 = gSaveBlock1Ptr
    .arm
    .text
    .global _start
_start:
    ldrh    r3, [r1, #0x0A]         @ the trainer id (TID)
    str     r3, [r0]                @ answer with it
    mov     r0, #1                  @ done
    bx      lr
"""


class CodeError(ValueError):
    """`line` is the source line the assembler named, or 0."""

    def __init__(self, message, line=0):
        self.line = line
        super().__init__(message)


# A desktop app started from Finder gets no shell PATH; these hold Homebrew's and the usual installs.
SEARCH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


def toolchain():
    """-> (as, objcopy) paths, or None when the GNU Arm toolchain is not installed."""
    path = os.pathsep.join([os.environ.get("PATH", ""), *SEARCH])
    tools = shutil.which(AS, path=path), shutil.which(OBJCOPY, path=path)
    return tools if all(tools) else None


def assemble(source):
    """ARM source -> machine code. Raises CodeError with the first diagnostic line."""
    tools = toolchain()
    if tools is None:
        raise CodeError("Assembling needs the GNU Arm toolchain (arm-none-eabi-as). "
                        "Install it, or open a prebuilt .bin instead.")
    with tempfile.TemporaryDirectory() as tmp:
        src, obj, binary = (pathlib.Path(tmp) / name for name in ("a.s", "a.o", "a.bin"))
        src.write_text(source if source.endswith("\n") else source + "\n")
        result = subprocess.run([tools[0], *AS_FLAGS, "-o", str(obj), str(src)],
                                capture_output=True, text=True)
        if result.returncode:
            for line in result.stderr.splitlines():
                if match := re.search(r"a\.s:(\d+): Error: (.*)", line):
                    raise CodeError(f"Line {match[1]}: {match[2]}", int(match[1]))
            raise CodeError(result.stderr.strip() or "The assembler failed.")
        subprocess.run([tools[1], "-O", "binary", str(obj), str(binary)], check=True)
        return binary.read_bytes()


@dataclass(frozen=True)
class Check:
    code: bytes
    frames: int
    instructions: int
    param: int
    sends: int         # bytes the payload put in the console's reply, 4 when it left it alone

    def describe(self):
        reply = f"answers 0x{self.param:08X}" if self.sends == 4 else f"sends back {self.sends} bytes"
        return (f"{len(self.code)} bytes; returned 1 after {self.frames} frame"
                f"{'s' if self.frames != 1 else ''} ({self.instructions} instructions) and {reply}.")


def check(code):
    """Run `code` as the console would; a fault or a payload that never returns 1 is a CodeError,
    because on the console either one hangs the Mystery Gift menu."""
    try:
        buffer_script.validate(code)
    except buffer_script.BufferScriptError as exc:
        raise CodeError(str(exc)) from None
    if not buffer_script.emulation_available():
        raise CodeError("The offline check needs Unicorn, which this install lacks.")
    sav2 = bytearray(0x1000)
    at = buffer_script.SAV2_PLAYER_TRAINER_ID
    sav2[at:at + 4] = SAMPLE_TRAINER_ID.to_bytes(4, "little")
    try:
        run = buffer_script.emulate_repeating(code, sav2=bytes(sav2))
    except buffer_script.BufferScriptError as exc:
        raise CodeError(f"It would hang the console: {exc}") from None
    return Check(bytes(code), run.calls, run.instructions, run.final.param,
                 run.final.client.send_size)
