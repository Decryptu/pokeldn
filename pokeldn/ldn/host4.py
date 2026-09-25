"""The host side of a Pia version-4 local session: what a Sword owes a station that joins it.

Every message here is the one a retail Sword sends while it hosts, rebuilt from fields and checked
byte for byte against the console's own (`tests/test_host4.py`). The order a joiner is answered in:

    joiner -> host   0x14 connection request, carrying its location
    host   -> joiner 0x14 ack of it, then a connection request of our own, addressed to the ids in
                     that location
    joiner -> host   0x14 connection response (17 bytes)
    host   -> joiner 0x14 ack of it, then our 840-byte connection response
    joiner -> host   0x14 ack, and 0x18 join request
    host   -> joiner 0x14 ack, 0x18 join response, then update mesh, RTT and both window acks

The Local Protocol update session goes to the subnet broadcast every 100 ms until each seated
station acknowledges the current sequence. docs/pia.md, docs/swsh_session.md.

Nothing here knows a game. Application data on 0x7C, 0x80 and the mesh's reliable port is handed
up through `on_data`; 0x84 goes to `on_broadcast` with the message flags (0x10 is zlib); every
other message the layer does not consume goes to `on_other`.
"""

import os
import struct
import time
import zlib

from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mesh
from pokeldn.ldn import pia4, reliable4, reliable5, rtt_protocol as rtt
from pokeldn.ldn import station4
from pokeldn.ldn import station_protocol as stp
from pokeldn.ldn.pia5 import gcm_iv, ldn_nonce_crc

PIA_PORT = 12345
BROADCAST_STREAM = 0x84           # nn::pia::transport::ReliableBroadcastProtocol
SYNC_CLOCK = 0x1C                 # u64 tick in, the tick and the mesh clock in ms out
CLONE_CLOCK = 0x77                # 18 bytes in; 01, bytes 1..9 echoed, the clone clock in ms out
UPDATE_SESSION_PERIOD = 0.1       # the console's own rebroadcast rate until acked
UPDATE_MESH_PERIOD = 2.0
RTT_PERIOD = 0.4
WINDOW_ACK_PERIOD = 1.0           # the host acks both 0x80 ports once a second, data or not
RETRANSMIT_AFTER = 0.3
STATION_FLAGS = 0x01              # message flags on 0x14, 0x18, 0x58 and 0x7C
BROADCAST_FLAGS = 0x11            # 0x24 and 0x80: flags 0x01 plus the no-bundle bit

RESPONSE_SIZE = 840               # a retail Sword's accepted 0x14 connection response
OFF_RESPONSE_ACCOUNT = 0x11       # 16 bytes; the same 16 open the advertisement's player record
OFF_RESPONSE_SESSION = 0x31       # 4 bytes, unread
OFF_RESPONSE_NAME = 0x88          # 1 byte of encoding, then the Pia player name, UTF-8
OFF_RESPONSE_TAIL = 0xB1          # 11 bytes, constant across captures
RESPONSE_TAIL = bytes.fromhex("0001000101020101000000")
OFF_RESPONSE_TOKEN = 0xBC         # 52 bytes; its first 8 also sit in the advertisement


def packet_iv(network_id_le, sender_mac, nonce8, source_id=0):
    return gcm_iv(ldn_nonce_crc(network_id_le, sender_mac), source_id, nonce8)


