#!/usr/bin/env python3
"""Start the portable beacon stored on the board while this computer listens: the board runs it as
on a charger and its LOG and STATUS lines print here. docs/hardware_esp32.md, Portable beacon.

    ./.venv/bin/python tools/ldn/esp32_beacon.py [--port PORT]

Ctrl-C leaves the beacon running on the board; unplugging it ends it.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.ldn import esp32, esp32_wlan  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="the board's serial port; the only one present by default")
    ap.add_argument("--status-every", type=float, default=5.0, metavar="SECONDS")
    args = ap.parse_args(argv)
    port = args.port or esp32_wlan.auto_port()
    radio = esp32.Radio.open_serial(port, log=print)
    try:
        if esp32.firmware_version(radio.info) < esp32.BEACON_FIRMWARE:
            print(f"firmware {radio.info.firmware_version} keeps no beacon", file=sys.stderr)
            return 1
        state = radio.beacon_state()
        if not state.stored:
            print("no beacon is stored on this board", file=sys.stderr)
            return 1
        radio.start_beacon()
        print(f"beacon started: {state.length} bytes, crc {state.crc:#010x}")
        while True:
            time.sleep(args.status_every)
            print(radio.status())
    except KeyboardInterrupt:
        return 0
    finally:
        radio.close()


if __name__ == "__main__":
    sys.exit(main())
