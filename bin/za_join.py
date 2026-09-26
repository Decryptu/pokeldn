#!/usr/bin/env python3
"""Join the network a searching Legends Z-A console puts up, and read what its Pia sends.

A console on the local search screen hosts its own network for a few seconds at a time, with a
fresh SSID each phase, and scans between them. It registers its Pia protocols while it hosts, so
the session is entered from that side: scan in a loop, take the seat when the network appears, and
log every datagram.

    sudo ./.venv/bin/python bin/za_join.py --seconds 600 --capture scratchpad/zaNN_join.jsonl

    (them) the local play menu, search, with the link code the run prints

The band is Pia header version 16, which is the GBA application's, so the packet header is
`pokeldn.ldn.crypto.PiaHeader`, the message framing is `pokeldn.ldn.reliable` and the Net, Session
and RTT layouts are `pokeldn.ldn.pia_connect`'s. What this title puts in them is unmeasured, which
is what the capture is for: every datagram in and out goes to --capture as one JSON line, and the
run ends with a tally of the protocol ids the console used.

`docs/za.md` has what the advertisement carries.
"""
import argparse
import json
import os
import socket
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(BUNDLED_LDN):
    sys.path.insert(0, BUNDLED_LDN)

import trio
import ldn

from pokeldn import za
from pokeldn.za import streams
from pokeldn.za.host import MSG_COMMIT, MSG_CONFIRM, OFFER_PICK, OFFER_PREVIEW
from pokeldn.ldn import crypto, host_pia, ldn_mitm, pia_connect, reliable
from pokeldn.ldn.transport import board_radio, find_ap_phy
from pokeldn.host_support import resolve_keys
from pokeldn.ldn import show_done

# The variable id we send as our own until the host names one. A retail joiner takes the id the
# host writes in the footer of its first mesh-addressed packet; this is the fallback.
OUR_VAR = 0xC493
STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]
# The protocol ids of the band, as the GBA application registers them. A native title numbers its
# own protocols and the names here are a starting guess, printed so a surprise is visible.
PROTOCOL_NAMES = {
    pia_connect.PROTO_NET: "net", pia_connect.PROTO_RTT: "rtt",
    pia_connect.PROTO_RELIABLE: "reliable", pia_connect.PROTO_SESSION: "session",
}


