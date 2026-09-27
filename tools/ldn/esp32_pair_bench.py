#!/usr/bin/env python3
"""Two boards, no console: board A hosts a network and floods the station with 1200-byte frames
at --flood per second, as a Scarlet host does in a retransmit storm; board B joins it and sends a
200-byte frame every 1/--send s, as the joiner's acks. Prints what B's host handed B, what B
counted, and B's STATUS maxima (read_max_us is the one a starved reader moves).
    ./.venv/bin/python tools/ldn/esp32_pair_bench.py AP_PORT STA_PORT [--seconds S] [--flood N]
        [--send N] [--bench]
--bench fills the station board's board-to-host line with BENCH while it sends, with the air free:
the condition in which a writer that spins on a full UART ring starved the reader.
--burst N sends N frames back to back per tick. A's RX_MGMT header copies count B's frames it
received and its misses: a sequence number first seen with the retry bit (docs/hardware_esp32.md).
--flood is broadcast from the access point, which an ESP32 sends at 1 Mbit/s: past about 90 a second
it fills the air itself. docs/hardware_esp32.md, The serial ceiling."""
import argparse, collections, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pokeldn.ldn import esp32

ap_ = argparse.ArgumentParser()
ap_.add_argument("ap_port"); ap_.add_argument("sta_port")
ap_.add_argument("--seconds", type=float, default=10)
ap_.add_argument("--flood", type=float, default=100)
ap_.add_argument("--send", type=float, default=150)
ap_.add_argument("--baud", type=int, default=1500000)
ap_.add_argument("--bench", action="store_true",
                 help="fill B's board-to-host line with BENCH meanwhile, with the air left free")
ap_.add_argument("--channel", type=int, default=6)
ap_.add_argument("--burst", type=int, default=1)
ap_.add_argument("--unicast", action="store_true", help="A's flood goes to B's MAC, acknowledged, not broadcast")
ap_.add_argument("--ap-flags", type=lambda v: int(v, 0), default=0, help="the AP_START flag byte")
ap_.add_argument("--ap-flags2", type=lambda v: int(v, 0), default=0, help="the second AP_START flag byte")
ap_.add_argument("--done-out", help="write B's TX-dones as 'board_us since_us host_time' lines, "
                 "and A's as 'board_us host_time' to FILE.ap")
ap_.add_argument("--size", type=int, default=200, help="B's frame length")
ap_.add_argument("--sta-rate", type=int, default=0, choices=range(8),
                 help="pin B's data rate: 1 1M, 2 11M, 3 6M, 4 12M, 5 24M, 6 36M, 7 54M; 0 rate control")
ap_.add_argument("--sta-power", type=int, default=0, help="B's maximum TX power, 0.25 dBm units (8..84)")
args = ap_.parse_args()

key, ssid = os.urandom(16), os.urandom(16).hex()
a = esp32.Radio.open_serial(args.ap_port, fast_baud=args.baud, log=lambda s: print("A", s))
b = esp32.Radio.open_serial(args.sta_port, fast_baud=args.baud, log=lambda s: print("B", s))
bssid = bytes.fromhex("020000be4c01")
link, joined = threading.Event(), threading.Event()
got_from_b = collections.Counter(); t0 = [None]; sta_mac = [bytes(6)]
b_done = []
def on_b(t, p):
    if t == esp32.MSG_TX_DONE and t0[0] and len(p) >= 8:
        board_us, since = int.from_bytes(p[:4], "little"), int.from_bytes(p[4:8], "little")
        if since != 0xFFFFFFFF: b_done.append((since, board_us, time.time()))
    elif t == esp32.MSG_LINK and p[:1] == b"\x01":
        sta_mac[0] = p[3:9]; link.set()
b.subscribe(on_b)

a_since = []; a_rx = []; a_done = []; heard = {}; a_copies = collections.Counter(); a_rssi = collections.Counter()
def on_a(t, p):
    if t == esp32.MSG_RX_MGMT and t0[0] and args.ap_flags2 & 4 and len(p) >= 30:
        stamp, p = int.from_bytes(p[2:6], "little"), p[:2] + p[6:]   # RX_TIME: the head carries it
    else:
        stamp = None
    if t == esp32.MSG_RX_MGMT and t0[0] and len(p) >= 26 and p[12:18] == sta_mac[0] and (p[2] >> 2) & 3 == 2:
        seq, retry = int.from_bytes(p[24:26], "little") >> 4, bool(p[3] & 8)
        # a gap over 1 s is the sequence number wrapping: a new frame
        new = seq not in heard or time.monotonic() - heard[seq] > 1.0
        a_copies["frames" if new else "duplicates"] += 1
        if stamp is not None: a_rx.append((stamp, int(new and retry)))
        if new and retry: a_copies["missed first copy"] += 1
        heard[seq] = time.monotonic(); a_rssi[p[1] - 256 if p[1] > 127 else p[1]] += 1
    elif t == esp32.MSG_TX_DONE and t0[0] and len(p) >= 8:
        a_done.append((int.from_bytes(p[:4], "little"), time.time()))
        since = int.from_bytes(p[4:8], "little")
        if since != 0xFFFFFFFF: a_since.append(since); a_copies["A unacked"] += len(p) > 8 and not p[8]
    elif t == esp32.MSG_STA_JOINED:
        joined.set()
    elif t == esp32.MSG_RX_ETH and t0[0] and p[12:14] == b"\x88\xb6":
        got_from_b[int(time.monotonic() - t0[0])] += 1
