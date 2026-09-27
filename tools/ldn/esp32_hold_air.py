#!/usr/bin/env python3
"""What the console sent on the air while a head-of-line frame was held, in sniffer (air) order.

    tools/ldn/esp32_hold_air.py HOST_TRACE SNIFF_TRACE --ap MAC --sta MAC [--min-ms 100]

Holds come from the host trace's TX_DONE (0x8D): a frame done more than --min-ms after the previous
TX-done. Each is found in the sniff trace by the access point's 802.11 sequence number; the console's
frames from the head frame's first copy to its last are listed with their power-management bit.
A sniffer on firmware that keeps ACKs also shows each ACK, and counts copies acknowledged on the air
and yet sent again: the sender missed that ACK.
The sniffer's arrival times lag the air, so only the order is used; --ap is the board's BSSID
(the sender of most frames to --sta), not an infrastructure access point on the same channel."""
import argparse
import struct


def frames(path):
    for line in open(path, errors="replace"):
        f = line.split()
        if len(f) < 4 or f[1] != "<" or int(f[2], 16) != 0x8C:
            continue
        p = bytes.fromhex(f[3])
        w = p[5:]
        if len(w) == 10 and w[0] == 0xD4:   # an ACK names only its receiver
            yield dict(t=float(f[0]), type=1, sub=13, flags=w[1], a1=w[4:10].hex(":"), a2="", seq=-1,
                       retry=False, pm=False, rate=p[2:5].hex(), rssi=p[1] - 256)
            continue
        if len(w) < 24:
            continue
        fc0, fc1 = w[0], w[1]
        yield dict(t=float(f[0]), type=(fc0 >> 2) & 3, sub=fc0 >> 4, flags=fc1,
                   a1=w[4:10].hex(":"), a2=w[10:16].hex(":"), seq=struct.unpack_from("<H", w, 22)[0] >> 4,
                   retry=bool(fc1 & 0x08), pm=bool(fc1 & 0x10), rate=p[2:5].hex(), rssi=p[1] - 256)


ap = argparse.ArgumentParser()
ap.add_argument("host_trace")
ap.add_argument("sniff_trace")
ap.add_argument("--ap", required=True)
ap.add_argument("--sta", required=True)
ap.add_argument("--min-ms", type=float, default=100.0)
ap.add_argument("--context", type=int, default=3)
a = ap.parse_args()

done = []
for line in open(a.host_trace, errors="replace"):
    f = line.split()
    if len(f) >= 4 and f[1] == "<" and int(f[2], 16) == 0x8D:
        b = bytes.fromhex(f[3])
        board_us, since_us = struct.unpack_from("<II", b)
        seq = struct.unpack_from("<H", b, 34)[0] >> 4 if len(b) >= 36 else -1
        if since_us < 5_000_000:
            done.append((board_us, since_us, seq, float(f[0])))
done.sort()
holds = []
for (pb, _, _, _), (b, since, seq, t) in zip(done, done[1:]):
    if (b - pb) / 1000 > a.min_ms and since / 1000 > a.min_ms:
        holds.append((seq, since / 1000, t))

sn = list(frames(a.sniff_trace))
pm_total = sum(1 for x in sn if x["a2"] == a.sta and x["pm"])
sta_total = sum(1 for x in sn if x["a2"] == a.sta)
print(f"sniffed {len(sn)} frames; console {sta_total}, PM=1 on {pm_total}")
acks = sum(1 for x in sn if x["type"] == 1)
if acks:
    # Firmware that sniffs ACKs: whether the frame after each data copy is an ACK to its sender.
    def acked(i):
        return i + 1 < len(sn) and sn[i + 1]["type"] == 1 and sn[i + 1]["a1"] == sn[i]["a2"]
    for name, src, dst in (("board to console", a.ap, a.sta), ("console to board", a.sta, a.ap)):
        idx = [i for i, x in enumerate(sn) if x["type"] == 2 and x["a2"] == src and x["a1"] == dst]
        # a copy that is followed by an ACK and yet sent again: the sender missed that ACK
        again = [i for i in idx if acked(i) and any(y["type"] == 2 and y["a2"] == src and y["seq"] ==
                 sn[i]["seq"] and y["retry"] for y in sn[i + 1:i + 12])]
        print(f"{name}: {len(idx)} data copies, {sum(map(acked, idx))} followed by an ACK; "
              f"{len(again)} acked yet sent again (the sender missed the ACK)")
for seq, waited, t in holds:
    idx = [i for i, x in enumerate(sn) if x["a2"] == a.ap and x["type"] == 2 and x["seq"] == seq
           and abs(x["t"] - t) < 2.0]
    if not idx:
        print(f"\nseq {seq} held {waited:.0f} ms: not in the sniff")
        continue
    lo, hi = idx[0], idx[-1]
    print(f"\nseq {seq} held {waited:.0f} ms: {len(idx)} copies seen, sniff span {lo}..{hi}")
    for i in range(max(0, lo - a.context), min(len(sn), hi + a.context + 1)):
        x = sn[i]
        who = "AP " if x["a2"] == a.ap else x["a2"]
        if x["type"] == 1:
            who = "ACK>AP" if x["a1"] == a.ap else "ACK>STA" if x["a1"] == a.sta else "ACK>" + x["a1"]
        if x["a2"] == a.sta:  # the console also talks to its home access point on the same channel
            who = "STA" if x["a1"] == a.ap else "STA>" + ("bcast" if x["a1"].startswith(("ff", "33")) else x["a1"])
        kind = {0: "mgmt", 1: "ctrl", 2: "data"}.get(x["type"], "?") + f"/{x['sub']}"
        mark = "*" if i in idx else " "
        print(f"  {mark}{i:6d} {who:21s} {kind:8s} seq {x['seq']:4d} {'R' if x['retry'] else ' '}"
              f"{'PM' if x['pm'] else '  '} rate {x['rate']} rssi {x['rssi']} t {x['t']:.3f}")
