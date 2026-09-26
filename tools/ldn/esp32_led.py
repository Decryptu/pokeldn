#!/usr/bin/env python3
"""Drive the board's blue LED: one pattern, or --demo to show each in turn. No radio traffic.

    ./.venv/bin/python tools/ldn/esp32_led.py --port PORT breathe --period 2000
    ./.venv/bin/python tools/ldn/esp32_led.py --port PORT --demo

Opening the port resets the board: its boot pulse plays first. After a pattern with no --duration
the LED keeps it until the board resets or another command arrives. docs/hardware_esp32.md, The
board's LED and buttons.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.ldn import esp32  # noqa: E402

DEMO = (   # pattern, peak, period ms, seconds shown
    ("breathe", 255, 3000, 6), ("blink", 255, 1000, 4), ("flash3", 255, 1000, 3),
    ("ramp-up", 255, 2000, 3), ("ramp-down", 255, 2000, 3), ("pulse", 255, 1200, 5),
    ("breathe", 40, 4000, 8), ("on", 25, 0, 3), ("auto", 0, 0, 3),
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("pattern", nargs="?", choices=esp32.LED_PATTERNS)
    ap.add_argument("--peak", type=int, default=255, help="0..255, perceptual")
    ap.add_argument("--period", type=int, default=0, help="ms; 0 is the pattern's default")
    ap.add_argument("--duration", type=int, default=0, help="ms; 0 holds it")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args(argv)
    if not args.demo and not args.pattern:
        ap.error("a pattern or --demo")
    radio = esp32.Radio.open_serial(args.port)
    try:
        radio.hello()
        time.sleep(1.0)   # the boot pulse
        if args.demo:
            for pattern, peak, period, seconds in DEMO:
                print(f"{pattern:10} peak {peak:3} period {period} ms", flush=True)
                radio.led(pattern, peak, period)
                time.sleep(seconds)
        else:
            radio.led(args.pattern, args.peak, args.period, args.duration)
    finally:
        radio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
