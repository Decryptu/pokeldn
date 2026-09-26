"""The host side of a BDSP Union Room: what a retail console sends when it hosts, built from fields.

A console entering the Union Room joins a room it finds before it opens its own
(`IlcaNetSessionSetting.matchingMode = Random`), so a network advertising the room draws it in.
Every builder here reproduces a retail host's own message from its parsed fields; the layouts are
on `docs/bdsp_session.md`. `HostSession` owns no socket: it takes datagrams and returns datagrams.
"""
import struct
import zlib
from dataclasses import dataclass, field

from pokeldn.bdsp import room
from pokeldn.bdsp.session import PIA_PORT, session_keys
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn.pia5 import password_crc
from pokeldn.ldn import reliable5 as rl
from pokeldn.ldn import rtt_protocol as rtt
from pokeldn.ldn import station_protocol as stp
from pokeldn.ldn import sync_clock
from pokeldn.ldn.pia5 import (PiaHeader5, build_message, ciphertext, decrypt_payload,
                              encrypt_payload, gcm_iv, is_pia5, ldn_nonce_crc, pad_payload,
                              parse_messages)
from pokeldn.ldn import show_done

SCENE_UNION_ROOM = 0x1100
SCENE_UNION_ROOM_PASSWORD = 0x1400    # the room entered "avec un mot de passe"
APP_VERSION = 199                 # 1.3.0's local communication version
MAX_PARTICIPANTS = 8
SYSTEM_COMM_VERSION = 8
ADVERTISE_HEADER_SIZE = 16

# The nine protocols a retail host's connection response lists, in its order, with its versions.
PROTOCOLS = ((0x14, 2), (0x18, 3), (0x1C, 0), (0x24, 0), (0x58, 3), (0x68, 1), (0x7C, 3),
             (0x94, 1), (0xA4, 0))
UNRELIABLE_PROTOCOL = 0x68
CONNECTION_RESPONSE_SIZE = stp.MAX_SIZE       # a retail acceptance is always 949 bytes
PLAYER_INFO_SIZE = 0xC3

# A retail host's framing, per message kind: (packet dst_var, message flags, destination).
# The station and join messages go to variable 0 and destination 0; RTT, the mesh update and the
# unreliable game state to variable 1 and every station; reliable data to the joiner's variable.
ALL_STATIONS = 0xFFFFFFFF
DST_VAR_ALL = 1

HOST_INDEX = 0
JOINER_INDEX = 1

UPDATE_SESSION_PERIOD = 0.1
STATION_RETRY = 0.5
UPDATE_MESH_PERIOD = 1.0
RTT_PERIOD = 0.4
RELIABLE_RETRY = 0.2
STATE_PERIOD = 1.0


def build_advertise_data(network_id, session_param, application_data=b"\0", password=""):
    """The 17 bytes a retail room advertises: Pia's 16-byte LDN header, then one byte of the game's.

        +0x00  network id, little-endian     +0x08  system communication version 8
        +0x04  password CRC32, 0 = none      +0x09  header size 16
        +0x0c  session parameter, little-endian; it seeds the session key
    """
    return (struct.pack("<I", network_id & 0xFFFFFFFF) + password_crc(password)
            + bytes([SYSTEM_COMM_VERSION, ADVERTISE_HEADER_SIZE, 0, 0])
            + struct.pack("<I", session_param & 0xFFFFFFFF) + bytes(application_data))


@dataclass
class Advertisement:
    network_id: int
    session_param: int
    app_version: int = APP_VERSION
    password: str = ""

    @property
    def application_data(self):
        return build_advertise_data(self.network_id, self.session_param, password=self.password)

    @property
    def keys(self):
        return session_keys(self)


def host_location(ip, constant_id, variable_id, service_variable_id):
    """A retail host's own station location: no public address, NAT fields zero, 36 bytes."""
    return stp.station_location(ip, PIA_PORT, constant_id, variable_id, service_variable_id,
                                nat_flags=0, nat_location=0, public=False)


