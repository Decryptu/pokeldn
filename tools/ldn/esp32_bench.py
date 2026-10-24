#!/usr/bin/env python3
"""Measure the serial ceiling and sustained uploads without a console.

    ./.venv/bin/python tools/ldn/esp32_bench.py --port PORT \\
        --bauds 921600,1500000,2000000,3000000 --bytes 2000000

The port is reopened per rate, which resets the board; a rate the USB bridge refuses shows as a HELLO
that never answers. docs/hardware_esp32.md, The serial ceiling.

    --uplink N   host to board: N ETH_TX of 100 to 300 bytes in bursts of --burst to an empty network,
                 against the board's tx_eth + tx_eth_failed. --no-flow ignores CREDIT on purpose.
    --trickle S  command latency: a 14-byte ETH_TX every 15 ms for S seconds (--flood adds BENCH the
                 other way); read_max_us stays near the 20 ms read timeout unless a read over-waits.
    --soak S     sustained host-to-board ETH_TX for S seconds, --size bytes per Ethernet frame,
                 paced to --rate bytes/s (0: unlimited); STATUS every 5 s, no console required.
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
    ap.add_argument("--size", type=int, default=1400, help="bytes per BENCH message (8..1600) or soak frame (14..1600)")
    ap.add_argument("--uplink", type=int, default=0, metavar="N")
    ap.add_argument("--soak", type=float, default=0, metavar="SECONDS")
    ap.add_argument("--rate", type=float, default=460_000, help="--soak: Ethernet bytes/s, 0: unlimited")
    ap.add_argument("--burst", type=int, default=11, help="--uplink: commands written back to back")
    ap.add_argument("--gap", type=float, default=0.02, help="--uplink: seconds between bursts")
    ap.add_argument("--no-flow", action="store_true", help="--uplink: ignore the board's CREDIT")
    ap.add_argument("--trickle", type=float, default=0, metavar="SECONDS")
    ap.add_argument("--flood", action="store_true", help="--trickle: BENCH the other way meanwhile")
    ap.add_argument("--ap", action="store_true",
                    help="--trickle: host an empty network, so each ETH_TX goes to the air")
    ap.add_argument("--body", type=int, default=0, help="--trickle: bytes after the Ethernet header")
    args = ap.parse_args(argv)
    bauds = [int(b) for b in args.bauds.split(",") if b.strip()]
    if args.soak:
        if args.soak < 0 or not 14 <= args.size <= 1600 or args.rate < 0 or not bauds:
            ap.error("--soak needs positive seconds, --size 14..1600, nonnegative --rate and a baud")
        if args.uplink or args.trickle or args.no_flow:
            ap.error("--soak uses CREDIT flow control and cannot be combined with --uplink or --trickle")
        for baud in bauds:
            try:
                soak(args.port, baud, args.soak, args.size, args.rate, bauds)
            except Exception as exc:
                print(f"{baud:>8}  soak FAILED: {exc}", flush=True)
                return 1
        return 0
    if args.trickle:
        for baud in bauds:
            trickle(args.port, baud, args.trickle, args.flood, args.ap, args.body, bauds)
        return 0
    if args.uplink:
        for baud in bauds:
            uplink(args.port, baud, args.uplink, args.burst, args.gap, args.no_flow, bauds)
        return 0
    for baud in bauds:
        try:
            radio = esp32.Radio.open_serial(args.port, fast_baud=baud, left_at=bauds)
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


def soak(port, baud, seconds, size=1400, rate=460_000, left_at=()):
    radio = esp32.Radio.open_serial(port, fast_baud=baud, left_at=left_at, log=print)
    sent = 0
    started = time.monotonic()
    try:
        radio.ap_start(11, "02:00:00:be:4c:01", "pokeldn-soak".ljust(32, "x"), os.urandom(16))
        before, _ = board_sent(radio)
        frame = b"\xff" * 6 + bytes.fromhex("0200000000be") + b"\x08\x00" + random.Random(1).randbytes(size - 14)
        started = time.monotonic()
        report_at = started + 5
        print(f"{baud:>8}  soak starting: {seconds:g}s, {size}-byte frames, "
              f"{rate:g} Ethernet bytes/s (0: unlimited)", flush=True)

        def report():
            counted, fields = board_sent(radio)
            print(f"{baud:>8}  soak {time.monotonic() - started:.1f}s: "
                  f"sent={sent} bytes={sent * size} counted={counted - before} "
                  f"uncredited={radio._written - radio._credited} "
                  f"host_dropped={radio.tx_dropped} resyncs={radio.flow_resyncs} "
                  f"status={fields}", flush=True)
            return counted - before

        while time.monotonic() - started < seconds:
            if radio.lost is not None:
                raise esp32.RadioError(str(radio.lost))
            for _ in range(32):
                radio.send_ethernet(frame)
                sent += 1
            if not radio.drain(5):
                raise esp32.RadioError(f"USB output did not drain: {radio.lost or 'timed out'}")
            if rate:
                target = min(started + seconds, started + sent * size / rate)
                while time.monotonic() < target:
                    if radio.lost is not None:
                        raise esp32.RadioError(str(radio.lost))
                    time.sleep(min(0.05, max(0, target - time.monotonic())))
            if time.monotonic() >= report_at:
                report()
                report_at = time.monotonic() + 5
        # A periodic STATUS already queued by the firmware can precede the last ETH_TX.
        deadline = time.monotonic() + 2
        counted = report()
        while counted < sent and time.monotonic() < deadline:
            time.sleep(0.1)
            counted = report()
        if counted != sent or radio.tx_dropped:
            raise esp32.RadioError(f"board counted {counted} of {sent} ETH_TX; host dropped {radio.tx_dropped}")
        radio.stop()
    except Exception:
        print(f"{baud:>8}  soak stopped after {time.monotonic() - started:.1f}s, "
              f"{sent} frames, {sent * size} Ethernet bytes; "
              f"written={radio._written} credited={radio._credited} "
              f"resyncs={radio.flow_resyncs}", flush=True)
        if radio.lost is None:
            try:
                radio.stop()
            except esp32.RadioError:
                pass
        raise
    finally:
        radio.close()


def uplink(port, baud, total, burst, gap, no_flow=False, left_at=()):
    if no_flow:
        esp32.FLOW_WINDOW = 1 << 40
    try:
        radio = esp32.Radio.open_serial(port, fast_baud=baud, left_at=left_at)
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
        behind = radio._written - radio._credited   # bytes the board's reader never took
        radio.stop()
    finally:
        radio.close()
    counted = after - before
    sent = total - radio.tx_dropped
    print(f"{baud:>8}  uplink {sent} of {total} written in {seconds:.1f}s, board counted {counted}, "
          f"lost {sent - counted}, bytes never read {behind}, flow resyncs {radio.flow_resyncs}; wire_rx_bad {fields['wire_rx_bad']} uart_fifo_ovf "
          f"{fields.get('uart_fifo_ovf')} uart_buffer_full {fields.get('uart_buffer_full')} "
          f"uart_frame_err {fields.get('uart_frame_err')} uart_events_full {fields.get('uart_events_full')} "
          f"tx_eth_failed {fields['tx_eth_failed']} tx_eth_retried {fields['tx_eth_retried']}")


def trickle(port, baud, seconds, flood, ap=False, body=0, left_at=()):
    radio = esp32.Radio.open_serial(port, fast_baud=baud, left_at=left_at)
    try:
        if ap:
            radio.ap_start(11, "02:00:00:be:4c:01", "pokeldn-bench".ljust(32, "x"), os.urandom(16))
        before, _ = board_sent(radio)
        frame = b"\xff" * 6 + bytes.fromhex("0200000000be") + b"\x08\x00" + bytes(body)
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
          f"{fields.get('write_max_us')} uart_fifo_ovf {fields.get('uart_fifo_ovf')} heap_min "
          f"{fields.get('heap_min')} tx_eth_retried {fields.get('tx_eth_retried')}")


if __name__ == "__main__":
    sys.exit(main())
