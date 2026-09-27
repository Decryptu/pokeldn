#!/usr/bin/env python3
"""Which board's clock a periodic loss follows: each board's clock rate against the host's, then the
fold period (in ppm off 100 TU on the station's clock) at which the slow frames bunch the most.
    tools/ldn/esp32_bench_drift.py DONE_FILE [--slow US]
DONE_FILE is esp32_pair_bench.py --done-out (the station), DONE_FILE.ap the access point's TX-dones.
A cycle on the station's own clock peaks at 0 ppm; one on the access point's peaks at the access
point's rate minus the station's."""
import argparse, collections, math
ap = argparse.ArgumentParser(); ap.add_argument("done"); ap.add_argument("--slow", type=int, default=3000)
ap.add_argument("--period", type=int, default=102_400); a = ap.parse_args()

def rate_ppm(pairs):
    # board us against host s: the least-lagged point of each 10 s window, then a least-squares line
    win = {}
    for u, h in pairs:
        k = int(h // 10); lag = h * 1e6 - u
        if k not in win or lag < win[k][0]: win[k] = (lag, u, h)
    xs = [h for _, _, h in win.values()]; ys = [u for _, u, _ in win.values()]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return (slope / 1e6 - 1) * 1e6

sta = [l.split() for l in open(a.done)]
sta_pairs = [(int(u), float(h)) for u, _, h in sta]
ap_pairs = [(int(u), float(h)) for u, h in (l.split() for l in open(a.done + ".ap"))]
r_sta, r_ap = rate_ppm(sta_pairs), rate_ppm(ap_pairs)
print(f"clock rate against the host: station {r_sta:+.1f} ppm, access point {r_ap:+.1f} ppm; "
      f"access point minus station {r_ap - r_sta:+.1f} ppm")
sent = [int(u) - int(s) for u, s, _ in sta if int(s) > a.slow]
print(f"{len(sta)} frames, {len(sent)} slow")
best = []
for ppm in range(-80, 81):
    p = a.period * (1 + ppm / 1e6)
    n = collections.Counter(int((t % p) / p * 40) for t in sent)
    # concentration: the share of slow frames in the fullest 4 of 40 bins
    best.append((sum(sorted(n.values())[-4:]) / len(sent), ppm))
best.sort(reverse=True)
print("most bunched (share in the fullest tenth, ppm):", [(f"{s:.2f}", p) for s, p in best[:5]])
print("at 0 ppm:", f"{dict((p, s) for s, p in best)[0]:.2f}")
