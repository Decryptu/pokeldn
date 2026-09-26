#!/usr/bin/env python3
"""Reconcile the host's commands against the board's counts in a POKELDN_ESP32_TRACE file.

    tools/ldn/esp32_cmd_loss.py TRACE [TRACE ...] [--timeline]

For each STATUS reply: ETH_TX the host wrote before the STATUS request that produced it, against
the board's tx_eth + tx_eth_failed; bytes written since the last HELLO against the board's latest
CREDIT (bytes the reader took off the UART). A byte gap is loss on the line or in the UART; a
command gap with no byte gap is loss after the reader (parse or handler). A trace two launchers
appended (the Arceus joiner that execs the host) is rebased where the board's counts restart."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pokeldn.ldn.esp32 import encode_frame  # noqa: E402

COUNTERS = ("tx_eth", "tx_eth_failed", "wire_rx_bad", "uart_fifo_ovf", "uart_buffer_full",
            "wire_dropped", "mode", "tx_eth_retried", "read_max_us", "handler_max_us",
            "handler_max_type")


def status_fields(payload: bytes) -> dict:
    out = {}
    for item in payload.decode(errors="replace").split():
        k, _, v = item.partition("=")
        if k in COUNTERS:
            out[k] = int(v, 0)
    return out


def read(path, timeline):
    written = 0            # bytes since the last HELLO, as the host counts them
    eth = 0                # ETH_TX written since the trace began
    eth_at_request = []    # ETH_TX and bytes written at each STATUS request, in order
    credit = 0
    credit_max = 0
    join_at = None
    first = None
    prev = None
    rows = []
    eth_base = 0           # ETH_TX written before the board last rebooted (a second process)
    base_candidate, last_hello = 0, None
    resyncs = 0
    logs = []
    for line in open(path):
        parts = line.split(" ", 3)
        if len(parts) < 3:
            continue
        t = float(parts[0])
        first = first if first is not None else t
        direction, mtype = parts[1], int(parts[2], 16)
        payload = bytes.fromhex(parts[3].strip()) if len(parts) > 3 and parts[3].strip() else b""
        if direction == ">":
            written += len(encode_frame(mtype, payload))
            if mtype == 0x01:
                written = credit = 0
                # Opening the port reboots the board; its first HELLO follows a quiet line.
                if last_hello is None or t - last_hello > 5:
                    base_candidate = eth
                last_hello = t
            elif mtype == 0x08:
                eth += 1
            elif mtype == 0x04 and join_at is None:
                join_at = t
            elif mtype == 0x0B:
                eth_at_request.append((eth, written, t))
        elif direction == "!":
            resyncs += 1
        elif direction == "<":
            if mtype == 0x8B and len(payload) == 4:
                credit = int.from_bytes(payload, "little")
                credit_max = max(credit_max, credit)
            elif mtype == 0x83:
                logs.append((t, payload.decode(errors="replace")))
            elif mtype == 0x89 and eth_at_request:
                sent, wrote, asked = eth_at_request.pop(0)
                f = status_fields(payload)
                counted = f.get("tx_eth", 0) + f.get("tx_eth_failed", 0)
                if prev is not None and counted < prev[2]:
                    eth_base = base_candidate
                sent -= eth_base
                row = (t, sent, counted, f)
                if timeline and (prev is None or sent - counted != prev[1] - prev[2]
                                 or f.get("wire_rx_bad") != prev[3].get("wire_rx_bad")):
                    base = join_at or first
                    print(f"  {t - base:8.2f}s  sent {sent:5d} counted {counted:5d} "
                          f"lost {sent - counted:4d}  rx_bad {f.get('wire_rx_bad', 0)} "
                          f"fifo {f.get('uart_fifo_ovf', 0)} full {f.get('uart_buffer_full', 0)} "
                          f"mode {f.get('mode')} bytes_behind {wrote - credit}")
                prev = row
                rows.append(row)
    return rows, resyncs, logs, written, credit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="+")
    ap.add_argument("--timeline", action="store_true")
    ap.add_argument("--logs", action="store_true")
    a = ap.parse_args()
    for path in a.traces:
        name = os.path.basename(path).replace("_esp32.trace", "")
        if a.timeline:
            print(name)
        rows, resyncs, logs, written, credit = read(path, a.timeline)
        if not rows:
            print(f"{name:12s} no STATUS")
            continue
        _, sent, counted, f = rows[-1]
        print(f"{name:12s} eth sent {sent:5d} counted {counted:5d} lost {sent - counted:4d}  "
              f"rx_bad {f.get('wire_rx_bad', 0):3d} fifo {f.get('uart_fifo_ovf', 0):3d} "
              f"full {f.get('uart_buffer_full', 0):3d} resyncs {resyncs}  "
              f"end bytes {written} credit {credit}")
        if a.logs:
            for t, text in logs:
                print(f"    LOG {text}")


if __name__ == "__main__":
    main()
