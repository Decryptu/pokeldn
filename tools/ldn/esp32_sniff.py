#!/usr/bin/env python3
"""A second ESP32 board as an air sniffer: every management and data frame to or from one MAC on
one channel, recorded whole in a POKELDN_ESP32_TRACE file. docs/hardware_esp32.md.

    ./.venv/bin/python tools/ldn/esp32_sniff.py --port /dev/cu.usbserial-XXXX --channel 1 \\
        --mac 48:f1:eb:20:9b:22 --seconds 120 --trace scratchpad/ehNN_sniff.trace
    scratchpad/esp32_trace_read.py scratchpad/ehNN_sniff.trace --key-from scratchpad/ehNN_esp32.trace
"""
import argparse
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True)
    ap.add_argument("--channel", type=int, required=True)
    ap.add_argument("--mac", required=True, help="the station or BSSID whose frames to keep")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--trace", required=True, help="output trace file")
    args = ap.parse_args()
    os.environ["POKELDN_ESP32_TRACE"] = args.trace
    from pokeldn.ldn import esp32
    radio = esp32.Radio.open_serial(args.port, log=print)
    count = [0]
    radio.subscribe(lambda t, p: count.__setitem__(0, count[0] + (t == esp32.MSG_RX_MGMT)))
    radio.sniff(args.channel, args.mac)
    print(f"[sniff] channel {args.channel}, frames to or from {args.mac}, {args.seconds:.0f} s -> {args.trace}")
    end = time.time() + args.seconds
    try:
        while time.time() < end:
            time.sleep(5)
            print(f"[sniff] {count[0]} frame(s)")
    except KeyboardInterrupt:
        pass
    radio.stop()
    radio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