def cleanup_stale():
    if board_radio():
        return
    import subprocess
    for name in STALE_VIFS:
        subprocess.run(["iw", "dev", name, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_socket(ifname, our_ip=None):
    from pokeldn.ldn import userspace_ip  # no kernel interface (ESP32 on macOS)
    if our_ip is None and (user := userspace_ip.udp_socket(ifname, za.PIA_PORT)) is not None:
        user.setblocking(False)
        return user
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if our_ip is None:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, ifname.encode())
        except (PermissionError, OSError):
            pass
    s.bind((our_ip or "", za.PIA_PORT))
    s.setblocking(False)
    return s


def describe(net):
    app = bytes(net.application_data)
    code = ""
    try:
        code = f" code={za.parse_advertise_data(app)['code']}"
    except (ValueError, IndexError):
        pass
    return (f"comm_id=0x{net.local_communication_id:016x} scene={net.scene_id} "
            f"version={net.version} app_version={net.app_version} ch={net.channel} "
            f"{net.num_participants}/{net.max_participants}{code}")


def describe_msg(msg):
    name = PROTOCOL_NAMES.get(msg.proto, "?")
    return (f"proto 0x{msg.proto:02x} {name} flags=0x{msg.flags:02x} "
            f"msgflags=0x{msg.msgflags:02x} len={len(msg.payload)}")


GAME_RELIABLE = 10
GAME_BROADCAST = 11
# Protocol 11 is addressed to the mesh's pseudo-station, not to the host.
MESH_DESTINATION = 0x0001
# Every frame a station sends on protocol 11 carries three in the sub-header's recipient count.
BROADCAST_RECIPIENTS = 3
# A pure acknowledgement carries message flags 0x40 on both game protocols.
ACK_MESSAGE_FLAGS = 0x40
# The station index a Broadcast Reliable payload is prefixed with: the joiner is 1, the host 2.
BROADCAST_PREFIX_JOINER = bytes.fromhex("00000001")
# The fourth trade step; once it is out the trade is saved on both sides (docs/za.md).
LAST_STEP = bytes.fromhex("0200b9010e")


class GameStreams:
    """The game's own layer: two reliable streams, opened and fed the way a reference joiner does.

    A reference joiner opens protocol 10 with its identity under the INIT flag, opens protocol 11
    with a four-byte frame and repeats the identity there, then sends the 1211-byte selection
    record the partner's screen is drawn from, and an offer when the player chooses one.
    Payloads are replayed from the reference session until this project composes its own.
    """

    def __init__(self, args, send, send_messages, record):
        self.args = args
        self.send = send
        self.send_messages = send_messages
        self.record = record
        self.start = 0xFFF0
        self.links = {GAME_RELIABLE: reliable.ReliableLink(start=self.start),
                      GAME_BROADCAST: reliable.ReliableLink(start=self.start)}
        self.opened = False
        self.opened_at = None
        self.offer_sent = False
        self.picked = False
        self.host_offers = 0
        self.acted = set()
        self.scheduled = []
        self.selections = 0
        self.last_selection = 0.0
        self.traded_at = None
        self.ref = {}
        for name in ("identity10", "open11", "identity11", "identity11b", "selection"):
            path = os.path.join(args.game_dir, f"za_ref_{name}.bin")
            if os.path.exists(path):
                self.ref[name] = open(path, "rb").read()
        # The same record twice: the preview marked 1, the pick marked 0 (docs/za.md, Hosting).
        self.offer = self.preview = None
        if args.trade_offer:
            record = open(args.trade_offer, "rb").read()
            if getattr(args, "fresh_pid", False):
                record = za.pokemon.fresh_offer(record)
                plain = za.pokemon.parse_offer(record)[1]
                print(f"[za] offering pid {plain[0x1C:0x20][::-1].hex()} ec {plain[:4][::-1].hex()}")
            self.preview = record[:-1] + bytes([OFFER_PREVIEW])
            self.offer = record[:-1] + bytes([OFFER_PICK])
        self.seen = {}
        self.dst_var = 0
        self.src_var = 0

    def _emit(self, proto, seq, flags_a, inner):
        """Protocol 10 is addressed to the host, protocol 11 to the mesh id, and both carry the
        host's variable id in the footer and travel zstd-compressed, as a reference joiner's do."""
        link = self.links[proto]
        broadcast = proto == GAME_BROADCAST
        if broadcast:
            body = streams.frame(seq, link.send_low(), inner, flags_a, BROADCAST_RECIPIENTS)
        else:
            body = reliable.build_reliable(seq, link.send_low(), inner, flagsA=flags_a)
        dst = MESH_DESTINATION if broadcast else self.dst_var
        # A pure acknowledgement rides message flags 0x40; application data carries none.
        msgflags = ACK_MESSAGE_FLAGS if flags_a == reliable.FLAGSA_CTRL else None
        self.send(proto, body, dst_var=dst, src_var=self.src_var, establishing=False,
                  compress=True, footer_var=self.dst_var, msgflags=msgflags)

    def _queue(self, proto, inner, flags_a, now_ms):
        seq = self.links[proto].queue(inner, flags_a, now_ms)
        self._emit(proto, seq, flags_a, inner)
        return seq

    def open(self, now_ms):
        """The opening a reference joiner sends: the identity alone on protocol 10, then its three
        protocol-11 messages bundled into one packet."""
        if "identity10" in self.ref:
            self._queue(GAME_RELIABLE, self.ref["identity10"], reliable.FLAGSA_INIT, now_ms)
        bundle = []
        link = self.links[GAME_BROADCAST]
        for name, flags_a in (("open11", reliable.FLAGSA_INIT),
                              ("identity11", reliable.FLAGSA_GBA),
                              ("identity11b", reliable.FLAGSA_GBA)):
            if name not in self.ref:
                continue
            inner = self.ref[name]
            seq = link.queue(inner, flags_a, now_ms)
            bundle.append((GAME_BROADCAST,
                           streams.frame(seq, link.send_low(), inner, flags_a,
                                         BROADCAST_RECIPIENTS), None))
        if bundle:
            self.send_messages(bundle, dst_var=MESH_DESTINATION, src_var=self.src_var,
                               establishing=False, compress=True, footer_var=self.dst_var,
                               note="the protocol 11 opening, bundled")
        print(f"[za] the game's streams are open: "
              + ", ".join(f"{k} {len(v)}B" for k, v in self.ref.items()))

    def pump(self, dst_var, src_var, elapsed):
        self.dst_var, self.src_var = dst_var, src_var
        now_ms = int(elapsed * 1000)
        if not self.opened:
            self.opened = True
            self.opened_at = elapsed
            self.open(now_ms)
            return
        for proto, link in self.links.items():
            for seq, flags_a, inner in link.due_retransmits(now_ms, limit=4):
                self._emit(proto, seq, flags_a, inner)
        # The selection record is a heartbeat, not a one-off: a reference joiner sends it about
        # four times a second under a fresh sequence each time, and the partner's screen follows
        # the highlight it carries.
        if ("selection" in self.ref and self.selections < self.args.selection_count
                and elapsed - self.opened_at >= self.args.selection_delay
                and elapsed - self.last_selection >= self.args.selection_period):
            self.last_selection = elapsed
            self.selections += 1
            self._queue(GAME_RELIABLE, self.ref["selection"], reliable.FLAGSA_GBA, now_ms)
            if self.selections == 1:
                print(f"[za] the selection record is going out, {self.args.selection_count} times")
        if (self.offer and not self.offer_sent
                and elapsed - self.opened_at >= self.args.offer_delay):
            self.offer_sent = True
            self._queue(GAME_RELIABLE, self.preview, reliable.FLAGSA_GBA, now_ms)
            print(f"[za] sent the preview, {len(self.preview)} bytes")
        for item in [x for x in self.scheduled if x[0] <= elapsed]:
            self.scheduled.remove(item)
            self._queue(GAME_RELIABLE, item[1], reliable.FLAGSA_GBA, now_ms)
            print(f"[za] sent {item[1][:2].hex()} ({len(item[1])} bytes) at {elapsed:.2f}s")
            if item[1] == LAST_STEP:
                self.traded_at = elapsed
                show_done()
                print(f"[za] trade_complete at {elapsed:.2f}s")

    def _answer_trade(self, inner, elapsed):
        """A reference joiner's side of the trade: previews marked 1 each way, then the host's pick
        marked 0, answered with ours and 0102; then 0104 each way and four 0200 steps. A console
        sends a preview each time its cursor moves, so the pick is keyed on the mark. docs/za.md."""
        head = inner[:2].hex()
        if head == "0101":
            self.host_offers += 1
            if inner[-1:] == bytes([OFFER_PICK]) and self.offer and not self.picked:
                self.picked = True
                self.scheduled.append((elapsed + 1.5, self.offer))
                self.scheduled.append((elapsed + 3.0, MSG_CONFIRM))
        elif head == "0104":
            self.scheduled.append((elapsed + 0.03, MSG_COMMIT))
            for delay, step in ((0.09, "03"), (0.2, "06"), (14.4, "0b"), (14.6, "0e")):
                self.scheduled.append((elapsed + delay, bytes.fromhex("0200b901" + step)))

    def on_message(self, proto, payload, elapsed):
        link = self.links.get(proto)
        r = reliable.parse_reliable(payload)
        if link is None or r is None:
            return
        now_ms = int(elapsed * 1000)
        if r.flagsA == 0:
            ack_id, mask = reliable.parse_bulk_ack(r.payload[4:] if proto == GAME_BROADCAST
                                                   else r.payload)
            link.on_ack(ack_id, mask, now_ms)
            return
        link.note_received(r.seq)
        head = r.payload[4:8] if proto == GAME_BROADCAST else r.payload[:4]
        if proto == GAME_RELIABLE and r.seq not in self.acted:
            self.acted.add(r.seq)
            print(f"[za] host {head[:2].hex()} ({len(r.payload)} bytes) at {elapsed:.2f}s")
            self._answer_trade(r.payload, elapsed)
        key = (proto, head[:2].hex(), len(r.payload))
        if key not in self.seen:
            self.seen[key] = elapsed
            print(f"[za] the game sent message {head[:2].hex()} on protocol {proto}, "
                  f"{len(r.payload)} bytes, at {elapsed:.2f}s")
        if proto == GAME_BROADCAST:
            ack = streams.build_broadcast_ack(link.recv_next)
        else:
            ack = link.ack_payload()
        # A pure acknowledgement carries no sequence of its own: a reference station sends every
        # one of them on the stream's base, 0xfff0, and one that advances is read as data with a
        # hole behind it.
        self._emit(proto, self.start, reliable.FLAGSA_CTRL, ack)


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--channels", default="1,6,11")
    ap.add_argument("--dwell", type=float, default=1.0, help="seconds per channel in a scan")
    ap.add_argument("--seconds", type=float, default=600.0, help="the whole run")
    ap.add_argument("--hold", type=float, default=120.0, help="how long to hold one seat")
    ap.add_argument("--after-trade", type=float, default=90.0,
                    help="seconds to keep the seat after the fourth step, then exit the run")
    ap.add_argument("--quiet-seat", type=float, default=0.0,
                    help="end a seat on which the console has sent nothing for this long")
    ap.add_argument("--connect-timeout", type=float, default=12.0,
                    help="bound the association alone; the seat itself is not bounded by it")
    ap.add_argument("--name", default="pokeldn")
    ap.add_argument("--platform", type=int, default=1,
                    help="the station platform byte; both retail consoles here are Switch 2")
    ap.add_argument("--mac", default=None, help="give the phy this MAC before associating")
    ap.add_argument("--comm-id", default=None, help="hex; the default is Legends Z-A's")
    ap.add_argument("--code", default=None,
                    help="only join a console waiting on this link code")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--capture", default=None, help="every datagram as one JSON line")
    ap.add_argument("--net-probe", action="store_true",
                    help="send the band's Net connection request once seated")
    ap.add_argument("--no-answer", action="store_true",
                    help="stay silent; the run then measures what the console sends on its own")
    ap.add_argument("--session-join", action="store_true",
                    help="send the Session join request once the console's Net is acknowledged")
    ap.add_argument("--join-repeat", type=int, default=30,
                    help="V-Blank ticks between re-sends of an unanswered Session join; 0 is once")
    ap.add_argument("--app-ver", default="0006",
                    help="hex; the application communication version the Session join declares. "
                         "Six is what a reference joiner sends and what the advertisement carries")
    ap.add_argument("--token", default="06",
                    help="hex; the Session join's 32-byte identification token, zero-padded. A "
                         "reference joiner sends 0x06 and zeroes")
    ap.add_argument("--player-name", default=" ",
                    help="the name the Session join's PlayerInfo carries; a reference joiner "
                         "sends one space")
    ap.add_argument("--source-id", choices=("ldn", "raw"), default="ldn",
                    help="our own constant id in the Session join: the LDN permutation of our MAC, "
                         "which is the form the console publishes for itself, or the MAC as it is")
    ap.add_argument("--protocols", default="1:0,3:5,5:1,6:0,9:1,10:3,11:4,12:4,13:7,15:0",
                    help="id:version pairs the Session join declares; the default is the set a "
                         "reference Legends Z-A joiner declares")
    ap.add_argument("--join-flags", default="0",
                    help="hex packet flags ORed into the Session join's header: 4 is the band's "
                         "skip-network-connection-check bit, which a station the console has not "
                         "yet connected may owe")
    ap.add_argument("--game", action="store_true",
                    help="once the session is up, open the game's reliable streams and send the "
                         "identity, the selection record and, with --trade-offer, an offer")
    ap.add_argument("--game-dir", default="scratchpad",
                    help="where the reference payloads za_ref_*.bin live")
    ap.add_argument("--fresh-pid", action="store_true",
                    help="send the offer under a new PID and encryption constant, shiny state kept, "
                         "so a save that took this record before takes it again")
    ap.add_argument("--trade-offer", default=None,
                    help="a 354-byte offer message to send once the streams are open")
    ap.add_argument("--selection-delay", type=float, default=0.5,
                    help="seconds after the identity before the selection record starts; a "
                         "reference joiner waits about 0.46 s")
    ap.add_argument("--selection-period", type=float, default=0.25,
                    help="seconds between selection records; a reference joiner sends about four "
                         "a second, each under a fresh sequence")
    ap.add_argument("--selection-count", type=int, default=16,
                    help="how many selection records to send; a reference joiner sent sixteen")
    ap.add_argument("--offer-delay", type=float, default=3.0,
                    help="seconds after the streams open before the offer goes out")
    ap.add_argument("--ip-join", action="store_true",
                    help="join an emulated host over the LAN through its ldn_mitm bridge, with no "
                         "radio and no root")
    ap.add_argument("--host-ip", default="172.16.86.1")
    ap.add_argument("--our-ip", default=None, help="our own address on that LAN")
    ap.add_argument("--scan-timeout", type=float, default=2.0)
    ap.add_argument("--seat-marker", default=None,
                    help="a file to write the moment a seat forms and again when it ends, so a "
                         "watcher on the other side can act on the seat without a relay")
    ap.add_argument("--node-version", type=int, default=za.APP_VERSION,
                    help="the local communication version our NodeInfo publishes on the LAN path; "
                         "a host publishes its own application version there")
    ap.add_argument("--broadcast", action="store_true",
                    help="address our datagrams to the link-local broadcast, as a retail station does")
    ap.add_argument("--our-var", default="0xc493",
                    help="the variable id we send as our own until the console names one")
    ap.add_argument("--unicast", action="store_true",
                    help="address our datagrams to the host rather than to the broadcast")
    return ap


async def run_session(args, keys, host_ip, host_mac, our_ip, our_mac, record):
    """Hold the seat and run the band's joiner state machine against the console.

    The answers come from `pokeldn.ldn.pia_connect.ConnectionManager`, which is the same joiner the
    GBA application drives, and the framing is the one `pokeldn.frlg.link.sim` sends it with: the
    Net acknowledgement from source variable id 0 with no footer, the Session join zstd-compressed
    from our own id to destination 0, and everything after it addressed to the host with the
    two-byte recipient footer.
    """
    # Over ldn_mitm the socket is bound to our own address: a wildcard one sends from whatever
    # address the kernel picks, which on a host sharing this machine is the host's own.
    sock = make_socket(args.ifname, our_ip if args.ip_join else None)
    pia = crypto.PiaCrypto(keys.ssid, za.GAME_KEY)
    broadcast_ip = our_ip.rsplit(".", 1)[0] + ".255"
    our_var = int(args.our_var, 16)
    t0 = time.monotonic()
    counts = {}
    seen = authed = sent = 0
    first_in = None
    pktid_by_dst = {}
    state = [None]
    # The header nonce is a per-station counter, not a random number: in a reference pair both
    # stations increment theirs by one on every packet they send (the Mac pair capture,
    # `docs/za.md`). A random nonce per packet is outside the peer's window after the first.
    nonces = host_pia.PiaNonceSequence(native=True)

    def send_messages(items, *, dst_var, src_var, compress=False, footer=True,
                      establishing=False, unicast=True, pktid=None, footer_var=None, note=""):
        """One Pia packet carrying N messages. A reference joiner bundles its three protocol-11
        opening messages into one packet, and Pia tiles them in the order they are written."""
        nonlocal sent
        body = b"".join(reliable.build_message(proto, payload, msgflags)
                        for proto, payload, msgflags in items)
        proto = items[0][0]
        if compress and crypto.HAVE_ZSTD:
            body = crypto.compress(body)
            zstd = True
        else:
            zstd = False
        footer_size = 0
        if footer:
            body += ((footer_var if footer_var is not None else dst_var) & 0xFFFF).to_bytes(2, "big")
            footer_size = 2
        pad = (-len(body)) % 16
        if pktid is None:
            # One counter for everything sent to the host (dst 0 included), one for the session
            # address: the host drops a packet below the highest id it has seen. docs/za.md.
            channel = dst_var if dst_var == pia_connect.SESSION_VAR else "host"
            pktid = pktid_by_dst.get(channel, 1)
            pktid_by_dst[channel] = pktid + 1 if pktid < 0xFFFF else 1
        extra = int(args.join_flags, 16) if proto == pia_connect.PROTO_SESSION else 0
        flags = (1 if zstd else 0) | (2 if establishing else 0) | extra
        header = crypto.PiaHeader(
            dst=dst_var, src=src_var, pktid=pktid, nonce8=nonces.take(),
            flags=(pad << 4) | flags, footer=footer_size)
        out = pia.encrypt(body + b"\xff" * pad, our_ip, header)
        to = host_ip if (unicast and not args.broadcast) else broadcast_ip
        sock.sendto(out, (to, za.PIA_PORT))
        sent += 1
        record(rec="tx", data=out.hex(), to=to, proto=proto, t=time.time(),
               dt=round(time.monotonic() - t0, 4))
        print(f"[za] -> proto 0x{proto:02x} "
              + "+".join(str(len(p)) for _, p, _ in items)
              + f" bytes, dst={dst_var:#06x} src={src_var:#06x} flags={flags:#04x}"
              + (f", {note}" if note else ""))

    def send(proto, payload, **kwargs):
        return send_messages([(proto, payload, kwargs.pop("msgflags", None))], **kwargs)

    def flush(conn, tick):
        for e in conn.drain():
            # The band's own type 6 names our MAC and no sequence; this title wants our LDN
            # constant id and the update's sequence, and repeats its update forever otherwise.
            if e["proto"] == pia_connect.PROTO_SESSION and e["payload"][:1] == b"\x06":
                continue
            send(e["proto"], e["payload"], dst_var=e["dst"], src_var=e["src"],
                 compress=e["compress"], footer=e["footer"], establishing=e["establishing"],
                 unicast=e.get("unicast", True), pktid=e.get("pktid"),
                 footer_var=e.get("footer_var"))
        if state[0] is not None and conn.state != state[0]:
            state[0] = conn.state
            print(f"[za] the joiner is now in state {conn.state}")

    class Joiner(pia_connect.ConnectionManager):
        """The band's joiner, with the Session join's declared protocol set and application
        version under the run's control: what this title expects in them is unmeasured."""

        def _join(self):
            kwargs = {}
            if args.app_ver:
                kwargs["app_ver"] = bytes.fromhex(args.app_ver)
            if args.protocols:
                kwargs["protocols"] = [tuple(int(x, 0) for x in pair.split(":"))
                                       for pair in args.protocols.split(",")]
            src = (pia_connect.ldn_constant_id(self.our_mac)[:6] if args.source_id == "ldn"
                   else self.our_mac)
            kwargs["token"] = bytes.fromhex(args.token) if args.token else b""
            return pia_connect.build_session_join(
                src, self.our_var.to_bytes(2, "big"), self.our_ip, self.host_mac,
                (self.host_var or 0).to_bytes(2, "big"), args.player_name, self.random4,
                player_id=self.player_id, **kwargs)

    game = None
    if args.game:
        game = GameStreams(args, send, send_messages, record)

    conn = None
    if not args.no_answer:
        conn = Joiner(
            our_mac, host_mac, our_ip, host_ip, our_var=our_var, player_name=args.name,
            random4=os.urandom(4), log=print, join_repeat_ticks=args.join_repeat)
        state[0] = conn.state

    if args.net_probe:
        import zlib
        network_id = zlib.crc32(bytes(keys.ssid)[1:16]) & 0xFFFFFFFF
        net = pia_connect.build_net_conn_request(
            2, our_var, our_mac, network_id, [our_ip, host_ip], max_stations=4)
        send(pia_connect.PROTO_NET, net, dst_var=0, src_var=our_var, footer=False,
             establishing=True, pktid=0, note="our own connection request")

    while True:
        now = time.monotonic()
        tick = int((now - t0) * 59.727)
        if now - t0 >= args.hold:
            print(f"[za] the hold ended after {now - t0:.1f}s")
            break
        if game is not None and game.traded_at is not None \
                and now - t0 >= game.traded_at + args.after_trade:
            print(f"[za] leaving the seat {args.after_trade:.0f}s after the trade")
            break
        if args.quiet_seat and first_in is None and now - t0 >= args.quiet_seat:
            print(f"[za] nothing from the console in {args.quiet_seat:.0f}s; ending the seat")
            break
        if conn is not None:
            conn.maybe_originate_rtt(tick)
            conn.maybe_repeat_join(tick)
            flush(conn, tick)
        if game is not None and conn is not None and conn.connected:
            game.pump(conn.host_var or 0, our_var, now - t0)
        try:
            data, addr = sock.recvfrom(4096)
        except BlockingIOError:
            await trio.sleep(0.005)
            continue
        except OSError as exc:
            print(f"[za] the socket raised: {exc}")
            break
        if addr[0] == our_ip:
            continue
        seen += 1
        if first_in is None:
            first_in = now - t0
            print(f"[za] the console's first datagram at {first_in:.2f}s, {len(data)} bytes "
                  f"from {addr[0]}")
        row = dict(rec="rx", data=data.hex(), frm=addr[0], t=time.time(), dt=round(now - t0, 4))
        decoded, why = host_pia.decode_datagram(data, addr[0], pia)
        if decoded is None:
            row["why"] = why
            if crypto.is_pia(data):
                header = crypto.PiaHeader.unpack(data)
                row["header"] = dict(enc=header.enc, flags=header.flags, dst=header.dst,
                                     src=header.src, pktid=header.pktid, footer=header.footer)
                print(f"[za] datagram {seen}: Pia, but {why} "
                      f"(enc=0x{header.enc:02x} src={header.src:#06x} dst={header.dst:#06x})")
            else:
                print(f"[za] datagram {seen}: not Pia, {len(data)} bytes")
            record(**row)
            continue
        authed += 1
        header, messages = decoded
        row["header"] = dict(enc=header.enc, flags=header.flags, dst=header.dst,
                             src=header.src, pktid=header.pktid, footer=header.footer)
        row["messages"] = [dict(proto=m.proto, flags=m.flags, msgflags=m.msgflags,
                                payload=m.payload.hex()) for m in messages]
        for m in messages:
            counts[m.proto] = counts.get(m.proto, 0) + 1
        print(f"[za] datagram {seen} at {now - t0:.2f}s, src={header.src:#06x} "
              f"dst={header.dst:#06x}: " + "; ".join(describe_msg(m) for m in messages))
        record(**row)
        if conn is None:
            continue
        # The console names our variable id in the footer of a mesh-addressed packet; until it
        # does, ours is the one we invented. dst 0x0001 is the session address, never ours: taking it
        # made our RTT unattributable and the host's liveness timeout kicked us. docs/za.md.
        if header.footer == 2 and header.dst not in (0, pia_connect.SESSION_VAR, 0xFFFF):
            conn.learn_ids(header.dst, header.src)
        for m in messages:
            if m.proto == pia_connect.PROTO_SESSION and m.payload[:1] == b"\x05" and conn is not None:
                sequence = za.session_encoding.session_update_sequence(m.payload) \
                    if False else za.session_update_sequence(m.payload)
                ack = za.build_session_update_ack(pia_connect.ldn_constant_id(our_mac), sequence)
                send(pia_connect.PROTO_SESSION, ack, dst_var=conn.host_var or 0, src_var=our_var,
                     establishing=False, footer_var=conn.host_var or 0,
                     note=f"session update acknowledgement, sequence {sequence}")
            if game is not None and m.proto in (GAME_RELIABLE, GAME_BROADCAST):
                game.on_message(m.proto, m.payload, now - t0)
            conn.on_message(m.proto, m.payload, tick)
        flush(conn, tick)

    sock.close()
    if counts:
        print("[za] protocol ids the console used: "
              + ", ".join(f"0x{p:02x} {PROTOCOL_NAMES.get(p, '?')} x{n}"
                          for p, n in sorted(counts.items())))
    print(f"[za] seat: {seen} datagram(s) in, {authed} authenticated, {sent} out"
          + (f", joiner state {conn.state}" if conn is not None else ""))
    record(rec="seat_end", seen=seen, authed=authed, sent=sent,
           state=(conn.state if conn is not None else None),
           counts={str(k): v for k, v in counts.items()}, t=time.time())
    return game is not None and game.traded_at is not None


def ip_scan_once(our_ip, host_ip, timeout):
    """-> the emulated host's NetworkInfo, or None. The scan leaves from our own address: the
    bridge drops one whose source is the host's own address and answers where it came from."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as us:
        us.settimeout(timeout)
        us.bind((our_ip, 0))
        try:
            us.sendto(ldn_mitm.build(ldn_mitm.SCAN), (host_ip, ldn_mitm.PORT))
            while True:
                data, _ = us.recvfrom(4096)
                kind, info = ldn_mitm.parse(data)
                if kind == ldn_mitm.SCAN_RESP:
                    return info
        except (socket.timeout, OSError, ValueError):
            return None


def ip_associate(our_ip, host_ip, our_mac, name, timeout, version=0):
    """-> (NetworkInfo, held TCP socket). The host keeps the connection open for the session."""
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(timeout)
    tcp.bind((our_ip, 0))
    tcp.connect((host_ip, ldn_mitm.PORT))
    tcp.sendall(ldn_mitm.build(ldn_mitm.CONNECT,
                               ldn_mitm.build_node_info(our_ip, our_mac, name.encode(),
                                                        version=version)))
    kind, synced = ldn_mitm.parse(tcp.recv(8192))
    if kind != ldn_mitm.SYNC_NETWORK:
        tcp.close()
        raise RuntimeError(f"the host answered our connect with type {kind}, not SyncNetwork")
    tcp.settimeout(None)
    return synced, tcp


def mark_seat(path, state, **fields):
    """Announce a seat to anything watching the shared folder: one line, state first."""
    if not path:
        return
    try:
        with open(path, "a") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {state} "
                     + " ".join(f"{k}={v}" for k, v in fields.items()) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        print(f"[za] the seat marker could not be written: {exc}")


def main_ip(args):
    """The same session against an emulated host on the LAN: a bridge scan, a connect, then Pia on
    12345 between our two real addresses. Only the transport differs from the radio path.

    The session key comes from the NetworkInfo of THIS scan: a Legends Z-A host hosting unmatched
    rotates its session id about every four seconds, and a key derived from an older scan is one
    the host has already discarded.
    """
    our_ip = args.our_ip
    if our_ip is None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((args.host_ip, ldn_mitm.PORT))
            our_ip = probe.getsockname()[0]
    our_mac = b"\x02\x00" + socket.inet_aton(our_ip)
    want = int(args.comm_id, 16) if args.comm_id else za.COMM_ID
    print(f"[za] ip-join: host {args.host_ip}, us {our_ip}, comm_id={want:#018x}")
    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    deadline = time.time() + args.seconds
    scans = seats = 0
    try:
        while time.time() < deadline:
            scans += 1
            info = ip_scan_once(our_ip, args.host_ip, args.scan_timeout)
            if info is None:
                continue
            comm_id = int.from_bytes(bytes(info[:8]), "little")
            session_id = ldn_mitm.session_id(info)
            if comm_id != want:
                print(f"[za] scan {scans}: comm_id={comm_id:#018x} is not Legends Z-A")
                time.sleep(args.scan_timeout)
                continue
            keys = za.session_keys(session_id)
            print(f"[za] scan {scans}: the emulator is hosting. session id={session_id.hex()} "
                  f"network_id={keys.network_id:#010x}")
            if args.scan_only:
                time.sleep(args.scan_timeout)
                continue
            try:
                synced, tcp = ip_associate(our_ip, args.host_ip, our_mac, args.name,
                                           args.scan_timeout * 4, version=args.node_version)
            except (OSError, RuntimeError) as exc:
                print(f"[za] the association failed: {exc}")
                continue
            seats += 1
            host_mac = bytes(ldn_mitm.host_mac(synced))
            # The bridge's SyncNetwork carries the session the host settled on; a rotation between
            # our scan and our connect would otherwise leave us on a discarded key.
            synced_id = ldn_mitm.session_id(synced)
            if synced_id != session_id:
                print(f"[za] the session id rotated under the connect: {session_id.hex()} -> "
                      f"{synced_id.hex()}; keying on the new one")
                keys = za.session_keys(synced_id)
            print(f"[za] *** SEATED *** over IP, host mac={host_mac.hex()}")
            mark_seat(args.seat_marker, "SEATED", session=synced_id.hex(), ip=our_ip)
            record(rec="seat", ssid=synced_id.hex(), host_ip=args.host_ip,
                   host_mac=host_mac.hex(), our_ip=our_ip, our_mac=our_mac.hex(),
                   network_info=bytes(synced).hex(), t=time.time())
            try:
                if trio.run(run_session, args, keys, args.host_ip, host_mac, our_ip, our_mac,
                            record):
                    break
            except Exception as exc:
                print(f"[za] the seat ended: {type(exc).__name__}: {exc}")
            finally:
                mark_seat(args.seat_marker, "ENDED", session=synced_id.hex())
                try:
                    tcp.close()
                except OSError:
                    pass
    except KeyboardInterrupt:
        print("\n[za] interrupted")
    finally:
        if cap:
            cap.close()
    print(f"[za] {scans} scan(s), {seats} seat(s)")
    return 0


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    if args.ip_join:
        return main_ip(args)
    if os.geteuid() != 0 and not board_radio():
        ap.error("joining needs the raw radio; re-run under sudo")
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[za] no AP-capable phy")
        return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[za] prod.keys not found at {keys_path!r}")
        return 2
    want = int(args.comm_id, 16) if args.comm_id else za.COMM_ID
    channels = [int(c) for c in args.channels.split(",") if c.strip()]
    print(f"[za] phy={phy} channels={channels} dwell={args.dwell}s comm_id={want:#018x}")
    cleanup_stale()
    if args.mac and board_radio():
        from pokeldn.ldn import esp32_wlan
        esp32_wlan.set_station_mac(args.mac)
    elif args.mac:
        import subprocess
        base = os.path.join("/sys/class/ieee80211", phy, "device", "net")
        for name in os.listdir(base):
            subprocess.run(["ip", "link", "set", "dev", name, "down"], check=False)
            subprocess.run(["ip", "link", "set", "dev", name, "address", args.mac], check=False)
    keys_file = ldn.load_keys(keys_path)

    cap = open(args.capture, "w") if args.capture else None

    def record(**row):
        if cap:
            cap.write(json.dumps(row) + "\n")
            cap.flush()

    deadline = time.time() + args.seconds
    scans = seats = 0
    try:
        while time.time() < deadline:
            scans += 1

            async def find():
                return await ldn.scan(keys_file, phyname=phy, channels=channels,
                                      dwell_time=args.dwell)
            scan_start = time.monotonic()
            try:
                nets = trio.run(find)
            except Exception as exc:
                print(f"[za] the scan raised: {exc}")
                time.sleep(0.5)
                continue
            # A scan that never returns reads on the log exactly like a console that stopped
            # hosting, so every pass says what it took and what it saw.
            print(f"[za] scan {scans}: {len(nets)} network(s) in "
                  f"{time.monotonic() - scan_start:.1f}s")
            target = None
            for n in nets:
                if n.local_communication_id != want:
                    continue
                print(f"[za]   {describe(n)} ssid={n.ssid.hex()}")
                record(rec="scan", comm_id=n.local_communication_id, ssid=n.ssid.hex(),
                       channel=n.channel, participants=n.num_participants,
                       max_participants=n.max_participants,
                       app_data=bytes(n.application_data).hex(), t=time.time())
                if args.code:
                    try:
                        if za.parse_advertise_data(bytes(n.application_data))["code"] != args.code:
                            continue
                    except (ValueError, IndexError):
                        continue
                if n.num_participants < n.max_participants:
                    target = n
            if target is None or args.scan_only:
                continue
            keys = za.session_keys(target.ssid)
            print(f"[za] joining: ssid={target.ssid.hex()} network_id={keys.network_id:#010x} "
                  f"channel={target.channel}")

            param = ldn.ConnectNetworkParam()
            param.keys, param.network, param.password = keys_file, target, za.PASSPHRASE
            param.name, param.app_version = args.name.encode(), target.app_version
            param.platform = args.platform
            param.phyname, param.ifname = phy, args.ifname

            async def seat():
                with trio.move_on_after(args.connect_timeout) as scope:
                    async with ldn.connect(param) as network:
                        scope.deadline = float("inf")
                        info = network.info()
                        parts = list(getattr(info, "participants", []) or [])
                        print(f"[za] *** SEATED *** ssid={info.ssid.hex()}")
                        for i, p in enumerate(parts[:2]):
                            name = bytes(getattr(p, "name", b"") or b"").split(b"\0")[0]
                            print(f"[za]   participant {i}: ip={getattr(p, 'ip_address', '?')} "
                                  f"mac={bytes(getattr(p, 'mac_address', b'')).hex()} "
                                  f"name={name!r}")
                        host = parts[0] if parts else None
                        host_ip = str(getattr(host, "ip_address", "") or "169.254.1.1")
                        host_mac = bytes(getattr(host, "mac_address", b"") or b"")
                        ours = parts[1] if len(parts) > 1 else None
                        our_ip = str(getattr(ours, "ip_address", "")
                                     or host_ip.rsplit(".", 1)[0] + ".2")
                        our_mac = bytes(getattr(ours, "mac_address", b"") or b"")
                        record(rec="seat", ssid=info.ssid.hex(), host_ip=host_ip,
                               host_mac=host_mac.hex(), our_ip=our_ip, our_mac=our_mac.hex(),
                               t=time.time())
                        return await run_session(args, keys, host_ip, host_mac, our_ip, our_mac,
                                                 record)

            try:
                traded = trio.run(seat)
                seats += 1
                if traded:
                    break
            except Exception as exc:
                def leaves(e):
                    inner = getattr(e, "exceptions", ())
                    return [x for i in inner for x in leaves(i)] if inner else [e]
                detail = "; ".join(f"{type(e).__name__}: {e}" for e in leaves(exc))
                print(f"[za] the seat ended: {detail}")
                record(rec="seat_failed", detail=detail, t=time.time())
    except KeyboardInterrupt:
        print("\n[za] interrupted")
    finally:
        if cap:
            cap.close()
    print(f"[za] {scans} scan(s), {seats} seat(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
