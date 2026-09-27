#!/usr/bin/env python3
"""Per 802.11 sequence number, the console's copies of a frame to the board: how many the sniffer saw
and how many the board's own receive path saw (RX_MGMT 0x84 head copies).
    tools/ldn/esp32_rx_copies.py HOST_TRACE SNIFF_TRACE --ap BSSID --sta MAC"""
import argparse, collections
ap = argparse.ArgumentParser(); ap.add_argument("host"); ap.add_argument("sniff")
ap.add_argument("--ap", required=True); ap.add_argument("--sta", required=True); a = ap.parse_args()

def copies(path, op, skip):
    c = collections.defaultdict(list)
    for line in open(path, errors="replace"):
        f = line.split()
        if len(f) < 4 or f[1] != "<" or int(f[2], 16) != op: continue
        w = bytes.fromhex(f[3])[skip:]
        if len(w) < 24 or (w[0] >> 2) & 3 != 2: continue
        if w[4:10].hex(":") != a.ap or w[10:16].hex(":") != a.sta: continue
        c[int.from_bytes(w[22:24], "little") >> 4].append((float(f[0]), bool(w[1] & 8)))
    return c

def split(c):
    # the sequence number wraps at 4096: a gap over 1 s starts another frame
    out = {}
    for s, l in c.items():
        l.sort(); k = 0; out[(s, k)] = [l[0]]
        for x, y in zip(l, l[1:]):
            if y[0] - x[0] > 1.0: k += 1; out[(s, k)] = []
            out[(s, k)].append(y)
    return out

sn = split(copies(a.sniff, 0x8C, 5)); bd = split(copies(a.host, 0x84, 2))
common = sorted(set(sn) & set(bd))
tab = collections.Counter()
for s in common:
    ns, nb = len(sn[s]), len(bd[s]); tab[(min(ns, 4), min(nb, 4))] += 1
print(f"seqs: sniffer {len(sn)}, board {len(bd)}, both {len(common)}, sniffer only {len(set(sn)-set(bd))}, board only {len(set(bd)-set(sn))}")
print("sniffer copies x board copies (4 = 4+): count")
for k, n in sorted(tab.items()): print(f"  {k[0]} x {k[1]}: {n}")
multi = [s for s in common if len(sn[s]) > 1]
print(f"retried on air: {len(multi)}; board heard 1 copy of {sum(len(bd[s])==1 for s in multi)}, "
      f"2+ copies of {sum(len(bd[s])>1 for s in multi)}")
one = [s for s in multi if len(bd[s]) == 1]
print(f"of those with one board copy, the board's copy carries the retry bit on "
      f"{sum(bd[s][0][1] for s in one)} of {len(one)} (a retry: the board missed the first copy)")
first = collections.Counter(); later = collections.Counter()
for line in open(a.sniff, errors="replace"):
    f = line.split()
    if len(f) < 4 or f[1] != "<" or int(f[2], 16) != 0x8C: continue
    p = bytes.fromhex(f[3]); w = p[5:]
    if len(w) < 24 or (w[0] >> 2) & 3 != 2 or w[4:10].hex(":") != a.ap or w[10:16].hex(":") != a.sta: continue
    (later if w[1] & 8 else first)[p[3]] += 1
print("console->board rate codes, first copies:", first.most_common(5), " retries:", later.most_common(6))
rssi = collections.Counter()
for line in open(a.host, errors="replace"):
    f = line.split()
    if len(f) >= 4 and f[1] == "<" and int(f[2], 16) == 0x84:
        b = bytes.fromhex(f[3])
        if len(b) > 26 and b[2+10:2+16].hex(":") == a.sta: rssi[b[1] - 256 if b[1] > 127 else b[1]] += 1
print("board's RSSI for the console's frames:", sorted(rssi.items()))
# a first copy the board missed is one followed by a retry (the board heard no first copy, see above)
NAMES = {8: "48M", 9: "24M", 10: "12M", 11: "6M", 12: "54M", 13: "36M", 14: "18M", 15: "9M", 3: "11M"}
seen = collections.defaultdict(list)
for line in open(a.sniff, errors="replace"):
    f = line.split()
    if len(f) < 4 or f[1] != "<" or int(f[2], 16) != 0x8C: continue
    p = bytes.fromhex(f[3]); w = p[5:]
    if len(w) < 24 or (w[0] >> 2) & 3 != 2 or w[4:10].hex(":") != a.ap or w[10:16].hex(":") != a.sta: continue
    seen[int.from_bytes(w[22:24], "little") >> 4].append((float(f[0]), p[3]))
fr = collections.Counter(); fr_missed = collections.Counter()
for s, l in seen.items():
    l.sort(); groups = [[l[0]]]
    for x, y in zip(l, l[1:]):
        (groups.append([y]) if y[0] - x[0] > 1.0 else groups[-1].append(y))
    for g in groups:
        fr[g[0][1]] += 1; fr_missed[g[0][1]] += len(g) > 1
print("first copy rate: sent, then retried:", {NAMES.get(r, r): (n, f"{100*fr_missed[r]/n:.1f}%") for r, n in fr.items()})
