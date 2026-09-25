"""The Sword trade host's own messages against a retail host's, and a whole trade against a
scripted joiner. The reference bytes are a retail Sword hosting a completed trade."""
import struct

from pokeldn.ldn import broadcast4, reliable4
from pokeldn.swsh import host_trade, trade

HOST = 16977200745185542144           # the retail host's station id in that trade
JOINER = 11029071703697129472


def test_chain_hash_matches_the_retail_host():
    assert host_trade.chain_hash((2304, 2313, 2278)) == 0x8FFA0F2E
    assert host_trade.chain_hash((2304, 2313, 2338)) == 0xB3615E90
    assert host_trade.chain_hash((2432, 2421, 2404)) == 0xE6DAC45D


def test_element_open_rebuilds_the_retail_triple():
    sent = []
    el = host_trade.Element(50, HOST, JOINER, clock=lambda: 2278)
    el.open(lambda port, payload: sent.append((port, payload.hex())))
    assert sent == [
        (1, "729c00000a0d083210a09c0120e6112a020000"),
        (1, "729c00000a19083210904e188080a08a8fc4c8cdeb0120e6112a0400000000"),
        (1, "729c00000a1a083210a09c01188080a08a8fc4c8cdeb0120e6112a04000018fc"),
    ]


def test_element_values_and_quorum_rebuild_the_retail_bytes():
    clocks = iter([2432, 2421, 2466])
    sent = []
    el = host_trade.Element(40, HOST, JOINER, clock=lambda: next(clocks))
    el.pair_clock = 2404
    send = lambda port, payload: sent.append(payload.hex())     # noqa: E731
    el.set_value(0, bytes(4), send)
    el.set_value(1, bytes(4), send)
    assert sent[0] == "689c00000a0b08282080132a0400000000"
    assert el.hash() == 0xE6DAC45D


class ScriptedJoiner:
    """A joining Sword as the host model reads one: answers, offers, commands, announcements."""

    def __init__(self, pk8):
        self.pk8 = pk8
        self.out = []                 # (kind, port, payload, compressed)
        self.pings = set()
        self.snap_in = broadcast4.Receiver()
        self.snap_out = broadcast4.Sender()
        self.sent_snapshot = False
        self.pairs = {}
        self.box = []
        self.commands_sent = set()

    def data(self, protocol, port, payload):
        self.out.append(("data", protocol, port, payload))

    def on_data(self, protocol, port, payload):
        mid = struct.unpack_from("<I", payload)[0]
        if mid in (97, 110, 120, 130):
            which = next(iter(host_trade.read_fields(payload[4:])))
            if which == trade.PING:
                self.data(protocol, 0, trade.sync(mid, trade.PING_REPLY))
                if mid not in self.pings:
                    self.pings.add(mid)
                    self.data(protocol, 0, trade.sync(mid, trade.PING))
            elif which == trade.PING_SYNCED:
                self.data(protocol, 0, trade.sync(mid, trade.PING_SYNCED))
        elif mid == trade.BLOCK:
            self.data(protocol, port, payload)
        elif mid == trade.POKEMON_TRADE:
            cmd = trade.parse_box_command(payload)
            if trade.offered_pokemon(payload) is not None:
                self.data(protocol, 0, trade.pokemon_trade(self.pk8))
                self.data(protocol, 0, trade.box_sync_state(1))
            if cmd == 4:
                self.data(protocol, 0, trade.box_sync_state(4))
        elif 40000 < mid < 41000:
            got = trade.parse_rpc(payload)
            off = got["offset"]
            if got["base"] == 20000 and got["station_id"] is None:
                phase = struct.unpack("<H", got["body"])[0]
                if off == 50 and phase == 0 and "sent50" not in self.pairs:
                    self.pairs["sent50"] = True
                    self.data(protocol, 0, trade.message(10050,
                                                          trade.field(1, trade.field(1, self.pk8))))
                if off == 40 and phase < host_trade.LADDER_LAST and phase not in self.commands_sent:
                    self.commands_sent.add(phase)
                    self.data(protocol, 0, trade.message(10040, trade.field(
                        1, trade.field_varint(1, phase))))
                announced = phase + 1 if (off in (40, 50) and phase < (1 if off == 50 else 4)) \
                    else host_trade.SENTINEL
                body = struct.pack("<HH", phase, announced)
                self.data(protocol, 1, trade.build_rpc(off, 20000, JOINER, 1, body))

    def on_broadcast(self, port, message, compressed):
        got = broadcast4.parse(message)
        if port == 0:
            body = None
            if got["kind"] == broadcast4.KIND_DATA and compressed:
                import zlib
                body = zlib.decompress(got["body"])
            for reply in self.snap_in.feed(message, body):
                self.out.append(("bcast", 0x84, 0, reply, False))
            if self.snap_in.complete() and not self.sent_snapshot:
                self.sent_snapshot = True
                for msg, packed in self.snap_out.transfer(bytes(3456)):
                    self.out.append(("bcast", 0x84, 1, msg, packed))
                self.out.append(("bcast", 0x84, 1,
                                 broadcast4.build_done(self.snap_out._next()), False))
            if got["kind"] == broadcast4.KIND_DONE:
                self.out.append(("bcast", 0x84, 0, broadcast4.build_done_ack(0), False))


def test_a_scripted_joiner_walks_the_host_to_the_end(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(host_trade.time, "time", lambda: now[0])
    pk8 = bytes(range(256)) + bytes(0x158 - 256)
    joiner = ScriptedJoiner(pk8)
    to_joiner = []
    host = host_trade.HostTrade(
        HOST, JOINER, snapshot=bytes(3456), offer_pk8=bytes(0x158),
        send=lambda protocol, port, payload: to_joiner.append(("data", protocol, port, payload)),
        send_broadcast=lambda port, msg, packed: to_joiner.append(("bcast", 0x84, port, msg,
                                                                   packed)),
        send_mesh=lambda payload: to_joiner.append(("mesh", 0x18, 1, payload)),
        log=lambda *a: None, end_delay=1.0, migrate=True)
    for _ in range(4000):
        host.tick(now[0])
        for item in to_joiner:
            if item[0] == "data":
                joiner.on_data(item[1], item[2], item[3])
            elif item[0] == "bcast":
                joiner.on_broadcast(item[2], item[3], item[4])
        to_joiner.clear()
        for item in joiner.out:
            if item[0] == "data":
                host.on_data(item[1], item[2], item[3], now[0])
            else:
                host.on_broadcast(item[2], item[3], item[4])
        joiner.out.clear()
        if host.stage == "done":
            break
        now[0] += 0.01
    assert host.stage == "done", host.stage
    assert host.elements[50].values[1][0] == pk8
    assert host.elements[40].phase == host_trade.LADDER_LAST
    assert reliable4.PROTOCOL == 0x7C


def test_without_migrate_the_host_holds_after_the_ladder():
    host = host_trade.HostTrade(HOST, JOINER, bytes(3456), bytes(0x158), lambda *a: None,
                                lambda *a: None, lambda *a: None, log=lambda *a: None)
    host.stage, host.stage_since = "saving", 0.0
    host.tick(10_000.0)
    assert host.stage == "saving"
