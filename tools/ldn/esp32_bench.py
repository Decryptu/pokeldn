#!/usr/bin/env python3
"""Measure the board-to-host serial ceiling at one or more baud rates. No console, no radio traffic.

    ./.venv/bin/python tools/ldn/esp32_bench.py --port PORT \\
        --bauds 921600,1500000,2000000,3000000 --bytes 2000000

For each rate the board streams random payloads (the COBS overhead of ciphertext) through CMD_BENCH
and this prints what arrived, what was lost or failed its checksum, and the rate against the line's
own limit of baud / 10. The port is reopened per rate, which resets the board. A rate the USB
bridge does not take shows as a HELLO that never answers. docs/hardware_esp32.md, The serial
ceiling.

    --uplink N   the other direction: the board hosts an empty network and the host sends N ETH_TX
                 commands in bursts of --burst, 100 to 300 bytes each as a seat's are; the board's
                 tx_eth + tx_eth_failed against N is what the host-to-board path lost.
    --trickle S  command latency: for S seconds the host writes a 14-byte ETH_TX (21 bytes on the
                 line) every 15 ms to an idle board, with --flood also streaming BENCH the other
                 way; prints the board's read_max_us, which stays near its 20 ms read timeout
                 unless a read waits for more than the bytes that arrived.
"""
import argparse
import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.ldn import esp32


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--bauds", default="921600,1500000,2000000,3000000")
    ap.add_argument("--bytes", type=int, default=2_000_000)
    ap.add_argument("--size", type=int, default=1400, help="bytes per message, 8..1600")
    ap.add_argument("--uplink", type=int, default=0, metavar="N")
    ap.add_argument("--burst", type=int, default=11, help="--uplink: commands written back to back")
    ap.add_argument("--gap", type=float, default=0.02, help="--uplink: seconds between bursts")
    ap.add_argument("--trickle", type=float, default=0, metavar="SECONDS")
    ap.add_argument("--flood", action="store_true", help="--trickle: BENCH the other way meanwhile")
    args = ap.parse_args(argv)
    if args.trickle:
        for baud in [int(b) for b in args.bauds.split(",") if b.strip()]:
            trickle(args.port, baud, args.trickle, args.flood)
        return 0
    if args.uplink:
        for baud in [int(b) for b in args.bauds.split(",") if b.strip()]:
            uplink(args.port, baud, args.uplink, args.burst, args.gap)
        return 0
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


def board_sent(radio):
    fields = dict(kv.split("=", 1) for kv in radio.status().split() if "=" in kv)
    return int(fields["tx_eth"]) + int(fields["tx_eth_failed"]), fields


def uplink(port, baud, total, burst, gap):
    try:
        radio = esp32.Radio.open_serial(port, fast_baud=baud)
    except Exception as exc:
        print(f"{baud:>8}  did not come up at this rate: {exc}")
        return
    try:
        radio.ap_start(11, "02:00:00:be:4c:01", "pokeldn-bench".ljust(32, "x"), os.urandom(16))
        before, _ = board_sent(radio)
        rng = random.Random(1)
        t0 = time.monotonic()
        for i in range(total):
            body = rng.randbytes(rng.randrange(86, 286))
            radio.send_ethernet(b"\xff" * 6 + bytes.fromhex("0200000000be") + b"\x08\x00" + body)
            if (i + 1) % burst == 0:
                time.sleep(gap)
                while len(radio._out) > esp32.QUEUE_LIMIT // 2:   # the host's queue, not the board's
                    time.sleep(0.005)
        radio.drain(60)
        seconds = time.monotonic() - t0
        time.sleep(1.0)
        after, fields = board_sent(radio)
        radio.stop()
    finally:
        radio.close()
    counted = after - before
    sent = total - radio.tx_dropped
    print(f"{baud:>8}  uplink {sent} of {total} written in {seconds:.1f}s, board counted {counted}, "
          f"lost {sent - counted}, flow resyncs {radio.flow_resyncs}; wire_rx_bad {fields['wire_rx_bad']} uart_fifo_ovf "
          f"{fields.get('uart_fifo_ovf')} uart_buffer_full {fields.get('uart_buffer_full')} "
          f"tx_eth_failed {fields['tx_eth_failed']} tx_eth_retried {fields['tx_eth_retried']}")


def trickle(port, baud, seconds, flood):
    radio = esp32.Radio.open_serial(port, fast_baud=baud)
    try:
        before, _ = board_sent(radio)
        frame = b"\xff" * 6 + bytes.fromhex("0200000000be") + b"\x08\x00"
        stop, sent = threading.Event(), [0]

        def writer():
            while not stop.is_set():
                radio.send_ethernet(frame)
                sent[0] += 1
                time.sleep(0.015)

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            if flood:
                r = radio.bench(int(160_000 * seconds), 1400, timeout=seconds * 4 + 10)
                print(f"{baud:>8}  BENCH {r['rate'] / 1000:.1f} KB/s, {r['missing']} missing")
            else:
                time.sleep(seconds)
        finally:
            stop.set()
            thread.join()
        radio.drain(30)
        time.sleep(1.0)
        after, fields = board_sent(radio)
    finally:
        radio.close()
    print(f"{baud:>8}  trickle {sent[0]} written, board counted {after - before}; read_max_us "
          f"{fields.get('read_max_us')} handler_max_us {fields.get('handler_max_us')} write_max_us "
          f"{fields.get('write_max_us')} uart_fifo_ovf {fields.get('uart_fifo_ovf')}")


if __name__ == "__main__":
    sys.exit(main())
