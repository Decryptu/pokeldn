#!/usr/bin/env python3
"""Measure the board-to-host serial ceiling at one or more baud rates. No console, no radio traffic.

    ./.venv/bin/python tools/ldn/esp32_bench.py --port /dev/cu.usbserial-0001 \\
        --bauds 921600,1500000,2000000,3000000 --bytes 2000000

For each rate the board streams random payloads (the COBS overhead of ciphertext) through CMD_BENCH
and this prints what arrived, what was lost or failed its checksum, and the rate against the line's
own limit of baud / 10. The port is reopened per rate, which resets the board. A rate the USB
bridge does not take shows as a HELLO that never answers. docs/hardware_esp32.md, The serial
ceiling.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.ldn import esp32


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--bauds", default="921600,1500000,2000000,3000000")
    ap.add_argument("--bytes", type=int, default=2_000_000)
    ap.add_argument("--size", type=int, default=1400, help="bytes per message, 8..1600")
    args = ap.parse_args(argv)
    for baud in [int(b) for b in args.bauds.split(",") if b.strip()]:
        try:
            radio = esp32.Radio.open_serial(args.port, fast_baud=baud)
        except Exception as exc:
            print(f"{baud:>8}  did not come up at this rate: {exc}")
            continue
        try:
            r = radio.bench(args.bytes, args.size, timeout=args.bytes / (baud / 10) * 3 + 10)
        finally:
            radio.close()
        line = baud / 10
        print(f"{baud:>8}  {r['rate'] / 1000:8.1f} KB/s  {100 * r['rate'] / line:5.1f}% of the line  "
              f"{r['messages']} messages, {r['missing']} missing, {r['rejected']} bad checksums, "
              f"board {r['board_seconds']:.2f}s host {r['seconds']:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