def player_info(name, language=3):
    """One PlayerInfo as a retail host fills it: the name in UTF-8, no account, the language."""
    out = (bytes([1]) + name.encode("utf-8")[:80].ljust(80, b"\0")
           + bytes([0]) + bytes(40) + bytes([language & 0xFF]) + bytes(64) + bytes(8))
    assert len(out) == PLAYER_INFO_SIZE
    return out


def build_connection_response(target_constant_id, target_variable_id, location, network_id,
                              names, ack_id, language=3):
    """An accepted connection response: the request's layout with type 2, zero-filled to 949."""
    body = stp.build_connection_request(
        target_constant_id, target_variable_id, PROTOCOLS, location, network_id=network_id,
        players=len(names), participants=len(names),
        player_infos=[player_info(n, language) for n in names], ack_id=0,
        message_type=stp.CONNECTION_RESPONSE)[:-4]
    return body.ljust(CONNECTION_RESPONSE_SIZE - 4, b"\0") + struct.pack(">I", ack_id)


def parse_connection_request(data):
    """-> dict, the joiner's side of the handshake. Same layout as the response."""
    if not data or data[0] != stp.CONNECTION_REQUEST:
        raise ValueError(f"not a connection request: {data[:4].hex()}")
    return stp.parse_connection_response(bytes([stp.CONNECTION_RESPONSE]) + data[1:])


def station_info(location, station_index, join_order):
    """One 68-byte mesh table entry: the location in 64 bytes, the index, the join order, a pad."""
    return (bytes(location).ljust(mp.LOCATION_FIELD, b"\0") + bytes([station_index & 0xFF])
            + struct.pack(">H", join_order & 0xFFFF) + b"\0")


def build_join_response(entries, joiner_index, ack_id, update_counter=0,
                        max_active=MAX_PARTICIPANTS, max_total=MAX_PARTICIPANTS):
    """`entries` is [(location, station index, join order)], host first."""
    head = bytes([mp.JOIN_RESPONSE, len(entries), HOST_INDEX, joiner_index, 1, 0, len(entries), 0,
                  max_active, 0, max_total, 0]) + struct.pack(">I", update_counter)
    return (head + b"".join(station_info(*e) for e in entries)
            + struct.pack(">I", ack_id & 0xFFFFFFFF))


def build_update_mesh(entries, update_counter):
    """The host's once-a-second statement of the mesh, always the full 556 bytes."""
    head = (bytes([mp.UPDATE_MESH, len(entries), HOST_INDEX, 0]) + struct.pack(">I", update_counter)
            + bytes([1, 0, len(entries), 0]))
    return (head + b"".join(station_info(*e) for e in entries)).ljust(mp.UPDATE_MESH_SIZE, b"\0")


def wrap(keys, our_mac, src_var, dst_var, nonce8, messages):
    """A Pia 5 packet from [(payload, protocol, port, message flags, destination)]."""
    body = b"".join(build_message(p, protocol=proto, port=port, message_flags=flags,
                                  destination=dest) for p, proto, port, flags, dest in messages)
    iv = gcm_iv(ldn_nonce_crc(keys.network_id_le, our_mac), src_var, nonce8)
    ct, tag = encrypt_payload(keys.session_key, iv, pad_payload(body))
    return PiaHeader5(dst_var=dst_var, src_var=src_var, nonce8=nonce8, tag=tag[:8]).pack() + ct


def unwrap(keys, peer_mac, data):
    """-> (header, messages) or (header, None) when the tag does not verify."""
    h = PiaHeader5.parse(data)
    iv = gcm_iv(ldn_nonce_crc(keys.network_id_le, peer_mac), h.src_var, h.nonce8)
    pt = decrypt_payload(keys.session_key, iv, ciphertext(data, h.footer_size), h.tag)
    return h, (parse_messages(pt) if pt is not None else None)


@dataclass
class Joiner:
    """One console in our room, from its LDN seat to its game messages."""
    ip: str
    mac: bytes
    ranking: int = 1
    variable_id: int = None
    constant_id: int = None
    location: bytes = None
    names: list = field(default_factory=list)
    session_acked: bool = False
    connected: bool = False
    response: bytes = None
    response_ack: int = None
    next_response: float = 0.0
    joined: bool = False
    join_response: bytes = None
    join_ack: int = None
    next_join_response: float = 0.0
    join_acked: bool = False
    # reliable, their direction
    rx_seqs: set = field(default_factory=set)
    rx_base: int = None
    rx_fragments: dict = field(default_factory=dict)
    # reliable, ours
    tx_seq: int = 1
    tx_pending: dict = field(default_factory=dict)
    their_ack: int = 0


