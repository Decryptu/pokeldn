#!/usr/bin/env python3
"""Freeze an emulator for a moment at a chosen phase of each ROM stream message, to reproduce a link
drop in minutes instead of hours [docs/rse_switch_build.md, Unresolved].

    ./.venv/bin/python tools/rse/stream_stall.py --pid PID --log HOST_LOG --out STALLS.jsonl

Follows the host's log; every --every messages it stops PID at --phases seconds after the message's
`sending ident` line for --pauses seconds, cycling through every pair. It ends on the console's
RFU disconnect, after --limit pauses, or when the log goes quiet for 120 s. Never point it at a console.
"""
import argparse
import itertools
import json
import os
import re
import signal
import time

SEND = re.compile(r"\[\s*([\d.]+)s\] \[mg\] sending ident 23")
DROP = "RFU disconnect frame"
QUIET_LIMIT = 120


def floats(text):
    return [float(x) for x in text.split(",")]


def freeze(pid, seconds):
    os.kill(pid, signal.SIGSTOP)
    try:
        time.sleep(seconds)
    finally:
        os.kill(pid, signal.SIGCONT)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=int, default=4, help="messages between pauses")
    ap.add_argument("--phases", type=floats, default=floats("0,0.05,0.1,0.2,0.3,0.5,1,2"))
    ap.add_argument("--pauses", type=floats, default=floats("0.3,0.4,0.5"))
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--second", type=floats, default=[], help="a second pause, --second-gap s after the first")
    ap.add_argument("--second-gap", type=float, default=0.04)
    args = ap.parse_args()

    plan = itertools.cycle(itertools.product(args.pauses, args.phases))
    done = seen = 0
    last = time.monotonic()
    with open(args.log, errors="replace") as log, open(args.out, "a") as out:
        log.seek(0, os.SEEK_END)
        while done < args.limit:
            line = log.readline()
            if not line:
                if time.monotonic() - last > QUIET_LIMIT:
                    print("log quiet, stopping", flush=True)
                    return
                time.sleep(0.005)
                continue
            last = time.monotonic()
            if DROP in line:
                print(f"DROP after {done} pauses: {line.strip()[:120]}", flush=True)
                return
            sent = SEND.search(line)
            if not sent:
                continue
            seen += 1
            if seen % args.every:
                continue
            pause, phase = next(plan)
            time.sleep(phase)
            freeze(args.pid, pause)
            for extra in args.second:
                time.sleep(args.second_gap)
                freeze(args.pid, extra)
            done += 1
            out.write(json.dumps({"ident_at": float(sent[1]), "phase": phase, "pause": pause}) + "\n")
            out.flush()
            print(f"pause {done}: {pause} s at +{phase} s of the message logged at {sent[1]}", flush=True)
    print(f"no drop after {done} pauses", flush=True)


if __name__ == "__main__":
    main()