a.subscribe(on_a)
a.ap_start(args.channel, bssid, ssid, key, flags=args.ap_flags, flags2=args.ap_flags2)
b.sta_join(args.channel, bssid, ssid, key, rate=args.sta_rate, power=args.sta_power)
if not link.wait(20) or not joined.wait(5):
    b.close(); a.close()
    sys.exit(f"no association: link {link.is_set()} joined {joined.is_set()}")
print(f"associated; A floods {args.flood:.0f}/s, B sends {args.send:.0f}/s for {args.seconds:.0f} s")

def fields(r):
    return dict(kv.split("=", 1) for kv in r.status().split() if "=" in kv)

stop = threading.Event(); handed = collections.Counter()
def flood():
    frame = (sta_mac[0] if args.unicast else b"\xff" * 6) + bssid + b"\x88\xb5" + os.urandom(1186)
    while not stop.is_set():
        a.send_ethernet(frame); time.sleep(1 / args.flood)
sent = [0]
def send():
    # The source must be the station MAC LINK reported: the driver sends it as addr2, and the AP
    # acknowledges no frame from another transmitter. docs/hardware_esp32.md
    frame = b"\xff" * 6 + sta_mac[0] + b"\x88\xb6" + os.urandom(args.size - 14)
    while not stop.is_set():
        for _ in range(args.burst):
            b.send_ethernet(frame); sent[0] += 1
        time.sleep(1 / args.send)
t0[0] = time.monotonic()
def bench():
    r = b.bench(int(150_000 * args.seconds), 1400, timeout=args.seconds * 4 + 10)
    print(f"B BENCH {r['rate'] / 1000:.0f} KB/s over {r['seconds']:.1f} s")
jobs = [send] + ([flood] if args.flood else []) + ([bench] if args.bench else [])
threads = [threading.Thread(target=f) for f in jobs]
for t in threads: t.start()
time.sleep(args.seconds)
stop.set()
for t in threads: t.join()
b.drain(60); time.sleep(1)
f = dict(kv.split("=", 1) for kv in b.request(esp32.CMD_STATUS, b"", esp32.MSG_STATUS, timeout=30)
         .decode(errors="replace").split() if "=" in kv)
print(f"B handed {sent[0]} ETH_TX, board counted tx_eth {f.get('tx_eth')} failed {f.get('tx_eth_failed')}")
print(f"A received {sum(got_from_b.values())} of B's frames; B's driver: tx_acked {f.get('tx_acked')} "
      f"tx_unacked {f.get('tx_unacked')}, queued max {f.get('tx_queued_max_us')} us, total "
      f"{f.get('tx_queued_total_us')} us over {f.get('tx_queued_n')}")
print(f"A's header copies of B's frames: {dict(a_copies)}; missed first copies "
      f"{100 * a_copies['missed first copy'] / max(1, a_copies['frames']):.1f}%; A's RSSI {sorted(a_rssi.items())}")
if b_done:
    if args.done_out and a_done:
        with open(args.done_out + ".ap", "w") as out:   # A's clock against the host's
            out.writelines(f"{u} {h:.6f}\n" for u, h in a_done)
    if args.done_out and a_rx:
        with open(args.done_out + ".rx", "w") as out:   # A's receive time, 1 when a first copy was missed
            out.writelines(f"{u} {m}\n" for u, m in a_rx)
    if args.done_out:
        with open(args.done_out, "w") as out:
            out.writelines(f"{u} {s} {h:.6f}\n" for s, u, h in b_done)
    d = sorted(s for s, _, _ in b_done); q = lambda f: d[min(len(d) - 1, int(f * len(d)))]
    print(f"B's ETH_TX to TX-done, us: median {q(0.5)} p90 {q(0.9)} p99 {q(0.99)}; over 1 ms "
          f"{100 * sum(x > 1000 for x in d) / len(d):.1f}%, over 3 ms {100 * sum(x > 3000 for x in d) / len(d):.1f}%")
if a_since:
    d = sorted(a_since); q = lambda f: d[min(len(d) - 1, int(f * len(d)))]
    print(f"A's ETH_TX to TX-done, us: n {len(d)} median {q(0.5)} p99 {q(0.99)} max {d[-1]}; "
          f"over 20 ms {sum(x > 20000 for x in d)}, over 50 ms {sum(x > 50000 for x in d)}")
print(f"B: handler_max_us {f.get('handler_max_us')} type {f.get('handler_max_type')} heap_min "
      f"{f.get('heap_min')} wire_dropped {f.get('wire_dropped')} rx_eth {f.get('rx_eth')} "
      f"tx_eth_retried {f.get('tx_eth_retried')} resyncs {b.flow_resyncs} write_max_us {f.get('write_max_us')} tx_eth_max_us {f.get('tx_eth_max_us')} tx_eth_total_us {f.get('tx_eth_total_us')} tx_eth_slow {f.get('tx_eth_slow')} read_max_us {f.get('read_max_us')} queue_max {f.get('queue_max')}")
b.stop(); a.stop(); b.close(); a.close()
