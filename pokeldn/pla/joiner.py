"""The joining station of a Legends Arceus trade: what a station that joined a console's network owes
it, from the Net answer to the phase protocol.

The order is the retail joiner's, read off a console that joined our host and completed a trade
(`docs/pla.md`, Joining a console's network). The class does no I/O. `receive` takes one
authenticated packet and returns the packets to send back; `poll` returns what a timer owes. Every
packet goes to the host.
"""

import hashlib
import os
import time

from pokeldn.ldn import pia6, pia_connect, reliable5
from pokeldn.pla import channel_table, data_exchange, game_channel, trade_box

PROTO_NET = 0x2C
PROTO_RTT = 0x58
PROTO_CLOCK = 0x77
PROTO_SESSION = 0x98
PROTO_STREAM = data_exchange.PROTOCOL          # 0x81
PROTO_GAME = game_channel.PROTOCOL             # 0x7c

NET_CONN_REQUEST = 0x11
NET_PROPERTY = 0x50
NET_START_HOST_MIGRATION = 0x40
SESSION_JOIN_ACK = 1
SESSION_JOIN_RESPONSE = 2
SESSION_LEAVE = 3
SESSION_UPDATE = 5
SESSION_UPDATE_ACK = 6

# The flags the retail joiner puts on its messages: 0x11 on the Net answers, 0x01 on the join
# request. Everything else goes out under 0x01, as the host that traded with a console sends it.
NET_ANSWER_FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK | pia6.MESSAGE_FLAG_NO_BUNDLING
FLAGS = pia6.MESSAGE_FLAG_SKIP_SOURCE_CHECK
MESH_DESTINATION = 0x0001                     # RTT and 0x81 name the recipient in the footer
MESH_ADDRESSED = (PROTO_RTT, PROTO_STREAM)
HOST_BITMAP = 0x01                            # the host is station 0
OUR_INDEX = 1

# The joiner's own phases on the phase key, and how long the retail joiner waited after the host's
# answer to the previous one before sending each (the 8 s is its trade animation).
PHASES = (3, 6, 11, 14)
PHASE_WAITS = (0.1, 0.3, 8.1, 0.2)

RTT_INTERVAL = 0.5
CLOCK_INTERVAL = 1.0
STREAM_ACK_INTERVAL = 1.0
RETRANSMIT_INTERVAL = 1.0
JOIN_REPEAT = 0.5


