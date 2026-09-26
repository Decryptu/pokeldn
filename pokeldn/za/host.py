"""The host's side of a Legends Z-A local trade, as a reference host runs it; owns no sockets.

A searching console joins a network carrying the title's advertisement. What a host owes it is read
off an emulated pair's trade (`docs/za.md`, Hosting): the Net connection status until the joiner
answers, the Session join response and two update sessions, the game's identity on both reliable
streams, the selection record once the second update is acknowledged, then the trade messages.

`HostSession` takes datagrams in and queues datagrams out; `bin/za_host.py` carries them.
"""
import os
import time
import zlib
from types import SimpleNamespace

from pokeldn import za
from pokeldn.ldn import crypto, host_pia, pia_connect, reliable, show_done
from pokeldn.za import streams

NET_REPEAT = 0.456                # a reference host re-sends its connection status this often
PROPERTY_REPEAT = 0.5
UPDATE_REPEAT = 1.0
SECOND_UPDATE_DELAY = 1.15        # a reference host's update sequence 1, after its sequence 0
RTT_PERIOD = 0.31
RETRANSMIT_MS = 500               # a reference host re-sends its unacknowledged opening at 0.5 s
SELECTION_COUNT = 2               # a reference host sends its selection record twice, 60 ms apart
SELECTION_GAP = 0.06
PREVIEW_DELAY = 2.7               # the first 0101, a preview no player chose
OFFER_DELAY = 1.5                 # our offer, after the console's own
CONFIRM_DELAY = 1.0               # our 0102, after the console's
COMMIT_DELAY = 1.5                # our 0104, after our 0102
NET_STATIONS = 4                  # the connection status and property both declare four slots
PROPERTY_BYTE = 2
HOST_TOKEN = b"\x06"              # the host station's identification token in its update
ACK_FLAGS = 0x40
RETRANSMIT_FLAGS = 0x20
BROADCAST_RECIPIENTS = 3
HOST_ENTRY = 1                    # a host acknowledges the joiner's broadcast stream in entry 1
RTT_TICKS = 19_200_000

MSG_SELECTION = "0100"
MSG_OFFER = "0101"
MSG_CONFIRM = bytes.fromhex("0102b90100")
MSG_COMMIT = bytes.fromhex("0104b90100")
MSG_STEP = "0200"
# An offer's last byte: 1 on the preview a station sends unasked, 0 on the player's pick. A pick
# sent with 1 is drawn as nothing and the partner waits on "Communicating" (docs/za.md).
OFFER_PREVIEW, OFFER_PICK = 1, 0
STEP_ANSWER = bytes.fromhex("0201")   # a host answers each 0200 step on protocol 11 with 0201


def build_rtt_request(tick, micros, host_var):
    """Type 0, the sender's 19.2 MHz tick, its microsecond clock, a zero halfword, the host's id."""
    return (b"\x00" + (tick & (2**64 - 1)).to_bytes(8, "big") + (micros & (2**64 - 1)).to_bytes(8, "big")
            + b"\x00\x00" + (host_var & 0xFFFF).to_bytes(2, "big"))


def build_rtt_response(request, micros, requester_var):
    """Type 1: the request's tick echoed, the responder's own clock, the requester's id."""
    out = bytearray(bytes(request[:21]).ljust(21, b"\x00"))
    out[0] = 1
    out[9:17] = (micros & (2**64 - 1)).to_bytes(8, "big")
    out[17:19] = (requester_var & 0xFFFF).to_bytes(2, "big")
    return bytes(out)


def session_ack_sequence(payload):
    """-> the update sequence a type-6 acknowledgement names: the u32 after the constant id."""
    return int.from_bytes(bytes(payload)[9:13], "big")