class HostSession:
    """A BDSP room hosted for one console. `receive` and `tick` return [(packet, ip)].

    `on_game(joiner, message, now)` is called with every game message the console sends and
    returns game messages to send back reliably.
    """

    def __init__(self, keys, adv, our_ip, our_mac, variable_id, name="PkCamp", language=3,
                 join=None, on_game=None, on_tick=None, record=None, nonce_start=0):
        self.keys, self.adv = keys, adv
        self.our_ip, self.our_mac = our_ip, bytes(our_mac)
        self.broadcast = our_ip.rsplit(".", 1)[0] + ".255"
        self.variable_id = variable_id & 0xFFFFFFFF
        self.constant_id = stp.ldn_constant_id(self.our_mac)
        self.service_id = stp.ldn_service_variable_id(self.our_mac)
        self.location = host_location(our_ip, self.constant_id, self.variable_id, self.service_id)
        self.name, self.language = name, language
        self.join = join if join is not None else room.build_join(-10.57, 0.0, 6.29, rot_y=243)
        self.on_game = on_game
        self.on_tick = on_tick
        self.record = record or (lambda **kw: None)
        self.nonce = nonce_start
        self.local_network_id = zlib.crc32(struct.pack("<II", adv.network_id, adv.session_param))
        self.session_seq = 1
        self.session_acked_seq = 0
        self.next_session = 0.0
        self.mesh_counter = 0
        self.next_mesh = 0.0
        self.next_rtt = 0.0
        self.next_state = 0.0
        self.joiner = None
        self.out = []
        self.counters = {"rx": 0, "rx_bad": 0, "tx": 0, "game_rx": 0, "game_tx": 0,
                         "rtt_answers": 0, "clock_answers": 0, "state_requests": 0}
        # the mesh clock a host hands out, in ms; any monotonic value
        self.clock_origin_ms = 1_000_000

    # -- sending ---------------------------------------------------------------------------
    def _nonce8(self):
        self.nonce = (self.nonce + 1) & ((1 << 64) - 1)
        return self.nonce.to_bytes(8, "big")

    def _send(self, messages, dst_var, ip):
        pkt = wrap(self.keys, self.our_mac, self.variable_id, dst_var, self._nonce8(), messages)
        self.out.append((pkt, ip))
        self.counters["tx"] += 1
        return pkt

    def _drain(self):
        out, self.out = self.out, []
        return out

    # -- the LDN seat ----------------------------------------------------------------------
    def seat(self, ip, mac, now):
        """A console associated, or re-associated: its handshake starts over from the update
        session, which goes out until it is acknowledged."""
        self.joiner = Joiner(ip=ip, mac=bytes(mac))
        self.session_seq += 1
        self.next_session = now
        self.record(rec="seat", t=now, ip=ip, mac=bytes(mac).hex())
        return self.tick(now)

    def leave(self, now):
        """The console dropped its LDN seat; the next association starts a fresh handshake."""
        if self.joiner is not None:
            self.record(rec="left", t=now, ip=self.joiner.ip)
        self.joiner = None
        self.session_seq += 1

    def update_session(self):
        nodes = [(self.our_ip, PIA_PORT, 0)]
        if self.joiner is not None:
            nodes.append((self.joiner.ip, PIA_PORT, self.joiner.ranking))
        return lp.build_update_session(self.session_seq, self.local_network_id, self.variable_id,
                                       self.service_id, self.constant_id, nodes)

    def mesh_entries(self):
        entries = [(self.location, HOST_INDEX, 0)]
        j = self.joiner
        if j is not None and j.location is not None:
            entries.append((j.location, JOINER_INDEX, 1))
        return entries

    # -- receiving -------------------------------------------------------------------------
    def receive(self, data, src_ip, now):
        j = self.joiner
        if src_ip == self.our_ip or not is_pia5(data) or j is None or src_ip != j.ip:
            return self._drain()
        h, msgs = unwrap(self.keys, j.mac, data)
        if msgs is None:
            self.counters["rx_bad"] += 1
            self.record(rec="rx_bad", t=now, src=src_ip, data=data[:48].hex())
            return self._drain()
        self.counters["rx"] += 1
        self.record(rec="rx", t=now, src=src_ip, dst_var=h.dst_var, src_var=h.src_var,
                    msgs=[{"proto": m.protocol, "port": m.port, "flags": m.message_flags,
                           "dest": m.destination, "payload": m.payload.hex()} for m in msgs])
        for m in msgs:
            handler = {lp.PROTOCOL: self._local, stp.PROTOCOL: self._station,
                       mp.PROTOCOL: self._mesh, rtt.PROTOCOL: self._rtt,
                       sync_clock.PROTOCOL: self._sync_clock,
                       rl.PROTOCOL: self._reliable,
                       UNRELIABLE_PROTOCOL: self._unreliable}.get(m.protocol)
            if handler is not None:
                handler(j, m, now)
        return self._drain()

    def _local(self, j, m, now):
        if len(m.payload) > 1 and m.payload[1] == lp.UPDATE_SESSION_ACK:
            seq = lp.parse_ack(m.payload)
            if seq == self.session_seq:
                j.session_acked = True
                self.session_acked_seq = seq
            self.record(rec="session_ack", t=now, seq=seq)

    def _station(self, j, m, now):
        kind = m.payload[0] if m.payload else None
        if kind == stp.CONNECTION_REQUEST:
            req = parse_connection_request(m.payload)
            if (req["target_constant_id"] != self.constant_id
                    or req["target_variable_id"] != self.variable_id):
                self.record(rec="request_not_ours", t=now, request=m.payload.hex())
                return
            loc = req["location"]
            j.variable_id, j.constant_id = loc["variable_id"], loc["constant_id"]
            # the joiner's own location bytes, as it sent them, go into the mesh table
            off = 16 + 2 * len(req["protocols"])
            size = struct.unpack_from(">H", m.payload, off)[0]
            j.location = m.payload[off + 2:off + 2 + size]
            j.names = req["player_names"]
            if j.response is None:
                j.response_ack = (zlib.crc32(j.location) | 1) & 0xFFFFFFFF
                j.response = build_connection_response(
                    j.constant_id, j.variable_id, self.location, self.adv.network_id,
                    [self.name], j.response_ack, self.language)
            j.connected = True
            self.record(rec="connection_request", t=now, joiner_var=j.variable_id,
                        names=j.names, protocols=req["protocols"], ack_id=req["ack_id"])
            self._send([(j.response, stp.PROTOCOL, 0, 0x01, 0)], 0, self.broadcast)
            j.next_response = now + STATION_RETRY
        elif kind == stp.ACK:
            ack = stp.parse_ack(m.payload)
            if ack == j.response_ack:
                j.response_ack = None
                self.record(rec="connection_acked", t=now)
            elif ack == j.join_ack:
                j.join_ack = None
                j.join_acked = True
                self.record(rec="join_acked", t=now)
                self._start_game(j, now)

    def _mesh(self, j, m, now):
        kind = m.payload[0] if m.payload else None
        if kind == mp.JOIN_REQUEST:
            ack = mp.read_ack_id(m.payload)
            msgs = [(stp.build_ack(ack), stp.PROTOCOL, 0, 0x01, 0)]
            if j.join_response is None and j.location is not None:
                j.join_ack = (ack + 0x9E3779B1) & 0xFFFFFFFF or 1
                j.join_response = build_join_response(self.mesh_entries(), JOINER_INDEX,
                                                       j.join_ack, self.mesh_counter)
                self.mesh_counter += 1
            if j.join_response is not None and not j.join_acked:
                msgs.append((j.join_response, mp.PROTOCOL, 0, 0x01, 0))
                j.next_join_response = now + STATION_RETRY
            j.joined = True
            self.record(rec="join_request", t=now, ack_id=ack)
            self._send(msgs, 0, self.broadcast)
        else:
            self.record(rec="mesh_rx", t=now, kind=kind, payload=m.payload.hex())

    def _rtt(self, j, m, now):
        reply = rtt.response_for(m.payload)
        if reply is not None:
            self._send([(reply, rtt.PROTOCOL, rtt.PORT, rtt.MESSAGE_FLAGS, ALL_STATIONS)],
                       DST_VAR_ALL, j.ip)
            self.counters["rtt_answers"] += 1

    def _sync_clock(self, j, m, now):
        """A joiner asks the host for the mesh clock about once a second and leaves the mesh
        about ten seconds after asking with no answer. The reply is its tick and the clock in ms."""
        msg = sync_clock.parse_message(m.payload)
        if msg is None or msg[1]:
            return
        clock_ms = self.clock_origin_ms + int(now * 1000)
        self._send([(struct.pack(">QQ", msg[0], clock_ms), sync_clock.PROTOCOL, m.port, 0x01,
                     1 << JOINER_INDEX)], j.variable_id or 0, j.ip)
        self.counters["clock_answers"] += 1

    def _unreliable(self, j, m, now):
        g = room.parse(m.payload) if len(m.payload) >= room.HEADER_SIZE else None
        if g:
            self._game(j, g, m.payload, now, via="unreliable")

    def _reliable(self, j, m, now):
        d = rl.parse(m.payload)
        if d["is_ack"]:
            if len(d["payload"]) >= 2:
                body = rl.parse_ack_payload(d["payload"])
                for e in body["entries"]:
                    j.their_ack = max(j.their_ack, e["ack_id"])
                for seq in [s for s in j.tx_pending if s < j.their_ack]:
                    del j.tx_pending[seq]
            return
        seq = d["sequence_id"]
        if j.rx_base is None:
            j.rx_base = seq - 1
        fresh = seq not in j.rx_seqs and seq > j.rx_base
        j.rx_seqs.add(seq)
        through = rl.contiguous_through(j.rx_seqs, j.rx_base)
        # the header's lowest-pending and the entry's second halfword are OUR window's lowest
        # unacknowledged id: the console skips its receive window up to it, so a value past our
        # next send makes it drop what we send next as already seen
        ours = min([j.tx_seq, *j.tx_pending])
        self._send([(rl.build_ack_message(through + 1, stream_id=d["stream_id"], field_0x50=ours,
                                          lowest_pending=ours),
                     rl.PROTOCOL, rl.PORT, rl.MESSAGE_FLAGS, 1 << JOINER_INDEX)],
                   j.variable_id or 0, j.ip)
        if not fresh:
            return
        frag = j.rx_fragments.setdefault(d["stream_id"], {})
        if d["flags"] & rl.FLAG_MESSAGE_START:
            frag.clear()
        frag[seq] = d["payload"]
        if not d["flags"] & rl.FLAG_MESSAGE_END:
            return
        payload = b"".join(frag[k] for k in sorted(frag))
        frag.clear()
        if d["flags"] & rl.FLAG_ZLIB:
            payload = zlib.decompress(payload)
        g = room.parse(payload) if len(payload) >= room.HEADER_SIZE else None
        if g:
            self._game(j, g, payload, now, via="reliable")

    # -- the game --------------------------------------------------------------------------
    def _start_game(self, j, now):
        """In the mesh: say who we are, the way a retail host's first reliable message does."""
        self.send_game(self.join, now)
        self.next_mesh = self.next_rtt = self.next_state = now

    def _game(self, j, g, payload, now, via):
        self.counters["game_rx"] += 1
        self.record(rec="game_message", t=now, via=via, data_id=g["data_id"], name=g["name"],
                    fields=g.get("fields"), payload=payload.hex())
        if g["data_id"] == room.REQUEST and g.get("fields") \
                and g["fields"]["RequestDataID"] == room.STATE:
            self.counters["state_requests"] += 1
        replies = []
        if self.on_game is not None:
            replies = self.on_game(j, g, payload, now) or []
        else:
            a = room.answer(g)
            if a is not None:
                replies = [a]
        for r in replies:
            if via == "unreliable" and g["data_id"] == room.REQUEST:
                # the console answers a request on the stream it came in on
                self._send([(r, UNRELIABLE_PROTOCOL, 0, 0x01, ALL_STATIONS)], DST_VAR_ALL, j.ip)
            else:
                self.send_game(r, now)

    def send_game(self, message, now):
        """One game message on the reliable protocol, retransmitted until acknowledged."""
        j = self.joiner
        if j is None or j.variable_id is None:
            return
        seq = j.tx_seq
        j.tx_seq += 1
        flags = rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START | rl.FLAG_MESSAGE_END
        if seq == 1:
            flags |= rl.FLAG_IS_INITIALIZED
        msg = rl.build_header(flags, seq, len(message), lowest_pending=min([seq, *j.tx_pending])
                              ) + bytes(message)
        j.tx_pending[seq] = [msg, now + RELIABLE_RETRY]
        self.counters["game_tx"] += 1
        self.record(rec="game_tx", t=now, seq=seq, payload=bytes(message).hex())
        self._send([(msg, rl.PROTOCOL, rl.PORT, rl.MESSAGE_FLAGS, 1 << JOINER_INDEX)],
                   j.variable_id, j.ip)

    # -- timers ----------------------------------------------------------------------------
    def tick(self, now):
        j = self.joiner
        if j is None:
            return self._drain()
        if not j.session_acked and now >= self.next_session:
            self._send([(self.update_session(), lp.PROTOCOL, 0, lp.MESSAGE_FLAGS, lp.BROADCAST)],
                       0, self.broadcast)
            self.next_session = now + UPDATE_SESSION_PERIOD
        if j.response_ack is not None and j.response is not None and now >= j.next_response:
            self._send([(j.response, stp.PROTOCOL, 0, 0x01, 0)], 0, self.broadcast)
            j.next_response = now + STATION_RETRY
        if j.join_ack is not None and j.join_response is not None and now >= j.next_join_response:
            self._send([(j.join_response, mp.PROTOCOL, 0, 0x01, 0)], 0, self.broadcast)
            j.next_join_response = now + STATION_RETRY
        if j.join_acked:
            if now >= self.next_mesh:
                self._send([(build_update_mesh(self.mesh_entries(), self.mesh_counter),
                             mp.PROTOCOL, 0, 0x01, ALL_STATIONS)], DST_VAR_ALL, j.ip)
                self.next_mesh = now + UPDATE_MESH_PERIOD
            if now >= self.next_rtt:
                stamp = int(now * 1000) & 0xFFFFFFFFFFFFFFFF
                self._send([(rtt.build(rtt.REQUEST, stamp), rtt.PROTOCOL, rtt.PORT,
                             rtt.MESSAGE_FLAGS, ALL_STATIONS)], DST_VAR_ALL, j.ip)
                self.next_rtt = now + RTT_PERIOD
            if now >= self.next_state:
                self._send([(room.STATE_NONE_MESSAGE, UNRELIABLE_PROTOCOL, 0, 0x01, ALL_STATIONS)],
                           DST_VAR_ALL, j.ip)
                self.next_state = now + STATE_PERIOD
            if self.on_tick is not None:
                for message in self.on_tick(j, now) or []:
                    self.send_game(message, now)
            for seq, entry in sorted(j.tx_pending.items()):
                msg, due = entry
                if now >= due:
                    self._send([(msg, rl.PROTOCOL, rl.PORT, rl.MESSAGE_FLAGS, 1 << JOINER_INDEX)],
                               j.variable_id, j.ip)
                    entry[1] = now + RELIABLE_RETRY
        return self._drain()


