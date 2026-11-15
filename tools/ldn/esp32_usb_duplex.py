#!/usr/bin/env python3
"""esp32_usb_duplex.py: measure USB frame loss both ways with the ESP32 radio idle.
docs/hardware_esp32.md, The ESP32-S2."""

import argparse
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pokeldn.ldn import esp32


COUNTERS = ("tx_eth_failed", "wire_rx_bad", "wire_dropped", "refused_heap", "refused_queue")


def status(radio):
    return dict(word.split("=", 1) for word in radio.status().split() if "=" in word)


def measure(port, seconds, size, interval):
    radio = esp32.Radio.open_serial(port, fast_baud=0)
    try:
        radio.stop()
        before = status(radio)
        if before["mode"] != "0":
            raise RuntimeError("The radio must be idle for this USB-only test")
        started = time.monotonic()
        attempted = 0
        payload = bytes(900)

        def upload():
            nonlocal attempted
            while time.monotonic() - started < seconds and not radio.lost:
                # Idle rejects Ethernet TX with ESP_ERR_INVALID_STATE. Its counter confirms a
                # valid host command reached the handler without transmitting a Wi-Fi frame.
                radio.send_ethernet(payload)
                attempted += 1
                time.sleep(interval)

        sender = threading.Thread(target=upload)
        sender.start()
        try:
            download = radio.bench(size, 1400, timeout=seconds * 4 + 10)
        finally:
            sender.join()
        if not radio.drain():
            raise RuntimeError("Timed out draining host USB commands")
        after = status(radio)
        delta = {field: int(after[field]) - int(before[field]) for field in COUNTERS}
        written = attempted - radio.tx_dropped
        return {
            "uplink_written": written,
            "uplink_missing": written - delta["tx_eth_failed"],
            "downlink_received": download["messages"],
            "downlink_missing": download["missing"],
            "downlink_rejected": download["rejected"],
            "downlink_kB_s": round(download["rate"] / 1000, 1),
            "flow_resyncs": radio.flow_resyncs,
            "host_queue_dropped": radio.tx_dropped,
            "board_counter_delta": delta,
            "board_heap": int(after["heap"]),
            "board_heap_min_since_boot": int(after["heap_min"]),
        }
    finally:
        radio.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--bytes", type=int, default=2_000_000)
    parser.add_argument("--interval", type=float, default=0.005)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if min(args.seconds, args.bytes, args.interval, args.repeat) <= 0:
        parser.error("seconds, bytes, interval and repeat must be positive")
    for _ in range(args.repeat):
        print(measure(args.port, args.seconds, args.bytes, args.interval), flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