def build_host_response(joiner_constant, joiner_variable, ack_id, account=None, session=None,
                        name="PkCamp", token=None):
    """The 840-byte accepted 0x14 connection response a retail Sword sends a joiner.

    Laid out from a retail Sword's own: `02 00 09 04 00`, the joiner's constant and variable ids,
    the host account's 16 bytes, 16 zero bytes, four unread bytes, `01 01 01 20` (0x37 is the gate
    the receiver checks under 5), the player name at 0x88, eleven constant bytes, a 52-byte token,
    zeroes, and the ack id the joiner answers with on 0x14.
    """
    out = bytearray(RESPONSE_SIZE)
    out[0:5] = bytes([stp.CONNECTION_RESPONSE, 0, station4.PLATFORM_SWITCH, 4, 0])
    struct.pack_into(">Q", out, 5, joiner_constant & 0xFFFFFFFFFFFFFFFF)
    struct.pack_into(">I", out, 0xD, joiner_variable & 0xFFFFFFFF)
    out[OFF_RESPONSE_ACCOUNT:OFF_RESPONSE_ACCOUNT + 16] = account or os.urandom(16)
    out[OFF_RESPONSE_SESSION:OFF_RESPONSE_SESSION + 4] = session or os.urandom(4)
    out[0x35:0x39] = bytes([1, 1, 1, 0x20])
    encoded = name.encode("utf-8")[:0x28]
    out[OFF_RESPONSE_NAME] = 1
    out[OFF_RESPONSE_NAME + 1:OFF_RESPONSE_NAME + 1 + len(encoded)] = encoded
    out[OFF_RESPONSE_TAIL:OFF_RESPONSE_TAIL + len(RESPONSE_TAIL)] = RESPONSE_TAIL
    out[OFF_RESPONSE_TOKEN:OFF_RESPONSE_TOKEN + 52] = token or os.urandom(52)
    struct.pack_into(">I", out, RESPONSE_SIZE - 4, ack_id & 0xFFFFFFFF)
    return bytes(out)


class Window:
    """One reliable window in one direction, on one (protocol, port)."""

    def __init__(self):
        self.next_seq = reliable4.FIRST_SEQUENCE      # ours, outgoing
        self.unacked = {}                             # seq -> [message bytes, last sent]
        self.through = None                           # theirs, incoming: contiguous through
        self.seen = set()


class Station:
    def __init__(self, ip, mac, index):
        self.ip, self.mac, self.index = ip, bytes(mac), index
        self.constant = stp.ldn_constant_id(self.mac)
        self.variable = None
        self.location = None
        self.state = "new"
        self.update_acked = 0
        self.windows = {}
        self.last_rtt = 0.0
        self.last_window_ack = 0.0
        self.last_update_mesh = 0.0
        self.seated_at = time.time()

    def window(self, protocol, port):
        return self.windows.setdefault((protocol, port), Window())

    @property
    def bitmap(self):
        return 1 << self.index


