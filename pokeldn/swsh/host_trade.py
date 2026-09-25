"""The hosting side of a Sword/Shield Link Trade, above the Pia 4 host layer.

A hosting Sword leads every stage and the joiner answers. The order, as a retail Sword hosted a
completed trade (docs/swsh_trade.md, docs/swsh_protocol.md):

    1  ping round on id 97; block `result{}` on 0x7C and `imReady` on 0x80
    2  both 3456-byte snapshots on 0x84: ours on port 0, theirs on port 1
    3  ping round on 110, then content 30 (the box): both offers and box commands on 20030
    4  ping round on 130, then content 50 (the exchange): each side's Pokemon
    5  ping round on 120, then content 40 (the confirmation ladder), phases 0..4
    6  box command 3, then MIGRATION_START on the mesh's reliable port

Per content N the joiner talks to the host on holder 10000+N (port 0) and the host publishes the
element on 40000+N (port 1): element 0 is the host's own value, element 1 relays the joiner's,
element 20000 with no owner is the shared phase, and each station has a 20000 pair (phase,
announced) and a 10000 quorum hash.

Nothing here touches a socket: `send(protocol, port, payload)` queues reliable data,
`send_broadcast(port, message, compressed)` sends one 0x84 message, `send_mesh(payload)` a
reliable mesh message on 0x18 port 1.
"""
import struct
import time
import zlib

from pokeldn.ldn import broadcast4, reliable4
from pokeldn.swsh import trade

PORT_CONTENT = 0                      # holders, pings, box commands
PORT_ELEMENT = 1                      # the 40000-family envelopes
FRAMES_PER_SECOND = 60                # the envelope clock advances at the frame rate
CLOCK_BASE = 1700
PING_PERIOD = 0.5
STATE_KEEPALIVE = 2.0                 # republish an element no one has answered
BROADCAST_PERIOD = 0.1
SENTINEL = 0xFC18                     # a pair's announced half before any announcement
LADDER_LAST = 4                       # content 40's teardown phase
END_DELAY = 26.0                      # ladder done to box command 3, as the retail host waited
MIGRATION_DELAY = 0.75
MESH_MIGRATION_START = 0x44


def chain_hash(clocks):
    """The quorum hash: h = crc32(le32(h + clock)) over the element's three clocks."""
    h = 0
    for clock in clocks:
        h = zlib.crc32(struct.pack("<I", (h + clock) & 0xFFFFFFFF))
    return h


def read_fields(data):
    """-> {field: int or bytes} for a flat protobuf message, or {} when it does not parse."""
    try:
        return trade._read_fields(bytes(data))
    except (IndexError, ValueError, KeyError):
        return {}


class PingRound:
    """One SyncPingDataHolder round we open: ping, answer theirs, synced once both replied."""

    def __init__(self, message_id):
        self.id = message_id
        self.last_ping = 0.0
        self.got_reply = self.got_ping = self.sent_synced = self.done = False

    def tick(self, now, send):
        if not self.got_reply and not self.got_ping and now - self.last_ping >= PING_PERIOD:
            send(PORT_CONTENT, trade.sync(self.id, trade.PING))
            self.last_ping = now

    def feed(self, which, send):
        if which == trade.PING:
            self.got_ping = True
            send(PORT_CONTENT, trade.sync(self.id, trade.PING_REPLY))
        elif which == trade.PING_REPLY:
            self.got_reply = True
        elif which == trade.PING_SYNCED:
            self.done = True
        if self.got_reply and self.got_ping and not self.sent_synced:
            send(PORT_CONTENT, trade.sync(self.id, trade.PING_SYNCED))
            self.sent_synced = True


