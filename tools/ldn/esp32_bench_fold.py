#!/usr/bin/env python3
"""Fold a pair bench's --done-out (board_us since_us) at a period: the slow share per tenth.
    tools/ldn/esp32_bench_fold.py FILE [PERIOD_US ...] [--slow US]"""
import collections, sys
args = [a for a in sys.argv[1:]]
slow_us = 3000
if "--slow" in args:
    i = args.index("--slow"); slow_us = int(args[i + 1]); del args[i:i + 2]
path, periods = args[0], [int(x) for x in args[1:]] or [102_400, 1_024_000, 1_000_000]
rows = [tuple(map(int, l.split())) for l in open(path)]
sent = [(u - s, s > slow_us) for u, s in rows]
print(f"{len(rows)} frames, {sum(x for _, x in sent)} over {slow_us} us")
for period in periods:
    n = collections.Counter(); k = collections.Counter()
    for t, sl in sent:
        b = int((t % period) / period * 20); n[b] += 1; k[b] += sl
    print(f"{period:>8} us:", " ".join(f"{100 * k[i] / max(1, n[i]):3.0f}" for i in range(20)))