class HostSession:
    """One seated console. `receive` and `tick` queue datagrams; `drain` hands them over."""

    def __init__(self, *, ssid, our_ip, our_mac, guest_ip, code, identity, identity_tail,
                 selection, offer, host_var=None, offer_at=None, log=print, record=None,
                 clock=time.monotonic):
        self.ssid = bytes(ssid)
        self.our_ip, self.our_mac, self.guest_ip = our_ip, bytes(our_mac), guest_ip
        self.code = code
        self.identity, self.identity_tail = bytes(identity), bytes(identity_tail)
        self.selection = bytes(selection)
        self.offer = self.preview = None
        if offer:
            self.offer = bytes(offer[:-1]) + bytes([OFFER_PICK])
            self.preview = bytes(offer[:-1]) + bytes([OFFER_PREVIEW])
        # Seconds after the preview to make our pick unprompted; None waits for the console's.
        self.offer_at = offer_at
        self.host_var = host_var or int.from_bytes(os.urandom(2), "big") % 0xFFF0 + 0x0002
        self.log, self.record, self.clock = log, record, clock
        self.pia = crypto.PiaCrypto(self.ssid, za.GAME_KEY)
        self.network_id = zlib.crc32(self.ssid[1:16]) & 0xFFFFFFFF
        self.constant_id = pia_connect.ldn_constant_id(self.our_mac)
        self.network = SimpleNamespace(our_ip=our_ip, ssid=self.ssid, SCENE_ID=za.SCENE_ID,
                                       participants=[(1, guest_ip)],
                                       max_participants=NET_STATIONS)
        self.nonces = host_pia.PiaNonceSequence(native=True)
        self.pkt = {"host": 1, "mesh": 1}
        self.out = []
        self.t0 = clock()
        self.links = {p: reliable.ReliableLink(start=streams.IDLE_NEXT,
                                               rto_bootstrap_ms=RETRANSMIT_MS,
                                               rto_ceil_ms=RETRANSMIT_MS)
                      for p in (streams.PROTO_RELIABLE, streams.PROTO_BROADCAST)}
        self.net_acked = False
        self.next_net = self.t0
        self.join = None
        self.guest_var = None
        self.update_seq = None
        self.update_acked = set()
        self.next_update = None
        self.property_acked = False
        self.next_property = None
        self.next_rtt = None
        self.scheduled = []
        self.last_due = 0.0
        self.acted = set()
        self.console_offers = 0
        self.offer_sent = False
        self.confirmed = self.committed = False
        self.steps = 0
        self.console_offer = None
        self.trade_complete = False
        self.counts = {}

    # -- framing -------------------------------------------------------------------------------

    def _elapsed(self, now):
        return now - self.t0

    def _send(self, items, *, dst, establishing=False, footer=True, pktid=None, note=""):
        raw = b"".join(reliable.build_message(p, payload, mf) for p, payload, mf in items)
        # A reference host compresses exactly the packets compression shortens.
        compress = crypto.HAVE_ZSTD and len(crypto.compress(raw)) < len(raw)
        if pktid is None:
            channel = "mesh" if dst == pia_connect.SESSION_VAR else "host"
            pktid = self.pkt[channel]
            self.pkt[channel] = pktid + 1 if pktid < 0xFFFF else 1
        data = host_pia.build_messages(
            self.network, self.pia, items, dst_var=dst, src_var=self.host_var, pktid=pktid,
            compress=compress, establishing=establishing,
            footer_var=(self.guest_var if footer else None), nonce_source=self.nonces)
        self.out.append((data, self.guest_ip))
        if self.record:
            self.record(rec="tx", data=data.hex(), to=self.guest_ip, t=time.time(),
                        protos=[p for p, _, _ in items], note=note)

    def drain(self):
        out, self.out = self.out, []
        return out

    # -- the layers below the game ---------------------------------------------------------------

    def _net_status(self):
        body = pia_connect.build_net_conn_request(
            2, self.host_var, self.our_mac, self.network_id, [self.our_ip, self.guest_ip],
            max_stations=NET_STATIONS)
        self._send([(pia_connect.PROTO_NET, body, None)], dst=0, establishing=True, footer=False,
                   pktid=0, note="net 0x11")

    def _net_property(self):
        app = za.build_advertise_data(self.code, num_players=2)
        body = host_pia.build_net_property_update(self.network, app, property_byte=PROPERTY_BYTE)
        self._send([(pia_connect.PROTO_NET, body, None)], dst=0, establishing=True, footer=False,
                   pktid=0, note="net 0x50")

    def _session_update(self, seq):
        body = pia_connect.build_session_update(
            self.join, self.constant_id, self.host_var, self.our_ip, " ",
            host_token=HOST_TOKEN, update_sequence=seq)
        self._send([(pia_connect.PROTO_SESSION, body, None)], dst=pia_connect.SESSION_VAR,
                   note=f"session update {seq}")
        self.update_seq = seq

    def _micros(self, now):
        return int((now - self.t0) * 1_000_000)

    def _on_session(self, header, payload, now):
        kind = payload[0]
        if kind == pia_connect.SESSION_JOIN_REQUEST:
            join = pia_connect.parse_session_join(payload)
            if join is None:
                self.log("[za-host] a Session join that does not parse; ignored")
                return
            first = self.join is None
            self.join, self.guest_var = join, join["source_var"]
            if not first and self.update_acked:
                return
            response = pia_connect.build_session_join_response(
                join, self.constant_id, self.host_var, os.urandom(4))
            self._send([(pia_connect.PROTO_SESSION, response, None)], dst=self.guest_var,
                       note="session join response")
            self._session_update(0)
            self.next_update = now + UPDATE_REPEAT
            if first:
                self.log(f"[za-host] the console asked to join as {self.guest_var:#06x}, "
                         f"app version {join['app_ver'].hex()}, "
                         f"{len(join['protocols'])} protocols; accepted")
                self._open_streams(now)
                self._net_property()
                self.next_property = now + PROPERTY_REPEAT
                self.next_rtt = now + 0.19
        elif kind == pia_connect.SESSION_UPDATE_ACK:
            seq = session_ack_sequence(payload)
            if seq in self.update_acked:
                return
            self.update_acked.add(seq)
            self.log(f"[za-host] the console acknowledged update {seq} at "
                     f"{self._elapsed(now):.2f}s")
            if seq == 0:
                self.next_update = now + SECOND_UPDATE_DELAY
            elif seq == 1:
                self.next_update = None
                for i in range(SELECTION_COUNT):
                    self._schedule(now, SELECTION_GAP, self.selection, "selection record")
                if self.offer:
                    self._schedule(now, PREVIEW_DELAY, self.preview, "preview offer")
                    if self.offer_at is not None:
                        self.offer_sent = True
                        self._schedule(now, self.offer_at, self.offer, "our offer")
        else:
            self.log(f"[za-host] Session type {kind} ({len(payload)} bytes) at "
                     f"{self._elapsed(now):.2f}s: {payload[:16].hex()}")

    def _on_rtt(self, header, payload, now):
        if payload[:1] == b"\x00" and self.guest_var is not None:
            response = build_rtt_response(payload, self._micros(now), header.src)
            self._send([(pia_connect.PROTO_RTT, response, None)], dst=pia_connect.SESSION_VAR)

    # -- the game's streams ----------------------------------------------------------------------

    def _emit(self, proto, seq, flags_a, inner, msgflags=None):
        link = self.links[proto]
        if proto == streams.PROTO_BROADCAST:
            body = streams.frame(seq, link.send_low(), inner, flags_a, BROADCAST_RECIPIENTS)
            dst = pia_connect.SESSION_VAR
        else:
            body = reliable.build_reliable(seq, link.send_low(), inner, flagsA=flags_a)
            dst = self.guest_var
        return (proto, body, msgflags), dst

    def _queue(self, proto, inner, flags_a, now):
        seq = self.links[proto].queue(inner, flags_a, int(now * 1000))
        return self._emit(proto, seq, flags_a, inner)

    def _open_streams(self, now):
        """The identity alone on protocol 10 under INIT, and the identity and its nine-byte tail
        bundled on protocol 11, the first of them under INIT."""
        item, dst = self._queue(streams.PROTO_RELIABLE, self.identity, reliable.FLAGSA_INIT, now)
        self._send([item], dst=dst, note="identity on 10")
        bundle = []
        for inner, flags_a in ((self.identity, reliable.FLAGSA_INIT),
                               (self.identity_tail, reliable.FLAGSA_GBA)):
            item, dst = self._queue(streams.PROTO_BROADCAST,
                                    streams.build_broadcast(inner, prefix=streams.PREFIX_HOST),
                                    flags_a, now)
            bundle.append(item)
        self._send(bundle, dst=dst, note="identity on 11")

    def _schedule(self, now, delay, payload, why, proto=streams.PROTO_RELIABLE):
        """Messages go out in the order they were asked for: a delay is a gap, never a jump
        ahead of what is already queued."""
        due = max(now + delay, self.last_due + 0.05)
        self.last_due = due
        self.scheduled.append((due, proto, payload, why))

    def _ack(self, proto):
        link = self.links[proto]
        if proto == streams.PROTO_BROADCAST:
            inner = streams.build_broadcast_ack(link.recv_next, prefix=streams.PREFIX_HOST,
                                                entry=HOST_ENTRY)
        else:
            inner = link.ack_payload()
        item, dst = self._emit(proto, streams.IDLE_NEXT, reliable.FLAGSA_CTRL, inner, ACK_FLAGS)
        self._send([item], dst=dst)

    def _on_stream(self, proto, payload, now):
        link = self.links[proto]
        r = reliable.parse_reliable(payload)
        if r is None:
            return
        if r.flagsA == reliable.FLAGSA_CTRL:
            body = r.payload[4:] if proto == streams.PROTO_BROADCAST else r.payload
            ack_id, mask = reliable.parse_bulk_ack(body)
            link.on_ack(ack_id, mask, int(now * 1000))
            return
        link.note_received(r.seq)
        if proto == streams.PROTO_BROADCAST:
            inner = streams.frame_payload(payload)[4:]
        else:
            inner = r.payload
        if (proto, r.seq) not in self.acted:
            self.acted.add((proto, r.seq))
            self._on_game(proto, inner, now)
        self._ack(proto)

    def _on_game(self, proto, inner, now):
        head = inner[:2].hex()
        key = (proto, head, len(inner))
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] == 1 or head not in (MSG_SELECTION,):
            self.log(f"[za-host] console {head} on {proto}, {len(inner)} bytes, at "
                     f"{self._elapsed(now):.2f}s")
        if proto != streams.PROTO_RELIABLE:
            return
        if head == MSG_OFFER:
            self.console_offers += 1
            self.console_offer = bytes(inner)
            if self.record:
                self.record(rec="console_offer", n=self.console_offers, data=inner.hex(),
                            t=time.time())
            # A console sends a preview, marked 1, each time its cursor moves; its pick is marked 0.
            if inner[-1] == OFFER_PICK and self.offer and not self.offer_sent:
                self.offer_sent = True
                self._schedule(now, OFFER_DELAY, self.offer, "our offer")
        elif inner[:5] == MSG_CONFIRM and not self.confirmed:
            self.confirmed = True
            self._schedule(now, CONFIRM_DELAY, MSG_CONFIRM, "confirm 0102")
            self._schedule(now, COMMIT_DELAY, MSG_COMMIT, "commit 0104")
            self.committed = True
        elif inner[:5] == MSG_COMMIT and not self.committed:
            self.committed = True
            self._schedule(now, 0.03, MSG_COMMIT, "commit 0104")
        elif head == MSG_STEP:
            self.steps += 1
            answer = streams.build_broadcast(STEP_ANSWER + bytes(inner[2:]),
                                             prefix=streams.PREFIX_HOST)
            self._schedule(now, 0.05, answer, f"step answer {inner[-1]:#04x}",
                           proto=streams.PROTO_BROADCAST)
            if self.steps >= 4 and not self.trade_complete:
                self.trade_complete = True
                show_done()
                self.log("[za-host] trade_complete: the console sent its four steps")

    # -- the loop's two entry points -------------------------------------------------------------

    def receive(self, datagram, src_ip, now=None):
        now = self.clock() if now is None else now
        decoded, why = host_pia.decode_datagram(datagram, src_ip, self.pia)
        if decoded is None:
            if self.record:
                self.record(rec="rx", data=bytes(datagram).hex(), frm=src_ip, why=why,
                            t=time.time())
            return
        header, messages = decoded
        if self.record:
            self.record(rec="rx", data=bytes(datagram).hex(), frm=src_ip, t=time.time(),
                        header=dict(dst=header.dst, src=header.src, pktid=header.pktid),
                        messages=[dict(proto=m.proto, msgflags=m.msgflags,
                                       payload=m.payload.hex()) for m in messages])
        for m in messages:
            if m.proto == pia_connect.PROTO_NET:
                kind = m.payload[1] if len(m.payload) > 1 else None
                if kind == pia_connect.NET_CONN_RESPONSE and not self.net_acked:
                    self.net_acked = True
                    self.log(f"[za-host] the console answered our connection status at "
                             f"{self._elapsed(now):.2f}s")
                elif kind == pia_connect.NET_UPDATE_PROPERTY_ACK and not self.property_acked:
                    self.property_acked = True
            elif m.proto == pia_connect.PROTO_SESSION and m.payload:
                self._on_session(header, m.payload, now)
            elif m.proto == pia_connect.PROTO_RTT:
                self._on_rtt(header, m.payload, now)
            elif m.proto in self.links and self.guest_var is not None:
                self._on_stream(m.proto, m.payload, now)

    def tick(self, now=None):
        now = self.clock() if now is None else now
        if not self.net_acked and now >= self.next_net:
            self._net_status()
            self.next_net = now + NET_REPEAT
        if self.next_update is not None and now >= self.next_update:
            seq = 0 if 0 not in self.update_acked else 1
            self._session_update(seq)
            self.next_update = now + UPDATE_REPEAT
        if (self.next_property is not None and not self.property_acked
                and now >= self.next_property):
            self._net_property()
            self.next_property = now + PROPERTY_REPEAT
        if self.next_rtt is not None and now >= self.next_rtt:
            request = build_rtt_request(int((now - self.t0) * RTT_TICKS), self._micros(now),
                                        self.host_var)
            self._send([(pia_connect.PROTO_RTT, request, None)], dst=pia_connect.SESSION_VAR)
            self.next_rtt = now + RTT_PERIOD
        if self.guest_var is None:
            return self.drain()
        now_ms = int(now * 1000)
        for proto, link in self.links.items():
            items = []
            for seq, flags_a, inner in link.due_retransmits(now_ms, limit=4):
                item, dst = self._emit(proto, seq, flags_a, inner, RETRANSMIT_FLAGS)
                items.append(item)
            if items:
                self._send(items, dst=dst)
        for entry in [e for e in self.scheduled if e[0] <= now]:
            self.scheduled.remove(entry)
            _due, proto, payload, why = entry
            item, dst = self._queue(proto, payload, reliable.FLAGSA_GBA, now)
            self._send([item], dst=dst, note=why)
            self.log(f"[za-host] sent {why}, {payload[:6].hex()} ({len(payload)} bytes) at "
                     f"{self._elapsed(now):.2f}s")
        return self.drain()