class Element:
    """One content's sync element, as its host runs it."""

    def __init__(self, offset, self_id, peer_id, clock):
        self.offset, self.self_id, self.peer_id = offset, self_id, peer_id
        self.clock = clock                    # a callable -> the next frame clock
        self.values = {0: None, 1: None}      # element id -> (body, clock)
        self.phase = 0                        # the shared value, element 20000 with no owner
        self.announced = SENTINEL             # our pair's high half
        self.pair_clock = None                # the clock our pair's LOW half was last written at
        self.peer_pair = None                 # (phase, announced) off the joiner's 20000
        self.last_publish = 0.0
        self.opened = False

    def _data(self, element_id, owner, clock, body):
        return trade.build_rpc(self.offset, element_id, owner, clock, body)

    def hash(self):
        v0, v1 = self.values[0], self.values[1]
        if v0 is None or v1 is None or self.pair_clock is None:
            return 0
        return chain_hash((v0[1], v1[1], self.pair_clock))

    def set_value(self, element_id, body, send):
        clock = self.clock()
        self.values[element_id] = (bytes(body), clock)
        send(PORT_ELEMENT, self._data(element_id or None, None, clock, body))

    def publish(self, send, shared=False, now=None):
        """The shared phase when asked, then our hash and our pair, on one clock."""
        clock = self.clock()
        if shared:
            send(PORT_ELEMENT, self._data(20000, None, clock, struct.pack("<H", self.phase)))
        if self.pair_clock is None or shared:
            self.pair_clock = clock
        send(PORT_ELEMENT, self._data(10000, self.self_id, clock, struct.pack("<I", self.hash())))
        send(PORT_ELEMENT, self._data(20000, self.self_id, clock,
                                      struct.pack("<HH", self.phase, self.announced)))
        self.last_publish = time.time() if now is None else now

    def open(self, send, now=None):
        self.opened = True
        self.publish(send, shared=True, now=now)

    def announce(self, value, send, now=None):
        self.announced = value
        self.publish(send, now=now)

    def feed(self, got):
        """A joiner envelope for this content: keep its pair."""
        if got["station_id"] == self.peer_id and got["base"] == 20000 and len(got["body"]) == 4:
            self.peer_pair = struct.unpack("<HH", got["body"])

    def peer_announced(self):
        return None if self.peer_pair is None or self.peer_pair[1] == SENTINEL \
            else self.peer_pair[1]

    def advance_if_quorum(self, send, now=None):
        """Both stations announced phase+1: the shared phase moves and our pair catches up."""
        peer = self.peer_announced()
        if (self.announced != SENTINEL and peer is not None and self.announced > self.phase
                and peer >= self.announced):
            self.phase = self.announced
            self.publish(send, shared=True, now=now)
            return True
        return False


