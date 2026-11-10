#!/usr/bin/env python3
"""Restore a FireRed `.sav` while the console is still running the Emerald build.

The stock save-restore payload is FireRed's. Its finish step calls FireRed's
``LoadGameSave`` and the Mystery Gift success message makes the running game save
the loaded state. Under the Emerald ROM that address points into unrelated code,
and letting Emerald save would replace the restored FireRed image with Emerald's
chunks. This tool builds the same payload with a different finish step:

  * ``swi 0x4C`` (``svc_FinishSave``) commits the whole 128 KiB flash image to
    ``save:/``;
  * it returns 0 instead of ``SAVE_STATUS_OK``, so the Mystery Gift menu ends on
    ``CLI_MSG_BUFFER_FAILURE`` and the running game does not save over the image.

The payload also reads Emerald's ``gSaveCounter`` (0x03006320 in the BPRE and
BPRF pokeemerald_switch builds) instead of FireRed's. The host advertises as
Emerald, which is what an Emerald console's Mystery Gift search expects.

Measured on the emulated French FireRed (2026-11-10): a VBlank hook wrote sector
30 with 0x5A through ``swi 0x48`` and then called ``swi 0x4C``; the save file
changed and sector 30 read 0x5A. The same write without ``0x4C`` stayed in the
in-memory flash image. On the retail English FireRed Lite running the Emerald
BPRE build, the Emerald Mystery Gift -> Wonder Cards -> Friend screen went black:
the console associated with the host's Wi-Fi but never sent its LinkPlayer block.
That retail path is unverified.

Once the console is back on FireRed with Mystery Gift unlocked, prefer the
ordinary FireRed restore, which writes, loads and saves the image:

    bin/frlg_mg_host.py --save-restore scratchpad/lite/lite_backup.sav ...

This tool is for the case where the console is still in Emerald. It accepts the
same host arguments as bin/frlg_mg_host.py; ``--version`` and ``--expect-console``
are removed because the CLI refuses ``emerald`` for a save session, and the
host profile is switched to Emerald below.
"""
import dataclasses
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BUNDLED_LDN = ROOT / "vendor" / "LDN"
if (BUNDLED_LDN / "ldn").is_dir():
    sys.path.insert(0, str(BUNDLED_LDN))

from pokeldn.frlg.gift import save_transfer  # noqa: E402

SOURCE = ROOT / "asm" / "save-restore.s"
RESIDENT = 0x0201C400
EMERALD_SAVE_COUNTER = 0x03006320

FINISH_STUB = """
@ FinishSave instead of LoadGameSave. 0 is not SAVE_STATUS_OK, so the Mystery
@ Gift menu ends on a failure and the running game does not save.
    .thumb
    .align  1
finish_stub:
    swi     0x4C
    movs    r0, #0
    bx      lr
    .arm
    .align  2
"""


def _tool(name):
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"{name} is not on PATH; install arm-none-eabi binutils")
    return path


def build_payload():
    """-> the 644-byte template with FinishSave and Emerald's counter patched in."""
    source = SOURCE.read_text()
    if "\nend:\n" not in source:
        raise SystemExit(f"{SOURCE}: no `end:` label to put the finish stub before")
    source = source.replace("\nend:\n", FINISH_STUB + "\nend:\n", 1)
    with tempfile.TemporaryDirectory(prefix="pokeldn-emerald-restore-") as tmp:
        src = pathlib.Path(tmp) / "save-restore-finish.s"
        obj = pathlib.Path(tmp) / "save-restore-finish.o"
        binary = pathlib.Path(tmp) / "save-restore-finish.bin"
        src.write_text(source)
        subprocess.run([_tool("arm-none-eabi-as"), "-march=armv4t", "-mcpu=arm7tdmi",
                        "-o", str(obj), str(src)], check=True)
        subprocess.run([_tool("arm-none-eabi-objcopy"), "-O", "binary",
                        str(obj), str(binary)], check=True)
        data = bytearray(binary.read_bytes())
        nm = subprocess.run([_tool("arm-none-eabi-nm"), str(obj)],
                            check=True, capture_output=True, text=True)
    stub = None
    for line in nm.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] == "finish_stub":
            stub = int(fields[0], 16)
            break
    if stub is None:
        raise SystemExit("the finish_stub symbol is missing from the assembled payload")
    if len(data) < 0x10:
        raise SystemExit("the assembled payload is too short")
    data[0x008:0x00C] = (RESIDENT + stub + 1).to_bytes(4, "little")
    data[0x00C:0x010] = EMERALD_SAVE_COUNTER.to_bytes(4, "little")
    return bytes(data)


def _load_cli():
    spec = importlib.util.spec_from_file_location("frlg_mg_host", ROOT / "bin" / "frlg_mg_host.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _host_args(argv):
    """Drop the CLI's FireRed/Emerald guards and keep the rest of the arguments."""
    args, out, i = list(argv), [], 0
    while i < len(args):
        arg = args[i]
        if arg in ("--version", "--expect-console"):
            i += 2
            continue
        if arg.startswith("--version=") or arg.startswith("--expect-console="):
            i += 1
            continue
        out.append(arg)
        i += 1
    if any(arg == "--save-restore-emerald" or arg.startswith("--save-restore-emerald=")
           for arg in out):
        raise SystemExit("use --save-restore; --save-restore-emerald is the FireRed-side variant")
    if not any(arg == "--save-restore" or arg.startswith("--save-restore=") for arg in out):
        raise SystemExit("emerald_save_restore.py needs --save-restore FILE")
    if any(arg == "--save-backup" or arg.startswith("--save-backup=") for arg in out):
        raise SystemExit("this tool restores; it does not back up")
    return out + ["--version", "firered"]


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    if any(arg in ("-h", "--help") for arg in raw):
        cli = _load_cli()
        sys.argv = ["emerald_save_restore.py", *raw]
        return cli.main()
    args = _host_args(raw)
    payload = build_payload()
    save_transfer.restore_code = lambda _build: payload
    save_transfer.NOT_RESTORED = save_transfer._encode_message(
        "The FireRed save is in.\nClose the game now.", None)
    cli = _load_cli()

    class EmeraldSaveTransferHost(cli.SaveTransferHostApplication):
        """A save-transfer host whose RFU identity is Emerald, not the CLI's FireRed."""

        def __init__(self, config, **kwargs):
            config = dataclasses.replace(
                config, profile=dataclasses.replace(config.profile, version="emerald"))
            super().__init__(config, **kwargs)

    cli.SaveTransferHostApplication = EmeraldSaveTransferHost
    sys.argv = ["emerald_save_restore.py", *args]
    return cli.main()


if __name__ == "__main__":
    sys.exit(main())
