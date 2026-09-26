#!/usr/bin/env python3
"""Where a host datagram waited on its way to the air, per stage, on the ESP32 board.

    tools/ldn/esp32_hold.py HOST_CAPTURE.jsonl HOST_TRACE [--min-ms 100]

Stages: udp_out (capture) -> ETH_TX written (trace '>' 08) -> board receives it (TX_DONE board time
minus its since-ETH_TX field, mapped to host time by the smallest arrival offset) -> TX-done.
Prints each stage's median / p99 / max, the datagrams over --min-ms end to end, and the largest
gaps in the udp_out stream and in the TX-done stream (a hold shows as a TX-done gap with no udp_out gap),
and the head-of-line holds: a frame that waited over --min-ms after the previous TX-done.
"""
import argparse
import json
import statistics
import struct


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else float("nan")


def show(name, v):
    if v:
        print(f"{name:28s} n={len(v):5d}  median {statistics.median(v):7.2f} ms  p99 {pct(v, .99):7.2f} ms"
              f"  max {max(v):7.2f} ms")


def gaps(ts, n=5):
    d = sorted(((b - a) * 1000, a) for a, b in zip(ts, ts[1:]))
    return d[-n:][::-1]


ap = argparse.ArgumentParser()
ap.add_argument("capture")
ap.add_argument("trace")
ap.add_argument("--min-ms", type=float, default=100.0)
a = ap.parse_args()

udp = []
for line in open(a.capture):
    r = json.loads(line)
    if r.get("kind") == "udp_out":
        udp.append((float(r["ts"]), r["hex"]))

eth, done = [], []
for line in open(a.trace, errors="replace"):
    f = line.split()
    if len(f) < 4:
        continue
    t, d, op, h = float(f[0]), f[1], int(f[2], 16), f[3]
    if d == ">" and op == 0x08:
        eth.append((t, h, len(h) // 2))
    elif d == "<" and op == 0x8D:
        b = bytes.fromhex(h)
        board_us, since_us, acked, iface, length = struct.unpack_from("<IIBBH", b)
        seq = struct.unpack_from("<H", b, 34)[0] >> 4 if len(b) >= 36 else -1
        done.append((t, board_us, since_us, acked, length, seq))

# udp_out -> the ETH_TX that carries its payload, in order.
host_ms, pairs, j = [], [], 0
for t, hx in udp:
    k = j
    while k < len(eth) and hx not in eth[k][1]:
        k += 1
    if k == len(eth):
        continue
    host_ms.append((eth[k][0] - t) * 1000)
    pairs.append((t, k))
    j = k + 1

matched = [x for x in done if x[2] != 0xFFFFFFFF]
board_ms = [x[2] / 1000 for x in matched]
unacked = sum(1 for x in matched if not x[3])

# TX-done -> its ETH_TX by length (802.11 = Ethernet + 14): the earliest unpaired ETH_TX of that
# length within 32 of the cursor. TX-dones complete out of order and the board's receive times can
# swap two frames the host wrote 0.1 ms apart, so the search looks back as well as forward.
of_eth, used, i = {}, set(), 0
for m in matched:
    for k in range(max(0, i - 32), min(i + 32, len(eth))):
        if k not in used and eth[k][2] + 14 == m[4]:
            of_eth[k] = m
            used.add(k)
            i = max(i, k + 1)
            break


def offset(t_board):
    """host time - board time, the smallest over TX-dones within 5 s (drift-tolerant lower bound)."""
    return min(t - bu / 1e6 for t, bu, *_ in matched if abs(bu / 1e6 - t_board) < 5)


offs = {}
for m in matched:
    key = int(m[1] / 1e6)
    if key not in offs:
        offs[key] = offset(m[1] / 1e6)
host_of = lambda bu: bu / 1e6 + offs[int(bu / 1e6)]
line_ms = [(t - host_of(bu)) * 1000 for t, bu, *_ in matched]
serial_ms, end_ms, end_at = [], [], []
for tu, k in pairs:
    if k in of_eth:
        _, bu, s = of_eth[k][:3]
        serial_ms.append((host_of(bu - s) - eth[k][0]) * 1000)
        end_ms.append((host_of(bu) - tu) * 1000)
        end_at.append(tu)

print(f"udp_out {len(udp)}, ETH_TX {len(eth)}, matched to ETH_TX {len(host_ms)}, TX_DONE {len(done)} "
      f"({len(matched)} for an ETH_TX, {unacked} not acked by the peer)")
show("udp_out -> ETH_TX written", host_ms)
show("ETH_TX -> board (approx)", serial_ms)
show("board queue -> TX-done", board_ms)
show("TX_DONE line lag", line_ms)
show("udp_out -> TX-done (approx)", end_ms)
print(f"TX-dones paired with an ETH_TX by length: {len(of_eth)} of {len(matched)}")
over = [(e, tu) for e, tu in zip(end_ms, end_at) if e >= a.min_ms]
print(f"datagrams over {a.min_ms:.0f} ms end to end: {len(over)}")
for e, tu in over[:10]:
    print(f"   t={tu - udp[0][0]:8.3f}  {e:7.1f} ms")
print("largest udp_out gaps (ms, at t):", [(round(g, 1), round(t - udp[0][0], 3)) for g, t in gaps([t for t, _ in udp])])
dt = [host_of(bu) for _, bu, *_ in matched]
print("largest TX-done gaps (ms, at t):", [(round(g, 1), round(t - udp[0][0], 3)) for g, t in gaps(dt)])
heads = [(p, d) for p, d in zip(matched, matched[1:])
         if d[2] >= a.min_ms * 1000 and d[1] - p[1] >= a.min_ms * 800]
print(f"head-of-line holds: {len(heads)}")
for p, d in heads:
    behind = sum(1 for x in matched if 0 <= x[1] - d[1] <= 5000 and x is not d)
    print(f"   t={host_of(d[1]) - udp[0][0]:8.3f}  seq {d[5]:4d} waited {d[2] / 1000:6.1f} ms,"
          f" {behind} more done within 5 ms")