class HostTrade:
    """The trade a hosting Sword runs, stage by stage, for one joined station."""

    STAGES = ("ping97", "block", "snapshot", "sync110", "box", "sync130", "exchange", "sync120",
              "confirm", "saving", "migrate", "done")

    def __init__(self, self_id, peer_id, snapshot, offer_pk8, send, send_broadcast, send_mesh,
                 log=print, end_delay=END_DELAY, auto_accept=True, record=None):
        self.self_id, self.peer_id = self_id, peer_id
        self.snapshot = bytes(snapshot)
        self.offer_pk8 = bytes(offer_pk8)
        self._send, self._send_broadcast, self._send_mesh = send, send_broadcast, send_mesh
        self.log, self.record = log, record or (lambda **row: None)
        self.end_delay, self.auto_accept = end_delay, auto_accept
        self.t0 = time.time()
        self.last_clock = CLOCK_BASE
        self.stage = "ping97"
        self.stage_since = self.t0
        self.pings = {i: PingRound(i) for i in (trade.SYNC_PING, 110, 130, 120)}
        self.block_sent = set()
        self.block_echoed = set()
        self.snap_out = broadcast4.Sender()
        self.snap_in = broadcast4.Receiver()
        self.snap_messages = None             # [(message, compressed)] of our transfer
        self.snap_acked = set()
        self.snap_done_acked = False
        self.snap_last = 0.0
        self.snap_order = 0
        self.peer_snapshot = None
        self.elements = {}
        self.box = {"our_offer": False, "our_accept": False, "peer_pk8": None, "peer_cmds": []}
        self.peer_pk8 = None                  # what the joiner put into content 50
        self.peer_commands = []               # the joiner's 10040 syncCommand values
        self.ladder_sent = -1
        self.ladder_done_at = None
        self.box3_at = None

    # -- helpers -------------------------------------------------------------------------------

    def clock(self):
        """The frame clock, strictly increasing across every envelope we send."""
        c = CLOCK_BASE + int((time.time() - self.t0) * FRAMES_PER_SECOND)
        self.last_clock = max(c, self.last_clock + 1)
        return self.last_clock

    def send(self, port, payload, protocol=reliable4.PROTOCOL):
        self._send(protocol, port, payload)

    def goto(self, stage):
        self.log(f"[trade] {self.stage} -> {stage} after {time.time() - self.stage_since:.1f} s")
        self.record(rec="stage", stage=stage, was=self.stage)
        self.stage = stage
        self.stage_since = time.time()

    def element(self, offset):
        if offset not in self.elements:
            self.elements[offset] = Element(offset, self.self_id, self.peer_id, self.clock)
        return self.elements[offset]

    # -- received ------------------------------------------------------------------------------

    def on_data(self, protocol, port, payload, now=None):
        now = time.time() if now is None else now
        payload = bytes(payload)
        if len(payload) < 4:
            self.log(f"[trade] <- {protocol:#04x}/{port} short {payload.hex()}")
            return
        mid = struct.unpack_from("<I", payload)[0]
        body = payload[4:]
        if mid in self.pings:
            which = next(iter(read_fields(body)), None)
            round_ = self.pings[mid]
            round_.feed(which, self.send)
            self.log(f"[trade] <- sync {mid} field {which}")
            return
        if mid == trade.BLOCK:
            self.block_echoed.add((protocol, payload))
            return
        if trade.RPC_ENVELOPE_BASE < mid <= trade.RPC_ENVELOPE_BASE + 1000:
            got = trade.parse_rpc(payload)
            if got and got["offset"] in self.elements:
                self.elements[got["offset"]].feed(got)
            return
        if mid == trade.POKEMON_TRADE:
            pk8 = trade.offered_pokemon(payload)
            command = trade.parse_box_command(payload)
            if pk8 is not None:
                self.box["peer_pk8"] = pk8
                self.log(f"[trade] <- the joiner offers a Pokemon, EC {pk8[:4].hex()}")
                self.record(rec="peer_offer", pk8=pk8.hex())
            if command is not None:
                self.box["peer_cmds"].append(command)
                self.log(f"[trade] <- box command {command}")
                self.record(rec="peer_box_command", command=command)
            return
        if 10000 < mid < 10100:
            self._on_holder(mid - 10000, body)
            return
        self.log(f"[trade] <- {protocol:#04x}/{port} id {mid} unhandled {payload.hex()[:80]}")

    def _on_holder(self, offset, body):
        outer = read_fields(body)
        inner = read_fields(outer.get(1, b"")) if isinstance(outer.get(1), bytes) else {}
        if offset == 50:
            pk8 = inner.get(1)
            if isinstance(pk8, bytes) and len(pk8) in (0x148, 0x158):
                self.peer_pk8 = pk8
                self.log(f"[trade] <- 10050, the joiner's Pokemon, EC {pk8[:4].hex()}")
                self.record(rec="peer_exchange", pk8=pk8.hex())
                if 50 in self.elements and self.elements[50].values[1] is None:
                    self.elements[50].set_value(1, pk8, self.send)
            return
        if offset == 40:
            value = inner.get(1, 0) if inner or isinstance(outer.get(1), bytes) else None
            if isinstance(value, int):
                self.peer_commands.append(value)
                self.log(f"[trade] <- 10040 syncCommand {value}")
                if 40 in self.elements:
                    self.elements[40].set_value(1, struct.pack("<I", value), self.send)
            return
        self.log(f"[trade] <- holder 1000{offset} {body.hex()[:80]}")

    def on_broadcast(self, port, message, compressed):
        """One 0x84 message from the joiner; `compressed` is Pia's 0x10 flag."""
        try:
            got = broadcast4.parse(message)
        except ValueError as exc:
            self.log(f"[trade] <- 0x84/{port} unreadable: {exc}")
            return
        if port == 0:
            # Their answers to our transfer.
            self.snap_out.saw(got["sequence"])
            if got["kind"] == broadcast4.KIND_ACK:
                base, mask = got["base"], got["mask"]
                self.snap_acked.update(range(base))
                self.snap_acked.update(base + 1 + b for b in range(64) if mask >> b & 1)
            elif got["kind"] == broadcast4.KIND_DONE_ACK:
                self.snap_done_acked = True
            return
        body = None
        if got["kind"] == broadcast4.KIND_DATA and compressed:
            body = zlib.decompress(got["body"])
        for reply in self.snap_in.feed(message, body):
            self._send_broadcast(1, reply, False)
        if self.peer_snapshot is None and self.snap_in.complete():
            self.peer_snapshot = self.snap_in.payload()
            self.log(f"[trade] <- the joiner's snapshot, {len(self.peer_snapshot)} bytes")
            self.record(rec="peer_snapshot", payload=self.peer_snapshot.hex())

    # -- the stages ------------------------------------------------------------------------------

    def tick(self, now=None):
        now = time.time() if now is None else now
        getattr(self, "_stage_" + self.stage)(now)

    def _stage_ping97(self, now):
        r = self.pings[trade.SYNC_PING]
        r.tick(now, self.send)
        if r.done:
            self.goto("block")

    def _stage_block(self, now):
        if not self.block_sent:
            self.send(PORT_CONTENT, trade.result())
            self.send(PORT_CONTENT, trade.im_ready(), protocol=reliable4.BROADCAST_PROTOCOL)
            self.block_sent = {1}
        if len(self.block_echoed) >= 2 or now - self.stage_since > 3.0:
            self.goto("snapshot")

    def _stage_snapshot(self, now):
        if self.snap_messages is None:
            self.snap_messages = self.snap_out.transfer(self.snapshot)[1:]
            self.log(f"[trade] -> our snapshot, {len(self.snap_messages)} fragments")
        if now - self.snap_last >= BROADCAST_PERIOD / 5:
            self.snap_last = now
            pending = [i for i in range(len(self.snap_messages)) if i not in self.snap_acked]
            if pending:
                # The retail host sends its control message before each fragment it repeats.
                self.snap_order += 1
                if self.snap_order % 2:
                    msg = broadcast4.build_control(self.snap_out._next(), len(self.snapshot),
                                                   self.snap_out.chunk_size,
                                                   self.snap_out.peer_sequence)
                    self._send_broadcast(0, msg, False)
                else:
                    index = pending[(self.snap_order // 2) % len(pending)]
                    msg, packed = self.snap_messages[index]
                    self._send_broadcast(0, msg, packed)
            elif not self.snap_done_acked:
                self._send_broadcast(0, broadcast4.build_done(self.snap_out._next(),
                                                              self.snap_out.peer_sequence), False)
                self.snap_last = now + BROADCAST_PERIOD
        if self.snap_done_acked and self.peer_snapshot is not None:
            self.goto("sync110")

    def _ping_stage(self, message_id, then, now):
        r = self.pings[message_id]
        r.tick(now, self.send)
        if r.done:
            self.goto(then)

    def _stage_sync110(self, now):
        self._ping_stage(110, "box", now)

    def _stage_box(self, now):
        el = self.element(30)
        if not el.opened:
            el.open(self.send, now)
        elif now - el.last_publish > STATE_KEEPALIVE and el.peer_pair is None:
            el.publish(self.send, now=now)
        if not self.box["our_offer"] and now - self.stage_since > 1.0:
            self.send(PORT_CONTENT, trade.pokemon_trade(self.offer_pk8))
            self.send(PORT_CONTENT, trade.box_sync_state(1))
            self.box["our_offer"] = True
            self.log("[trade] -> our offer and box command 1")
        if (self.auto_accept and not self.box["our_accept"] and self.box["peer_pk8"] is not None
                and 1 in self.box["peer_cmds"]):
            self.send(PORT_CONTENT, trade.box_sync_state(4))
            self.box["our_accept"] = True
            self.log("[trade] -> box command 4, we accept")
        if self.box["our_accept"] and 4 in self.box["peer_cmds"]:
            self.goto("sync130")

    def _stage_sync130(self, now):
        self._ping_stage(130, "exchange", now)

    def _stage_exchange(self, now):
        el = self.element(50)
        if not el.opened:
            el.open(self.send, now)
            return
        if el.values[0] is None and now - self.stage_since > 0.4:
            el.set_value(0, self.offer_pk8, self.send)
            el.announce(1, self.send, now)
        if el.values[1] is None and self.peer_pk8 is not None:
            el.set_value(1, self.peer_pk8, self.send)
            el.publish(self.send, now=now)
        if el.advance_if_quorum(self.send, now) or el.phase >= 1:
            self.goto("sync120")

    def _stage_sync120(self, now):
        self._ping_stage(120, "confirm", now)

    def _stage_confirm(self, now):
        el = self.element(40)
        if not el.opened:
            el.open(self.send, now)
            return
        if el.phase >= LADDER_LAST:
            self.ladder_done_at = now
            self.log("[trade] the ladder reached phase 4")
            self.goto("saving")
            return
        # At phase p we send command p (element 0) and announce p + 1, once.
        if self.ladder_sent < el.phase and el.peer_pair is not None:
            el.set_value(0, struct.pack("<I", el.phase), self.send)
            el.announce(el.phase + 1, self.send, now)
            self.ladder_sent = el.phase
            self.log(f"[trade] ladder: command {el.phase}, announcing {el.phase + 1}")
        el.advance_if_quorum(self.send, now)

    def _stage_saving(self, now):
        if now - self.stage_since >= self.end_delay:
            self.send(PORT_CONTENT, trade.box_sync_state(3))
            self.log("[trade] -> box command 3")
            self.goto("migrate")

    def _stage_migrate(self, now):
        if now - self.stage_since >= MIGRATION_DELAY:
            self._send_mesh(bytes([MESH_MIGRATION_START, 0, 1]))
            self.log("[trade] -> MIGRATION_START, host 0 hands over to 1")
            self.goto("done")

    def _stage_done(self, now):
        pass