class TradePartner:
    """The game side of a room member who trades: the approach, the trade messages, and the
    security phase, as a retail partner answers them (`docs/bdsp_trade.md`).

    The player raises the trade emote (`NetCharacterStateData{4, 1}`); `approach_delay` seconds
    later this walks up (`NetDataTalkReserveData`), and on an accepting result opens the greeting
    (`NetDataTalkData{GREETING}`). The console then leads the trade and each message is answered.
    `complete` gates the answer to the ready-ok, after which the console writes its save.
    """

    def __init__(self, offer, trainer_name="PkCamp", trainer_id=41234, secret_id=23117,
                 complete=False, approach_delay=2.0, security_repeat=1.0, state=room.STATE_NONE,
                 recruiting=0, save_theirs=None, record=None):
        self.offer = offer
        self.trainer = room.build_trade_traner(trainer_name, trainer_id, secret_id)
        self.complete = complete
        self.approach_delay, self.security_repeat = approach_delay, security_repeat
        self.state, self.recruiting = state, recruiting
        self.save_theirs = save_theirs or (lambda n, raw: None)
        self.record = record or (lambda **kw: None)
        self.their_state = None
        self.approach_at = None
        self.approached = False
        self.our_security = 0
        self.their_security = None
        self.next_security = 0.0
        self.their_pokes = 0
        self.trades = 0

    def game(self, joiner, g, payload, now):
        data_id, fields = g["data_id"], g.get("fields") or {}
        body = payload[room.HEADER_SIZE:]
        if data_id == room.REQUEST:
            a = room.answer(g, state=self.state, is_recruitment=self.recruiting)
            return [a] if a is not None else []
        if data_id == room.STATE and fields:
            was, self.their_state = self.their_state, fields
            if fields.get("isRecruiment") and fields.get("state") == room.STATE_RECRUITMENT_TRADE:
                if fields != was:
                    self.approach_at = now + self.approach_delay
                    self.approached = False
                    self.record(rec="their_emote", t=now, fields=fields)
            return []
        if data_id == room.TALK_RESERVE:
            # the player walked up to our character; unanswered, their character freezes
            self.record(rec="talked_to", t=now)
            return [room.build_talk_reserve_result(can_talk=0, is_recruitment=self.recruiting,
                                                   emoticon_state=self.state)]
        if data_id == room.TALK_RESERVE_RESULT:
            self.record(rec="approach_result", t=now, fields=fields)
            if fields.get("IsCanTalk") == 0:
                return [room.build(room.TALK, bytes.fromhex("0001000000"))]
            self.approached = False
            return []
        if data_id == room.TRADE_TRANER:
            self.record(rec="their_trainer", t=now, fields=room.parse_trade_traner(body))
            return [self.trainer]
        if data_id == room.TRADE_POKE:
            self.their_pokes += 1
            self.save_theirs(self.their_pokes, body)
            self.record(rec="their_poke", t=now, n=self.their_pokes)
            return [room.build_trade_poke(self.offer)]
        if data_id == room.TRADE_POKE_CHECK_OK:
            self.record(rec="their_check_ok", t=now)
            return [room.build_fields(room.TRADE_POKE_CHECK_OK, 1)]
        if data_id == room.TRADE_READY_OK and fields.get("isTradeOk"):
            self.their_security = fields["tradeState"]
            self.record(rec="their_security_state", t=now, state=self.their_security)
            if not self.complete:
                return []
            self.our_security = room.mirror_trade_state(self.their_security)
            self.next_security = now + self.security_repeat
            return [room.build_trade_ready_ok(self.our_security, is_trade_ok=1)]
        if data_id == room.TRADE_READY_OK:
            self.record(rec="their_ready_ok", t=now, fields=fields, answered=self.complete)
            return [room.build_trade_ready_ok()] if self.complete else []
        if data_id == room.RETURN_SELECT:
            if self.our_security or self.their_security is not None:
                self.trades += 1
                self.record(rec="trade_complete", t=now, trades=self.trades)
                show_done()
            self.our_security, self.their_security = 0, None
            return []
        return []

    def tick(self, joiner, now):
        out = []
        if (self.approach_at is not None and not self.approached and now >= self.approach_at
                and joiner.join_acked):
            self.approached = True
            self.approach_at = None
            self.record(rec="approach", t=now)
            out.append(room.build_talk_reserve())
        # a state is re-said once a second: WAIT_READYOK and a CHILD's SEND_READYOK only end on a
        # message arriving inside them, and the repeat stops at the return to the select window
        if (self.our_security and self.their_security is not None and now >= self.next_security
                and not joiner.tx_pending):
            self.next_security = now + self.security_repeat
            out.append(room.build_trade_ready_ok(self.our_security, is_trade_ok=1))
        return out
