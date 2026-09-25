#!/usr/bin/env python3
"""Two boards, no console: board A hosts a network and floods the station with 1200-byte frames
at --flood per second, as a Scarlet host does in a retransmit storm; board B joins it and sends a
200-byte frame every 1/--send s, as the joiner's acks. Prints what B's host handed B, what B
counted, and B's STATUS maxima (read_max_us is the one a starved reader moves).
    ./.venv/bin/python tools/ldn/esp32_pair_bench.py AP_PORT STA_PORT [--seconds S] [--flood N]
        [--send N] [--bench]
--bench fills the station board's board-to-host line with BENCH while it sends, with the air free:
the condition in which a writer that spins on a full UART ring starved the reader.
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
ap_.add_argument("--sta-mac", default="8c:94:df:58:cd:b8", help="board B's station MAC (esptool read-mac)")
args = ap_.parse_args()

key, ssid = os.urandom(16), os.urandom(16).hex()
a = esp32.Radio.open_serial(args.ap_port, fast_baud=args.baud)
b = esp32.Radio.open_serial(args.sta_port, fast_baud=args.baud)
bssid = bytes.fromhex("020000be4c01")
link, joined = threading.Event(), threading.Event()
got_from_b = collections.Counter(); t0 = [None]
b.subscribe(lambda t, p: link.set() if t == esp32.MSG_LINK and p[:1] == b"\x01" else None)

def on_a(t, p):
    if t == esp32.MSG_STA_JOINED:
        joined.set()
    elif t == esp32.MSG_RX_ETH and t0[0] and p[12:14] == b"\x88\xb6":
        got_from_b[int(time.monotonic() - t0[0])] += 1
a.subscribe(on_a)
a.ap_start(args.channel, bssid, ssid, key)
b.sta_join(args.channel, bssid, ssid, key)
if not link.wait(20) or not joined.wait(5):
    b.close(); a.close()
    sys.exit(f"no association: link {link.is_set()} joined {joined.is_set()}")
sta_mac = bytes.fromhex(args.sta_mac.replace(":", ""))
print(f"associated; A floods {args.flood:.0f}/s, B sends {args.send:.0f}/s for {args.seconds:.0f} s")

def fields(r):
    return dict(kv.split("=", 1) for kv in r.status().split() if "=" in kv)

stop = threading.Event(); handed = collections.Counter()
def flood():
    frame = b"\xff" * 6 + bssid + b"\x88\xb5" + os.urandom(1186)
    while not stop.is_set():
        a.send_ethernet(frame); time.sleep(1 / args.flood)
sent = [0]
def send():
    frame = b"\xff" * 6 + (sta_mac or bytes(6)) + b"\x88\xb6" + os.urandom(186)
    while not stop.is_set():
        b.send_ethernet(frame); sent[0] += 1; time.sleep(1 / args.send)
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
print(f"B: handler_max_us {f.get('handler_max_us')} type {f.get('handler_max_type')} heap_min "
      f"{f.get('heap_min')} wire_dropped {f.get('wire_dropped')} rx_eth {f.get('rx_eth')} "
      f"tx_eth_retried {f.get('tx_eth_retried')} resyncs {b.flow_resyncs} write_max_us {f.get('write_max_us')} tx_eth_max_us {f.get('tx_eth_max_us')} tx_eth_total_us {f.get('tx_eth_total_us')} tx_eth_slow {f.get('tx_eth_slow')} read_max_us {f.get('read_max_us')} queue_max {f.get('queue_max')}")
b.stop(); a.stop(); b.close(); a.close()