class Pia4Host:
    """Everything below the game: seat a joiner, keep the mesh, carry both reliable windows."""

    def __init__(self, network_id_le, session_key, our_ip, our_mac, send, log=print,
                 on_data=None, on_other=None, name="PkCamp", account=None, token=None,
                 session=None, capture=None, on_broadcast=None):
        self.network_id_le = bytes(network_id_le)
        self.session_key = bytes(session_key)
        self.our_ip, self.our_mac = our_ip, bytes(our_mac)
        self.constant = stp.ldn_constant_id(self.our_mac)
        self.variable = struct.unpack(">I", os.urandom(4))[0]
        self.service_variable = stp.ldn_service_variable_id(self.our_mac)
        self.local_network_id = struct.unpack(">I", os.urandom(4))[0]
        self.location = stp.station_location(our_ip, PIA_PORT, self.constant, self.variable,
                                             self.service_variable, nat_flags=0, nat_location=0,
                                             probeinit=0, private_available=1, public=False)
        self._send = send
        self.log = log
        self.on_data = on_data or (lambda st, proto, port, payload: None)
        self.on_other = on_other or (lambda st, proto, port, payload: None)
        self.on_broadcast = on_broadcast
        self.name, self.account, self.token, self.session = name, account, token, session
        self.capture = capture
        self.stations = {}            # ip -> Station
        self.sequence = 1             # the update session's
        self.last_update = 0.0
        self.mesh_counter = 0
        self.ack_counter = struct.unpack(">I", os.urandom(4))[0] & 0x7FFFFFFF
        self.rtt_seen = 0
        self.t0 = time.time()

    # -- the wire ------------------------------------------------------------------------------

    def record(self, **row):
        if self.capture is not None:
            row.setdefault("t", round(time.time() - self.t0, 4))
            self.capture(row)

    def send_message(self, dst_ip, payload, protocol, port=0, flags=STATION_FLAGS,
                     destination=0, compress=False):
        body = zlib.compress(payload) if compress else payload
        msg = pia4.build_message(body, protocol=protocol, source=self.constant, port=port,
                                 message_flags=flags | (pia4.MESSAGE_FLAG_ZLIB if compress else 0),
                                 destination=destination)
        nonce8 = os.urandom(8)
        iv = packet_iv(self.network_id_le, self.our_mac, nonce8)
        self._send(pia4.build_packet(self.session_key, iv, msg, nonce8=nonce8), dst_ip)
        self.record(rec="tx", dst=dst_ip, protocol=protocol, port=port, flags=flags,
                    destination=destination, payload=payload.hex())

    def next_ack_id(self):
        self.ack_counter = (self.ack_counter + 1) & 0xFFFFFFFF
        return self.ack_counter

    # -- seats ---------------------------------------------------------------------------------

    def seat(self, ip, mac, index):
        """The LDN layer seated a station; the Local Protocol starts listing it."""
        if ip in self.stations:
            return self.stations[ip]
        st = Station(ip, mac, index)
        self.stations[ip] = st
        self.sequence += 1
        self.log(f"[pia4] seat {index}: {ip} {st.mac.hex()} constant {st.constant:#018x}")
        return st

    def unseat(self, ip):
        if self.stations.pop(ip, None) is not None:
            self.sequence += 1
            self.log(f"[pia4] {ip} left")

    def nodes(self):
        out = [(self.our_ip, PIA_PORT, 0)]
        for st in sorted(self.stations.values(), key=lambda s: s.index):
            out.append((st.ip, PIA_PORT, st.index))
        return out

    def mesh_entries(self):
        out = [(self.location, 0)]
        for st in sorted(self.stations.values(), key=lambda s: s.index):
            if st.location is not None and st.state == "joined":
                out.append((st.location, st.index))
        return out

    # -- periodic ------------------------------------------------------------------------------

    def tick(self, now=None):
        now = time.time() if now is None else now
        broadcast = self.broadcast_ip()
        if (any(st.update_acked < self.sequence for st in self.stations.values())
                or not self.stations) and now - self.last_update >= UPDATE_SESSION_PERIOD:
            upd = lp.build_update_session(self.sequence, self.local_network_id, self.variable,
                                          self.service_variable, self.constant, self.nodes())
            self.send_message(broadcast, upd, lp.PROTOCOL, flags=0x09)
            self.last_update = now
        for st in list(self.stations.values()):
            if st.state != "joined":
                continue
            if now - st.last_rtt >= RTT_PERIOD:
                stamp = int(now * 1e9) & ((1 << 64) - 1)
                self.send_message(st.ip, bytes(8) + struct.pack(">Q", stamp), rtt.PROTOCOL,
                                  destination=st.bitmap)
                st.last_rtt = now
            if now - st.last_update_mesh >= UPDATE_MESH_PERIOD:
                self.send_message(st.ip, mesh.build_update_mesh_v4(0, self.mesh_entries(),
                                                                   self.mesh_counter),
                                  mesh.PROTOCOL, destination=st.bitmap)
                st.last_update_mesh = now
            if now - st.last_window_ack >= WINDOW_ACK_PERIOD:
                for port in (0, 1):
                    w = st.window(reliable4.BROADCAST_PROTOCOL, port)
                    self.send_window_ack(st, reliable4.BROADCAST_PROTOCOL, port, w)
                st.last_window_ack = now
            for (protocol, port), w in st.windows.items():
                for seq, entry in sorted(w.unacked.items()):
                    if now - entry[1] >= RETRANSMIT_AFTER:
                        self.send_message(st.ip, entry[0], protocol, port=port,
                                          flags=STATION_FLAGS, destination=st.bitmap)
                        entry[1] = now

    def broadcast_ip(self):
        parts = self.our_ip.split(".")
        if parts[0] == "127":
            peers = [st.ip for st in self.stations.values()]
            return peers[0] if peers else self.our_ip
        return ".".join(parts[:3] + ["255"])

    # -- the reliable windows ------------------------------------------------------------------

    def send_window_ack(self, st, protocol, port, w):
        ack_id = (w.through + 1) if w.through is not None else reliable4.FIRST_SEQUENCE
        ours = st.window(protocol, port)
        lowest = min(ours.unacked) if ours.unacked else ours.next_seq
        dests = (st.constant,) if protocol == reliable4.BROADCAST_PROTOCOL else ()
        body = reliable4.build_ack_message(ack_id, lowest_pending=lowest, destinations=dests)
        flags = BROADCAST_FLAGS if protocol == reliable4.BROADCAST_PROTOCOL else STATION_FLAGS
        self.send_message(st.ip, body, protocol, port=port, flags=flags & ~0x10,
                          destination=st.bitmap)

    def send_broadcast(self, ip, port, message, compressed=False):
        """One 0x84 message; `compressed` sets Pia's zlib flag over a body already deflated."""
        st = self.stations[ip]
        self.send_message(ip, message, BROADCAST_STREAM, port=port,
                          flags=STATION_FLAGS | (pia4.MESSAGE_FLAG_ZLIB if compressed else 0),
                          destination=st.bitmap)

    def send_data(self, ip, protocol, port, payload):
        """Queue one application message on 0x7C or 0x80 and put it on the wire now."""
        st = self.stations[ip]
        w = st.window(protocol, port)
        seq = w.next_seq
        w.next_seq += 1
        lowest = min(w.unacked) if w.unacked else seq
        dests = (st.constant,) if protocol == reliable4.BROADCAST_PROTOCOL else ()
        msg = reliable4.build_data_message(payload, sequence_id=seq, lowest_pending=lowest,
                                           destinations=dests)
        w.unacked[seq] = [msg, time.time()]
        self.send_message(ip, msg, protocol, port=port, destination=st.bitmap)
        self.record(rec="tx_data", dst=ip, protocol=protocol, port=port, seq=seq,
                    payload=bytes(payload).hex())
        return seq

    def _reliable_in(self, st, protocol, port, body, now):
        try:
            got = reliable4.parse_message(body)
        except ValueError:
            return
        if got["is_ack"]:
            if len(got["payload"]) == reliable4.ACK_PAYLOAD_SIZE:
                w = st.window(protocol, port)
                entries = reliable4.parse_ack_payload(got["payload"])
                ids = [e["ack_id"] for e in entries[:8] if e["ack_id"]]
                if ids:
                    upto = max(ids)
                    for seq in [s for s in w.unacked if s < upto]:
                        del w.unacked[seq]
            return
        w = st.window(protocol, port)
        if w.through is None:
            w.through = got["sequence_id"] - 1
        fresh = got["sequence_id"] > w.through and got["sequence_id"] not in w.seen
        w.seen.add(got["sequence_id"])
        w.through = reliable5.contiguous_through(w.seen, w.through)
        self.send_window_ack(st, protocol, port, w)
        if fresh:
            self.record(rec="rx_data", src=st.ip, protocol=protocol, port=port,
                        seq=got["sequence_id"], payload=got["payload"].hex())
            self.on_data(st, protocol, port, got["payload"])

    # -- receive -------------------------------------------------------------------------------

    def on_packet(self, data, src_ip, now=None):
        now = time.time() if now is None else now
        st = self.stations.get(src_ip)
        if st is None or not pia4.is_pia4(data):
            return
        h = pia4.PiaHeader4.parse(data)
        iv = packet_iv(self.network_id_le, st.mac, h.nonce8, source_id=h.station)
        plain = pia4.decrypt_payload(self.session_key, iv, pia4.ciphertext(data), h.tag)
        if plain is None:
            self.record(rec="rx_unauthenticated", src=src_ip, head=data[:16].hex())
            return
        for m in pia4.parse_packet(plain):
            self.record(rec="rx", src=src_ip, protocol=m["protocol"], port=m["port"],
                        flags=m["flags"], destination=m["destination"],
                        payload=m["payload"].hex())
            self._dispatch(st, m, now)

    def _dispatch(self, st, m, now):
        protocol, port, body = m["protocol"], m["port"], bytes(m["payload"])
        if protocol == lp.PROTOCOL:
            try:
                kind, _ = lp.parse_header(body)
                if kind == lp.UPDATE_SESSION_ACK:
                    st.update_acked = max(st.update_acked, lp.parse_ack(body))
            except ValueError:
                pass
        elif protocol == stp.PROTOCOL:
            self._station(st, body)
        elif protocol == mesh.PROTOCOL and port == mesh.PORT_UNRELIABLE and body[:1] == bytes(
                [mesh.JOIN_REQUEST]):
            self._join(st, body)
        elif protocol == SYNC_CLOCK and len(body) == 16:
            # A joining Shield asks every two seconds and holds its game until it is answered.
            ms = int((now - self.t0) * 1000)
            self.send_message(st.ip, body[:8] + struct.pack(">Q", ms), SYNC_CLOCK,
                              destination=st.bitmap)
        elif protocol == CLONE_CLOCK and len(body) >= 18 and body[0] == 0:
            ms = int((now - st.seated_at) * 1000)
            self.send_message(st.ip, b"\x01" + body[1:10] + struct.pack(">Q", ms), CLONE_CLOCK,
                              destination=st.bitmap)
        elif protocol == rtt.PROTOCOL:
            if len(body) == rtt.SIZE_V4 and body[0] == rtt.REQUEST:
                self.send_message(st.ip, rtt.response_for_v4(body), rtt.PROTOCOL,
                                  destination=st.bitmap)
        elif protocol in (reliable4.PROTOCOL, reliable4.BROADCAST_PROTOCOL) or (
                protocol == mesh.PROTOCOL and port == mesh.PORT_RELIABLE):
            self._reliable_in(st, protocol, port, body, now)
        elif protocol == BROADCAST_STREAM and self.on_broadcast is not None:
            self.on_broadcast(st, port, body, m["flags"])
        else:
            self.on_other(st, protocol, port, body)

    def _station(self, st, body):
        kind = body[0] if body else None
        if kind == stp.CONNECTION_REQUEST:
            # A hosting Shield acks the joiner's request before it sends its own; unacked, the
            # joiner repeats the request and never answers ours.
            self.send_message(st.ip, station4.build_ack(station4.ack_id_of(body)), stp.PROTOCOL)
            got = station4.parse_incoming_request(body)
            if got["constant_id"] != self.constant:
                self.log(f"[pia4] {st.ip}: a request for {got['constant_id']:#x}, not us")
                return
            loc = got["station"]
            st.variable = loc["variable_id"]
            st.location = got["location"][:loc["size"]]
            st.state = "requested"
            ack_id = self.next_ack_id()
            # [0x10] of ours echoes [1] of theirs, which a joining Shield draws per request and
            # checks; [1] of ours is our own draw (emulated Shield pair, docs/swsh_session.md).
            req = station4.build_connection_request(st.constant, st.variable, self.location,
                                                    nat_flags=os.urandom(1)[0],
                                                    nat_location=body[1])
            self.send_message(st.ip, req + struct.pack(">I", ack_id), stp.PROTOCOL)
            self.log(f"[pia4] {st.ip}: connection request, variable {st.variable:#010x}; "
                     f"sent ours")
        elif kind == stp.CONNECTION_RESPONSE:
            self.send_message(st.ip, station4.build_ack(station4.ack_id_of(body)), stp.PROTOCOL)
            if st.variable is None:
                return
            resp = build_host_response(st.constant, st.variable, self.next_ack_id(),
                                       account=self.account, session=self.session,
                                       name=self.name, token=self.token)
            self.send_message(st.ip, resp, stp.PROTOCOL)
            st.state = "responded"
            self.log(f"[pia4] {st.ip}: connection response result {body[1]}; sent ours")
        elif kind == station4.ACK:
            self.record(rec="rx_station_ack", src=st.ip, ack_id=station4.ack_id_of(body))

    def _join(self, st, body):
        self.send_message(st.ip, station4.build_ack(mesh.read_ack_id(body)), stp.PROTOCOL)
        if st.location is None:
            self.log(f"[pia4] {st.ip}: join request before any location; refused in silence")
            return
        first = st.state != "joined"
        st.state = "joined"
        resp = mesh.build_join_response_v4(0, st.index, self.mesh_entries(), self.next_ack_id(),
                                           update_counter=self.mesh_counter)
        self.send_message(st.ip, resp, mesh.PROTOCOL)
        if first:
            self.mesh_counter += 1
            st.last_update_mesh = 0.0
            self.log(f"[pia4] {st.ip}: joined the mesh as station {st.index}")
