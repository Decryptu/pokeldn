#!/usr/bin/env python3
"""What else is on the air: one board visits each channel and counts every frame it receives,
corrupted ones (FCS failures) included, with their airtime, RSSI and the radio's noise floor.
docs/hardware_esp32.md, Two boards reproduce the misses.

    ./.venv/bin/python tools/ldn/esp32_census.py --port /dev/cu.usbserial-XXXX \\
        [--channels 1,3,5,6,7,9,11] [--dwell 30] [--passes 1] [--out FILE]
"""
import argparse
import collections
import math
import os
import statistics
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# wifi_phy_rate_t legacy codes -> Mbit/s
LEGACY = {0: 1, 1: 2, 2: 5.5, 3: 11, 5: 2, 6: 5.5, 7: 11, 8: 48, 9: 24, 10: 12, 11: 6, 12: 54,
          13: 36, 14: 18, 15: 9}
HT_BITS = [26, 52, 78, 104, 156, 208, 234, 260]   # data bits per 4 us symbol, MCS 0-7, 20 MHz


def airtime_us(sig_mode: int, rate: int, mcs: int, length: int) -> float:
    """A frame's time on the air from its length and PHY rate (long GI, no STBC)."""
    if sig_mode == 0:
        mbps = LEGACY.get(rate)
        if mbps is None:
            return 0.0
        if mbps in (1, 2, 5.5, 11):
            return (192 if rate < 5 else 96) + length * 8 / mbps
        bits = mbps * 4
        return 20 + 4 * math.ceil((16 + 8 * length + 6) / bits)
    bits = HT_BITS[(mcs & 0x7F) % 8] * ((mcs & 0x7F) // 8 + 1) * (2.077 if mcs & 0x80 else 1)
    return 36 + 4 * math.ceil((16 + 8 * length + 6) / bits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True)
    ap.add_argument("--channels", default="1,3,5,6,7,9,11")
    ap.add_argument("--dwell", type=float, default=30)
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--out", help="append each record as 'channel board_us rssi nf state type mode rate "
                                  "mcs len addr2' lines")
    args = ap.parse_args()
    from pokeldn.ldn import esp32
    radio = esp32.Radio.open_serial(args.port, log=print)
    recs = []
    radio.subscribe(lambda t, p: recs.append(p) if t == esp32.MSG_RX_CENSUS and len(p) >= 13 else None)
    out = open(args.out, "a") if args.out else None
    for _ in range(args.passes):
        for ch in [int(c) for c in args.channels.split(",")]:
            radio.sniff(ch, "ff:ff:ff:ff:ff:ff")
            time.sleep(0.5)
            recs.clear()
            time.sleep(args.dwell)
            got = list(recs)
            radio.stop()
            good = collections.Counter(); bad = 0; air = 0.0; bad_air = 0.0; nf = []; bad_rssi = []
            senders = collections.defaultdict(list); kinds = collections.Counter()
            for p in got:
                u = int.from_bytes(p[:4], "little")
                rssi, noise = p[4] - 256 if p[4] > 127 else p[4], p[5] - 256 if p[5] > 127 else p[5]
                state, ptype, mode, rate, mcs = p[6], p[7], p[8], p[9], p[10]
                length = int.from_bytes(p[11:13], "little"); frame = p[13:]
                t = airtime_us(mode, rate, mcs, length); nf.append(noise)
                a2 = frame[10:16].hex(":") if len(frame) >= 16 else "-"
                if out:
                    out.write(f"{ch} {u} {rssi} {noise} {state} {ptype} {mode} {rate} {mcs} {length} {a2}\n")
                if state:
                    bad += 1; bad_air += t; bad_rssi.append(rssi); continue
                air += t
                kinds["DSSS" if mode == 0 and LEGACY.get(rate, 0) in (1, 2, 5.5, 11) else
                      "OFDM" if mode == 0 else "HT"] += 1
                if a2 != "-" and ptype != 2 or (ptype == 2 and len(frame) >= 16):
                    senders[a2].append(rssi)
                good[ptype] += 1
            n_good = sum(good.values())
            print(f"channel {ch:2}: {n_good / args.dwell:6.0f} good/s ({dict(kinds)}), "
                  f"{bad / args.dwell:5.0f} FCS-fail/s, busy {100 * (air + bad_air) / (args.dwell * 1e6):4.1f}% "
                  f"(fails {100 * bad_air / (args.dwell * 1e6):3.1f}%), noise floor "
                  f"{statistics.median(nf) if nf else '-'}, fail RSSI median "
                  f"{statistics.median(bad_rssi) if bad_rssi else '-'}")
            top = sorted(senders.items(), key=lambda kv: -len(kv[1]))[:4]
            print("            " + ", ".join(f"{m} {len(v)} @{statistics.median(v):.0f}" for m, v in top))
    if out:
        out.close()
    radio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
