#!/usr/bin/env python3
"""Press a Switch's buttons through the controller board (firmware/pad, docs/hardware_pad.md).

    pad.py A                      press A
    pad.py HOME wait:1 A          steps run in order
    pad.py 'down*3' A             a step repeated
    pad.py hold:B:2               hold B for 2 s
    pad.py stick:L:-1:0:0.5       left stick fully left for 0.5 s
    pad.py --play FILE.pokemacro  load a macro onto the board and start it
    pad.py --stop                 stop the board's macro
    pad.py --status               mounted, macro progress, firmware version
    pad.py --download             reboot the board into the ROM loader to flash it

A step list runs from this host, a macro on the board's own clock. Requests go to the controller
service (pokeldn.pad.service) on 127.0.0.1, which this starts in-process when none is running.

macOS aborts a process that opens Bluetooth unless its app declares NSBluetoothAlwaysUsageDescription.
`pad.py --make-app scratchpad/PadBridge.app` writes an app that runs the service; `open` it once and
allow Bluetooth.
"""
import argparse
import asyncio
import os
import pathlib
import plistlib
import stat
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.pad import macro, service  # noqa: E402


def parse(step):
    """One step -> (report, seconds) pairs."""
    name, _, count = step.partition("*")
    times = int(count) if count else 1
    parts = name.split(":")
    head = parts[0].upper()
    if head == "WAIT":
        return [(None, float(parts[1]))] * times
    if head == "HOLD":
        return [(macro.state(parts[1].split("+")), float(parts[2])), (macro.NEUTRAL, 0.1)] * times
    if head == "STICK":
        side, xy = parts[1].upper(), (float(parts[2]), float(parts[3]))
        secs = float(parts[4]) if len(parts) > 4 else 0.3
        r = macro.state(left=xy) if side == "L" else macro.state(right=xy)
        return [(r, secs), (macro.NEUTRAL, 0.1)] * times
    try:
        return [(macro.state(head.split("+")), 0.1), (macro.NEUTRAL, 0.15)] * times
    except macro.MacroError as e:
        raise SystemExit(f"{e}; known: {', '.join(macro.KEYS)}")


def make_app(path):
    app = pathlib.Path(path).resolve()
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleIdentifier": "io.pokeldn.padbridge", "CFBundleName": "PadBridge",
            "CFBundleExecutable": "PadBridge", "CFBundlePackageType": "APPL", "LSUIElement": True,
            "NSBluetoothAlwaysUsageDescription": "Sends button presses to the pokeldn controller board.",
        }, f)
    exe = macos / "PadBridge"
    root = pathlib.Path(__file__).resolve().parents[2]
    # A child, not exec: the app stays the process macOS asks about Bluetooth.
    exe.write_text(f'#!/bin/sh\ncd "{root}"\nPYTHONPATH="{root}" "{sys.executable}" -m pokeldn.pad.service '
                   f'>> "{app.parent / "padbridge.log"}" 2>&1\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    subprocess.run(["codesign", "--force", "-s", "-", str(app)], check=True)
    print(f"wrote {app}; start it with: open {app}")


def client():
    if not service.running():
        threading.Thread(target=lambda: asyncio.run(service.serve()), daemon=True).start()
        for _ in range(50):
            if service.running():
                break
            time.sleep(0.1)
    return service.Client()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("steps", nargs="*")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--play", metavar="FILE", help="load a .pokemacro onto the board and start it")
    ap.add_argument("--stop", action="store_true", help="stop the board's macro")
    ap.add_argument("--download", action="store_true", help="reboot the board into the ROM loader")
    ap.add_argument("--scan", action="store_true", help="list the Bluetooth LE advertisers in range")
    ap.add_argument("--make-app", metavar="PATH", help="write the macOS bridge app and exit")
    args = ap.parse_args()
    plan = [item for step in args.steps for item in parse(step)]
    if args.make_app:
        return make_app(args.make_app)
    text = pathlib.Path(args.play).read_text() if args.play else None
    if text:
        macro.compile_macro(macro.loads(text))
    c = client()
    try:
        if args.scan:
            print("\n".join(c.call("scan")["out"]))
        if args.download:
            c.call("download")
            print("rebooting into the ROM loader")
            return
        if args.stop:
            c.call("stop")
        if text:
            r = c.call("play", macro=text)
            loops = "until stopped" if r["loops"] == 0 else f"{r['loops']} time(s)"
            print(f"playing {r['entries']} entries; setup {r['setup_ms']} ms, loop {r['loop_ms']} ms, {loops}")
        for report, secs in plan:
            if report is not None:
                c.call("send", report=report.hex())
            time.sleep(secs)
        if plan:
            c.call("send", report=macro.NEUTRAL.hex())
        if args.status or not (plan or text or args.stop or args.scan):
            c.call("connect")
            s = c.call("status")["status"]
            print(f"mounted {'yes' if s['mounted'] else 'no'}, writes {s['writes']}, "
                  f"{'playing' if s['playing'] else 'idle'} entry {s['index']}/{s['count']} "
                  f"loops done {s['loops_done']}, firmware {s['version'] or 'before 1.0.0'}, "
                  f"reset {s['reset_reason']} previous boot stage {s['stage_before']} boots {s['boots']}")
    except service.ServiceError as e:
        sys.exit(str(e))
    finally:
        c.close()


if __name__ == "__main__":
    main()