class JoinerSession:
    """One joined session. `offer` is the encrypted 0x178-byte record to trade away; `exchange` is
    the 139-byte data exchange record that names the player."""

    def __init__(self, keys, our_ip, our_mac, offer, exchange, *, name=" ",
                 player_id=pia6.DEFAULT_PLAYER_ID, our_var=None, phase_waits=PHASE_WAITS,
                 drive=False, net_answer=True, log=print, clock=time.monotonic):
        self.net_answer = net_answer   # False sends the join with no Net 0x12 (docs/pla.md, Unresolved)
        self.keys, self.our_ip, self.offer, self.exchange = keys, our_ip, bytes(offer), exchange
        self.our_cid = pia_connect.ldn_constant_id(our_mac)
        self.name, self.player_id, self.phase_waits = name, player_id, tuple(phase_waits)
        self.our_var = our_var if our_var is not None else (
            int.from_bytes(os.urandom(2), "big") % 0xFFF0 + 0x10)
        self.log, self.clock, self.drive = log, clock, drive
        self.host_var = self.host_cid = None
        self.join_sent_at = None
        self.accepted = self.seated = self.host_left = False
        self.migration_asked = None    # when the host first sent NetStartHostMigration
        self.last_rtt = self.last_clock = self.last_stream_ack = 0.0
        self.clock_seq = 0
        self.stream_high = {}          # 0x81 port -> the host's highest sequence
        self.host_record = None        # the host's data exchange record
        self.content_sent = False
        self.seq = {}                  # (protocol, port) -> our next sequence
        self.outstanding = {}          # (protocol, port, seq) -> [body, sent_at]
        self.host_keys = set()         # handler keys the host has announced open
        self.our_keys = set()          # handler keys we have announced open
        self.host_opened = False       # the host's port-0 open has arrived and been mirrored
        self.shown = False
        self.answered = set()          # the host messages already answered, one answer each
        self.console_records = []      # (selector, counter, record) the host showed or offered
        self.received = None           # the record the host offered, the one a trade delivers
        self.phase_index = 0           # the next of PHASES to send
        self.phase_ready_at = None
        self.host_phase = 0
        self.phase_closed = False
        self.traded = False
        # With `drive`, the joiner is the player as well: it offers once the host has shown, confirms
        # once the host has offered, and sends selector 7 after the game's 1.5 s stopwatch. Without
        # it, the console's player leads and every step is answered as a host of ours answers it.
        self.host_showed = self.offered = self.confirmed = False
        self.host_confirmed_at = None
        self.sent_seven = False

    # -- packets ---------------------------------------------------------------------------------

    def _packet(self, body, protocol, port=0, flags=FLAGS):
        msg = pia6.build_message(body, protocol=protocol, port=port, message_flags=flags)
        dst, footer = self.host_var or 0, ()
        if protocol in MESH_ADDRESSED:
            dst, footer = MESH_DESTINATION, (self.host_var or 0,)
        return pia6.build_packet(self.keys.session_key, self.keys.network_id, self.our_ip, msg,
                                 dst_var=dst, src_var=self.our_var, packet_id=0,
                                 nonce8=os.urandom(8), footer_ids=footer)

    def _next_seq(self, protocol, port):
        seq = self.seq.get((protocol, port), 1)
        self.seq[(protocol, port)] = seq + 1
        return seq

    def _reliable(self, body, protocol, port, seq):
        """A data message we originate: kept until the host acknowledges it."""
        self.outstanding[(protocol, port, seq)] = [body, self.clock()]
        return self._packet(body, protocol, port)

    def _join_request(self):
        body = pia6.build_session_join(self.our_cid, self.our_var, self.our_ip, self.host_cid,
                                       self.host_var, self.name, os.urandom(4),
                                       player_id=self.player_id)
        self.join_sent_at = self.clock()
        return self._packet(body, PROTO_SESSION)

    def leave(self, sends=4):
        """-> the type-3 leave a console bursts when its player quits, `sends` times."""
        return [self._packet(pia_connect.build_session_leave_v11(
            self.our_cid, self.our_var, self.our_ip, random4=os.urandom(4)), PROTO_SESSION)
            for _ in range(sends)]

    # -- inbound ---------------------------------------------------------------------------------

    def receive(self, messages):
        """-> the packets owed for one authenticated packet's messages."""
        out = []
        for msg in messages:
            handler = {PROTO_NET: self._net, PROTO_SESSION: self._session, PROTO_RTT: self._rtt,
                       PROTO_CLOCK: self._clock, PROTO_STREAM: self._stream,
                       PROTO_GAME: self._game}.get(msg.protocol)
            if handler is not None:
                out += handler(msg)
        return out

    def _net(self, msg):
        p = msg.payload
        if len(p) < 2:
            return []
        if p[1] == NET_START_HOST_MIGRATION and self.migration_asked is None:
            # A console hosting a trade hands the host role to the station that joins; the new
            # host creates the network (docs/pla.md, The Net Protocol). The message is 4 bytes.
            self.migration_asked = self.clock()
            self.log("[pla] the host asked for host migration")
        if len(p) < 8:
            return []
        if p[1] == NET_CONN_REQUEST:
            req = pia_connect.parse_net_conn_request(p)
            if req is None:
                return []
            host_var, host_cid, seq = req
            out = [self._packet(pia_connect.build_net_response(seq), PROTO_NET,
                                flags=NET_ANSWER_FLAGS)] if self.net_answer else []
            if self.host_var is None:
                self.host_var, self.host_cid = host_var, host_cid
                self.log(f"[pla] the host is var {host_var:#06x}, constant id {host_cid.hex()}; "
                         f"joining as var {self.our_var:#06x}")
                out.append(self._join_request())
            return out
        if p[1] == NET_PROPERTY:
            seq = int.from_bytes(p[4:8], "big")
            return [self._packet(pia_connect.build_net_property_ack(seq), PROTO_NET,
                                 flags=NET_ANSWER_FLAGS)]
        return []

    def _session(self, msg):
        p = msg.payload
        if not p:
            return []
        if p[0] == SESSION_JOIN_ACK:
            self.log("[pla] <- join request acknowledged (type 1)")
        elif p[0] == SESSION_JOIN_RESPONSE and len(p) >= 0x2B:
            self.accepted = p[3] == 1
            self.log(f"[pla] <- join response (type 2), status {p[3]}, station {p[0x26]}, "
                     f"sequence {int.from_bytes(p[0x29:0x2B], 'big')}")
        elif p[0] == SESSION_UPDATE and len(p) >= 3:
            seq = p[1:3]
            out = [self._packet(bytes([SESSION_UPDATE_ACK]) + self.our_cid.ljust(8, b"\0")[:8]
                                + b"\0\0" + seq, PROTO_SESSION)]
            if not self.seated:
                self.seated = True
                self.log(f"[pla] <- station list (type 5, sequence {int.from_bytes(seq, 'big')}):"
                         " SEATED; opening the data exchange stream")
                seq_id = self._next_seq(PROTO_STREAM, data_exchange.HOST_PORT)
                out.append(self._reliable(data_exchange.build_stream_open(HOST_BITMAP, seq_id),
                                          PROTO_STREAM, data_exchange.HOST_PORT, seq_id))
            return out
        elif p[0] == SESSION_LEAVE:
            if not self.host_left:
                self.log("[pla] <- the host left the session (type 3)")
            self.host_left = True
        return []

    def _rtt(self, msg):
        p = msg.payload
        if not p or p[0] != 0 or len(p) < 9:
            return []
        reply = bytes([1]) + p[1:9] + (self.host_var or 0).to_bytes(2, "big")
        return [self._packet(reply, PROTO_RTT)]

    def _clock(self, msg):
        p = msg.payload
        if len(p) < 18 or p[0] != 0:
            return []
        ours = int(self.clock() * 1000) & ((1 << 64) - 1)
        return [self._packet(bytes([1]) + p[1:10] + ours.to_bytes(8, "big"), PROTO_CLOCK)]

    def _acked(self, protocol, port, rm, entry_index):
        """Retire what an acknowledgement covers. Entry i acknowledges station i's stream."""
        try:
            entries = reliable5.parse_ack_payload(rm["payload"])["entries"]
        except ValueError:
            return
        if not entries:
            return
        entry = entries[min(entry_index, len(entries) - 1)]
        for key in [k for k in self.outstanding if k[:2] == (protocol, port)
                    and k[2] < entry["ack_id"]]:
            del self.outstanding[key]

    def _stream_ack(self, port, first):
        """The 0x81 acknowledgement, as the retail joiner sends it on both ports: entry 0 for the
        host's stream, entry 1 for its own. Its first carries type 0 and the host's sequence in the
        second field, every later one type 1 and one past it."""
        high = max(self.stream_high.values(), default=0)
        entries = [dict(stream_id=0, ack_id=high + 1, field_0x50=high if first else high + 1),
                   dict(stream_id=0, ack_id=1, field_0x50=1)]
        payload = reliable5.build_ack_payload(entries, unknown0=0 if first else 1)
        body = reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                      lowest_pending=self.seq.get((PROTO_STREAM, port), 1),
                                      destination_bits=1, bitmap=[HOST_BITMAP]) + payload
        return self._packet(body, PROTO_STREAM, port)

    def _stream(self, msg):
        try:
            rm = reliable5.parse(msg.payload)
        except ValueError:
            return []
        if not rm["flags"] & reliable5.FLAG_APPLICATION_DATA:
            self._acked(PROTO_STREAM, msg.port, rm, OUR_INDEX)
            return []
        self.stream_high[msg.port] = max(self.stream_high.get(msg.port, 0), rm["sequence_id"])
        out = [self._stream_ack(msg.port, first=True)]
        self.last_stream_ack = self.clock()
        if rm["flags"] & reliable5.FLAG_ZLIB and self.host_record is None:
            try:
                self.host_record = data_exchange.decompress(rm["payload"])
            except Exception:
                return out
            who = data_exchange.read_record(self.host_record)
            self.log(f"[pla] <- the host's data exchange record: player {who['name']!r}, "
                     f"id {who['player_id'].hex()}")
        if self.host_record is not None and not self.content_sent:
            self.content_sent = True
            seq = self._next_seq(PROTO_STREAM, data_exchange.JOINER_PORT)
            out.append(self._reliable(
                data_exchange.build_content_message(self.exchange, HOST_BITMAP, seq),
                PROTO_STREAM, data_exchange.JOINER_PORT, seq))
            out.append(self._announce(bytes(game_channel.KEY_SIZE), opened=True))
            self.log("[pla] -> our data exchange record, and the trade box key open")
        return out

    def _announce(self, key, opened):
        """-> the channel table message announcing `key` on port 1."""
        if opened:
            self.our_keys.add(key)
        else:
            self.our_keys.discard(key)
        seq = self._next_seq(PROTO_GAME, game_channel.JOINER_PORT)
        flags = None if seq == 1 else (reliable5.FLAG_APPLICATION_DATA
                                       | reliable5.FLAG_MESSAGE_START
                                       | reliable5.FLAG_MESSAGE_END)
        body = game_channel.build_payload_message(channel_table.build([(key, opened)]), seq, flags)
        return self._reliable(body, PROTO_GAME, game_channel.JOINER_PORT, seq)

    def _send_game(self, key, body):
        seq = self._next_seq(PROTO_GAME, game_channel.HOST_PORT)
        return self._reliable(game_channel.build_message(key, body, seq), PROTO_GAME,
                              game_channel.HOST_PORT, seq)

    def _send_box(self, selector, counter):
        seq = self._next_seq(PROTO_GAME, trade_box.PORT)
        body = trade_box.build_message(self.offer, sequence_id=seq, selector=selector,
                                       counter=counter)
        return self._reliable(body, PROTO_GAME, trade_box.PORT, seq)

    def _game(self, msg):
        try:
            cm = reliable5.parse(msg.payload)
        except ValueError:
            return []
        if not cm["flags"] & reliable5.FLAG_APPLICATION_DATA:
            self._acked(PROTO_GAME, msg.port, cm, 0)
            return []
        seq = cm["sequence_id"]
        out = [self._packet(game_channel.build_ack(seq + 1, lowest_pending=seq,
                                                   station_index=0), PROTO_GAME, msg.port)]
        seen = (msg.port, seq)
        if seen in self.answered:
            return out                 # a retransmission, already answered
        self.answered.add(seen)
        payload = cm["payload"]
        if msg.port == game_channel.JOINER_PORT:
            for key, opened in channel_table.parse(payload):
                self.log(f"[pla] <- the host announced key {key.hex()} "
                         f"{'open' if opened else 'closed'}")
                if opened:
                    self.host_keys.add(key)
                    if key not in self.our_keys:
                        out.append(self._announce(key, opened=True))
                else:
                    self.host_keys.discard(key)
            return out + self._advance()
        key, body = game_channel.split_message(payload)
        if key == bytes(game_channel.KEY_SIZE) and cm["flags"] & reliable5.FLAG_IS_INITIALIZED:
            # Mirrored once. A host of ours mirrors the joiner's mirror back, and answering that
            # again would open the channel a third time.
            if not self.host_opened:
                self.host_opened = True
                self.log(f"[pla] <- the host opened the trade box channel, {body.hex()}; mirrored")
                out.append(self._send_game(key, body))
            return out + self._advance()
        offered = trade_box.read_payload(payload)
        if offered is not None:
            self.console_records.append((offered["selector"], offered["counter"],
                                         offered["record"]))
            if offered["selector"] == trade_box.SELECTOR_OFFERING:
                self.received = offered["record"]
            else:
                self.host_showed = True
            self.log(f"[pla] <- the host is {trade_box.selector_name(offered['selector'])} "
                     f"{trade_box.describe(offered['record'])}")
            mark = ("box", offered["selector"], offered["counter"],
                    hashlib.sha256(offered["record"]).digest())
            ours = ("ours", offered["selector"], offered["counter"])
            if offered["selector"] == trade_box.SELECTOR_OFFERING and ours in self.answered:
                self.answered.add(mark)           # our offer for this round is already out
            if mark not in self.answered:
                self.answered.add(mark)
                self.answered.add(ours)
                out.append(self._send_box(offered["selector"], offered["counter"]))
                self.log(f"[pla] -> ours back, {trade_box.selector_name(offered['selector'])}")
            return out + self._advance()
        selector = trade_box.read_selector(payload)
        if selector is not None and selector[0] in trade_box.MIRRORED_SELECTORS:
            if selector[0] == trade_box.SELECTOR_CONFIRMING and self.host_confirmed_at is None:
                self.host_confirmed_at = self.clock()
            if selector[0] == 7:
                self.sent_seven = True
            if ("step", selector[1]) not in self.answered:
                self.answered.add(("step", selector[1]))
                out.append(self._send_game(bytes(game_channel.KEY_SIZE), selector[1]))
                self.log(f"[pla] <-> trade step {trade_box.selector_name(selector[0])} "
                         f"{selector[1].hex()}")
            if selector[0] == 7 and trade_box.PHASE_KEY not in self.our_keys:
                out.append(self._announce(trade_box.PHASE_KEY, opened=True))
                self.log("[pla] -> the phase key open")
            return out + self._advance()
        phase = trade_box.read_phase(payload)
        if phase is not None:
            self.host_phase = max(self.host_phase, phase[1])
            self.log(f"[pla] <- the host's phase, selector {phase[0]}, phase {phase[1]}")
            return out + self._advance()
        self.log(f"[pla] <- game channel port {msg.port} key {key.hex()} body {body.hex()}")
        return out

    # -- the trade, driven by state and time -----------------------------------------------------

    def _advance(self):
        out = []
        now = self.clock()
        if (not self.shown and self.host_opened
                and bytes(game_channel.KEY_SIZE) in self.host_keys):
            self.shown = True
            out.append(self._send_box(trade_box.SELECTOR_SHOWING, 0))
            self.log(f"[pla] -> showing {trade_box.describe(self.offer)}")
        if self.drive:
            out += self._drive(now)
        both_open = (trade_box.PHASE_KEY in self.host_keys
                     and trade_box.PHASE_KEY in self.our_keys)
        if not both_open or self.phase_closed:
            return out
        if self.phase_index < len(PHASES):
            previous = PHASES[self.phase_index - 1] if self.phase_index else 0
            if self.host_phase >= previous:
                if self.phase_ready_at is None:
                    self.phase_ready_at = now + self.phase_waits[self.phase_index]
                if now >= self.phase_ready_at:
                    phase = PHASES[self.phase_index]
                    self.phase_index += 1
                    self.phase_ready_at = None
                    out.append(self._send_game(trade_box.PHASE_KEY,
                                               bytes([trade_box.PHASE_SELECTOR_MINE, phase])))
                    self.log(f"[pla] -> our phase {phase}")
        elif self.host_phase >= PHASES[-1]:
            self.phase_closed = self.traded = True
            out.append(self._announce(trade_box.PHASE_KEY, opened=False))
            self.log("[pla] *** the host answered every phase: the trade is carried out; "
                     "the phase key closed ***")
        return out

    def _drive(self, now):
        out = []
        zero = bytes(game_channel.KEY_SIZE)
        if self.shown and self.host_showed and not self.offered:
            self.offered = True
            self.answered.add(("ours", trade_box.SELECTOR_OFFERING, 0))
            out.append(self._send_box(trade_box.SELECTOR_OFFERING, 0))
            self.log("[pla] -> offering ours (drive)")
        if self.offered and self.received is not None and not self.confirmed:
            self.confirmed = True
            self.answered.add(("step", b"\x05\x00"))
            out.append(self._send_game(zero, b"\x05\x00"))
            self.log("[pla] -> confirming the trade (drive)")
        if (self.confirmed and self.host_confirmed_at is not None and not self.sent_seven
                and now - self.host_confirmed_at >= 1.5):
            self.sent_seven = True
            self.answered.add(("step", b"\x07\x00"))
            out.append(self._send_game(zero, b"\x07\x00"))
            self.log("[pla] -> selector 7 (drive)")
            if trade_box.PHASE_KEY not in self.our_keys:
                out.append(self._announce(trade_box.PHASE_KEY, opened=True))
                self.log("[pla] -> the phase key open")
        return out

    def poll(self):
        """-> the packets a timer owes: the join repeat, RTT, clock, stream acks, retransmits,
        and the next phase once its wait is over."""
        out = []
        now = self.clock()
        if self.host_var is None:
            return out
        if not self.accepted and not self.seated and now - self.join_sent_at >= JOIN_REPEAT:
            out.append(self._join_request())
        if not self.seated:
            return out
        if now - self.last_rtt >= RTT_INTERVAL:
            self.last_rtt = now
            stamp = int(now * 1000) & 0xFFFFFFFFFFFFFFFF
            out.append(self._packet(bytes([0]) + stamp.to_bytes(8, "big") + b"\0\0", PROTO_RTT))
        if now - self.last_clock >= CLOCK_INTERVAL:
            self.last_clock = now
            self.clock_seq = (self.clock_seq + 1) & 0xFF
            stamp = int(now * 1000) & 0xFFFFFFFFFFFFFFFF
            out.append(self._packet(bytes([0, self.clock_seq]) + stamp.to_bytes(8, "big")
                                    + bytes(8), PROTO_CLOCK))
        if self.stream_high and now - self.last_stream_ack >= STREAM_ACK_INTERVAL:
            self.last_stream_ack = now
            out += [self._stream_ack(port, first=False) for port in (data_exchange.HOST_PORT,
                                                                     data_exchange.JOINER_PORT)]
        for (protocol, port, _), entry in sorted(self.outstanding.items()):
            if now - entry[1] >= RETRANSMIT_INTERVAL:
                entry[1] = now
                out.append(self._packet(entry[0], protocol, port))
        return out + self._advance()
