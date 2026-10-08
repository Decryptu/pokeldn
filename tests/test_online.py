"""Online trade: the event signature against BIP-340's own vectors, matching and the channel over
a lossy relay, and two Sword hosts trading their scripted consoles' Pokemon through it."""
import csv
import random
import struct
from pathlib import Path

import pytest

from pokeldn.online import link, schnorr
from pokeldn.swsh import host_trade, trade
from tests.test_swsh_host_trade import HOST, JOINER, ScriptedJoiner

VECTORS = Path(__file__).parent / "data" / "bip340_vectors.csv"


def test_schnorr_matches_every_bip340_vector():
    with VECTORS.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 19
    for row in rows:
        public, message = bytes.fromhex(row["public key"]), bytes.fromhex(row["message"])
        signature = bytes.fromhex(row["signature"])
        if row["secret key"]:
            secret = bytes.fromhex(row["secret key"])
            assert schnorr.public_key(secret) == public, row["index"]
            assert schnorr.sign(secret, message, bytes.fromhex(row["aux_rand"])) == signature
        assert schnorr.verify(public, message, signature) == (row["verification result"] == "TRUE"), \
            row["index"]


class Hub:
    """Every relay at once: an event reaches each subscriber unless the draw loses it, out of order."""

    def __init__(self, loss=0.0, seed=1):
        self.queue, self.pools = [], []
        self.loss, self.rng = loss, random.Random(seed)

    def pool(self, on_event):
        hub = self

        class Pool:
            def subscribe(self, *a):
                pass

            def start(self):
                pass

            def close(self):
                pass

            def connected(self):
                return 1

            def publish(self, event):
                for other in hub.pools:
                    if hub.rng.random() >= hub.loss:
                        hub.queue.append((other, event))
                return 1

        made = Pool()
        made.on_event = on_event
        self.pools.append(made)
        return made

    def deliver(self):
        batch, self.queue = self.queue, []
        self.rng.shuffle(batch)
        for pool, event in batch:
            pool.on_event(event)


def partners(hub, now, count, game="swsh", code="12345678", validate=None):
    made = [link.Partner(game, code, name=f"P{i}", log=lambda *a: None, clock=lambda: now[0],
                         pool_factory=hub.pool, validate=validate) for i in range(count)]
    for p in made:
        p.start(thread=False)
    return made


def run(hub, now, made, until, seconds=120.0, step=0.1, extra=lambda: None):
    end = now[0] + seconds
    while now[0] < end and not until():
        for p in made:
            p.tick()
        hub.deliver()
        extra()
        now[0] += step
    return until()


@pytest.mark.parametrize("count,loss", [(2, 0.0), (7, 0.0), (6, 0.4)])
def test_everyone_in_a_room_pairs_with_one_other(count, loss):
    hub, now = Hub(loss), [1000.0]
    made = partners(hub, now, count)
    assert run(hub, now, made, lambda: sum(p.paired for p in made) == count - count % 2)
    by_key = {p.me.public: p for p in made}
    for p in made:
        if p.paired:
            assert by_key[p.peer].peer == p.me.public


def test_a_different_code_or_game_never_meets():
    hub, now = Hub(), [1000.0]
    made = (partners(hub, now, 1, code="11111111") + partners(hub, now, 1, code="22222222")
            + partners(hub, now, 1, game="sv", code="11111111"))
    assert not run(hub, now, made, lambda: any(p.paired for p in made), seconds=30)


def test_the_channel_carries_rounds_in_order_through_loss():
    hub, now = Hub(loss=0.4, seed=7), [1000.0]
    a, b = partners(hub, now, 2)
    assert run(hub, now, [a, b], lambda: a.paired and b.paired)
    a.offer(b"first")
    a.withdraw()
    a.offer(b"second")
    a.accept()
    assert run(hub, now, [a, b], lambda: b.theirs().accepted)
    assert b.theirs().offer == b"second" and b.theirs().withdrawn == 1
    a.done()
    b.done()
    a.offer(b"next")
    assert run(hub, now, [a, b], lambda: b.theirs().offer == b"next")
    assert b.round == 2 and b.rounds[1].done


def test_a_refused_record_never_reaches_the_partner_side():
    hub, now = Hub(), [1000.0]
    a, b = partners(hub, now, 2, validate=lambda record: ("bad", "") if record == b"bad" else (None, "it"))
    assert run(hub, now, [a, b], lambda: a.paired and b.paired)
    a.offer(b"bad")
    assert run(hub, now, [a, b], lambda: a.theirs().refused == "bad")
    assert b.theirs().offer is None


def test_a_partner_silent_before_any_offer_is_replaced_and_after_one_is_lost():
    hub, now = Hub(), [1000.0]
    a, b = partners(hub, now, 2)
    assert run(hub, now, [a, b], lambda: a.paired and b.paired)
    assert run(hub, now, [a], lambda: a.state == "searching", seconds=link.LOST_AFTER + 5)
    assert run(hub, now, [a, b], lambda: a.paired and b.paired)
    a.offer(b"mon")
    assert run(hub, now, [a], lambda: a.state == "lost", seconds=link.LOST_AFTER + 5)


class FirstOffering(ScriptedJoiner):
    """A joining Sword whose player offers from the box at once and accepts once a Pokemon shows."""

    def on_data(self, protocol, port, payload):
        mid = struct.unpack_from("<I", payload)[0]
        if 40000 < mid < 41000 and trade.parse_rpc(payload)["offset"] == 30 and not self.box:
            self.box.append("offered")
            self.data(protocol, 0, trade.pokemon_trade(self.pk8))
            self.data(protocol, 0, trade.box_sync_state(1))
        if mid == trade.POKEMON_TRADE and trade.offered_pokemon(payload) is not None:
            self.got = trade.offered_pokemon(payload)
            self.data(protocol, 0, trade.box_sync_state(4))
            return
        super().on_data(protocol, port, payload)


def host_for(console, partner):
    out = []
    host = host_trade.HostTrade(
        HOST, JOINER, snapshot=bytes(3456), offer_pk8=bytes(0x158),
        send=lambda protocol, port, payload: out.append(("data", protocol, port, payload)),
        send_broadcast=lambda port, msg, packed: out.append(("bcast", 0x84, port, msg, packed)),
        send_mesh=lambda payload: out.append(("mesh", 0x18, 1, payload)),
        log=lambda *a: None, partner=partner)

    def step(now):
        host.tick(now)
        for item in out:
            if item[0] == "data":
                console.on_data(item[1], item[2], item[3])
            elif item[0] == "bcast":
                console.on_broadcast(item[2], item[3], item[4])
        out.clear()
        for item in console.out:
            if item[0] == "data":
                host.on_data(item[1], item[2], item[3], now)
            else:
                host.on_broadcast(item[2], item[3], item[4])
        console.out.clear()
    return host, step


def test_two_sword_hosts_trade_their_consoles_pokemon_online(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(host_trade.time, "time", lambda: now[0])
    hub = Hub(loss=0.2, seed=3)
    a, b = partners(hub, now, 2)
    mon_a, mon_b = bytes([0xA1]) * 0x158, bytes([0xB2]) * 0x158
    console_a, console_b = FirstOffering(mon_a), FirstOffering(mon_b)
    host_a, step_a = host_for(console_a, a)
    host_b, step_b = host_for(console_b, b)
    seen_before_pairing = []

    def both():
        if not (a.paired and b.paired):
            seen_before_pairing.append(host_a.box["our_offer"] or host_b.box["our_offer"])
        step_a(now[0])
        step_b(now[0])

    assert run(hub, now, [a, b], lambda: host_a.stage == host_b.stage == "saving",
               step=0.01, seconds=300, extra=both)
    assert not any(seen_before_pairing)
    assert console_a.got == mon_b and console_b.got == mon_a
    assert host_a.elements[50].values[0][0] == mon_b and host_a.elements[50].values[1][0] == mon_a
    assert host_b.elements[50].values[0][0] == mon_a and host_b.elements[50].values[1][0] == mon_b
    assert a.round == b.round == 2


def test_a_sword_host_never_accepts_before_the_partner_console_does(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(host_trade.time, "time", lambda: now[0])
    hub = Hub()
    a, b = partners(hub, now, 2)
    console = FirstOffering(bytes([0xA1]) * 0x158)
    host, step = host_for(console, a)
    assert run(hub, now, [a, b], lambda: a.paired and b.paired)
    b.offer(bytes([0xB2]) * 0x158)       # the far console offers and never accepts
    run(hub, now, [a, b], lambda: False, step=0.01, seconds=20, extra=lambda: step(now[0]))
    assert host.box["our_offer"] and not host.box["our_accept"] and host.stage == "box"
    b.withdraw()
    commands = []
    console.on_data = lambda protocol, port, payload: commands.append(trade.parse_box_command(payload))
    run(hub, now, [a, b], lambda: 2 in commands, step=0.01, seconds=10, extra=lambda: step(now[0]))
    assert 2 in commands and not host.box["our_offer"]


class ScarletConsole:
    """A Scarlet whose player offers at once, confirms once a Pokemon shows, and commits once the
    host confirmed, as docs/sv.md's measured exchange orders it."""

    def __init__(self, record):
        from pokeldn.sv import trade as sv
        self.sv, self.record, self.got, self.out = sv, record, None, []
        self.out.append((0, sv.build(sv.KEY_TRADE, sv.KIND_OFFER, 0, record)))

    def on(self, port, payload):
        sv = self.sv
        if port == 1:
            if payload == sv.table_update(sv.KEY_EXCHANGE, True):
                self.out.append((1, payload))
            return
        key, kind, step, body = sv.parse(payload)
        if key == sv.KEY_TRADE and kind == sv.KIND_OFFER:
            self.got = body
            self.out.append((0, sv.build(sv.KEY_TRADE, sv.KIND_CONFIRM)))
        elif key == sv.KEY_TRADE and kind == sv.KIND_CONFIRM:
            self.out.append((0, sv.build(sv.KEY_TRADE, sv.KIND_COMMIT)))
        elif key == sv.KEY_EXCHANGE and kind == sv.KIND_STEP_OPEN:
            self.out.append((0, sv.build(sv.KEY_EXCHANGE, sv.KIND_STEP_OPEN, step)))


def scarlet_host(console, partner):
    from pokeldn.sv import trade as sv
    stage = sv.TradeStage([], partner=partner)
    sent = []

    def step():
        for _, port, payload in stage.tick():
            sent.append((port, payload))
        for port, payload in console.out:
            for _, out_port, reply in stage.on_message(port, payload):
                sent.append((out_port, reply))
        console.out.clear()
        for port, payload in sent:
            console.on(port, payload)
        sent.clear()
    return stage, step


def test_two_scarlet_hosts_trade_their_consoles_pokemon_online():
    hub, now = Hub(loss=0.2, seed=5), [1000.0]
    a, b = partners(hub, now, 2, game="sv")
    mon_a, mon_b = bytes([0xA1]) * 348, bytes([0xB2]) * 348
    console_a, console_b = ScarletConsole(mon_a), ScarletConsole(mon_b)
    host_a, step_a = scarlet_host(console_a, a)
    host_b, step_b = scarlet_host(console_b, b)
    assert run(hub, now, [a, b], lambda: host_a.trades == host_b.trades == 1,
               extra=lambda: (step_a(), step_b()))
    assert console_a.got == mon_b and console_b.got == mon_a
    assert host_a.joiner_offers == [mon_a] and host_b.joiner_offers == [mon_b]
    assert a.round == b.round == 2


def test_a_scarlet_host_confirms_only_after_the_partner_console_does():
    from pokeldn.sv import trade as sv
    hub, now = Hub(), [1000.0]
    a, b = partners(hub, now, 2, game="sv")
    console = ScarletConsole(bytes([0xA1]) * 348)
    stage, step = scarlet_host(console, a)
    assert run(hub, now, [a, b], lambda: a.paired and b.paired)
    b.offer(bytes([0xB2]) * 348)
    run(hub, now, [a, b], lambda: False, seconds=10, extra=step)
    assert console.got == bytes([0xB2]) * 348 and not stage.confirmed and not stage.committed
    b.accept()
    run(hub, now, [a, b], lambda: stage.trades == 1, seconds=10, extra=step)
    assert stage.trades == 1
    b.withdraw()                        # a withdrawal after the trade belongs to the next one
    assert sv.KIND_CANCEL not in [sv.parse(p)[1] for _, _, p in stage.tick()]


def za_seat(partner):
    """A Z-A host with a partner, and a scripted console seated on it up to its box."""
    from pokeldn.ldn import pia_connect
    from pokeldn.za import host as za_host
    from tests import test_za_host as ref
    host = za_host.HostSession(
        ssid=ref.SSID, our_ip=ref.HOST_IP, our_mac=ref.HOST_MAC, guest_ip=ref.JOINER_IP,
        code="00000000", identity=bytes.fromhex("1400") + bytes(104),
        identity_tail=bytes.fromhex("1403b9018269fb308f"), selection=bytes.fromhex("0100") + bytes(1209),
        offer=[], host_var=ref.HOST_VAR, clock=lambda: 0.0, log=lambda *a: None, partner=partner)
    console = ref.ScriptedJoiner(host)
    t = console.run(0.1, 0.0)
    console.send(pia_connect.PROTO_NET, bytes.fromhex("0112000000000002"), dst=0, now=t)
    console.send(pia_connect.PROTO_SESSION, ref.JOIN, dst=0, now=t)
    console.send(pia_connect.PROTO_SESSION, bytes.fromhex("067f00030000020000000000000001"), now=t)
    t = console.run(t + 1.3, t)
    console.send(pia_connect.PROTO_SESSION, bytes.fromhex("067f00030000020000000000010001"), now=t)
    console.run(t + 3.0, t)
    return host, console


def za_player(console, record):
    """The console's player: picks `record`, confirms once the partner's pick shows, and walks the
    four steps once the host's 0104 arrives."""
    state = {"picked": False, "confirmed": False, "stepped": False}

    def play(t):
        heard = [x[2] for x in console.game_heard()]
        if not state["picked"]:
            state["picked"] = True
            console.game(record, t)
        if not state["confirmed"] and any(h[:2] == b"\x01\x01" and h[-1] == 0 for h in heard):
            state["confirmed"] = True
            console.game(bytes.fromhex("0102b90100"), t)
        if not state["stepped"] and any(h[:2] == b"\x01\x04" for h in heard):
            state["stepped"] = True
            console.game(bytes.fromhex("0104b90100"), t)
            for step in ("03", "06", "0b", "0e"):
                console.game(bytes.fromhex("0200b901" + step), t)
    return play


def test_two_za_hosts_trade_their_consoles_pokemon_online():
    hub, now = Hub(loss=0.2, seed=11), [1000.0]
    a, b = partners(hub, now, 2, game="za")
    head = bytes.fromhex("0101b90300bc815801")
    pick_a, pick_b = head + bytes([0xA1]) * 344 + b"\x00", head + bytes([0xB2]) * 344 + b"\x00"
    (host_a, console_a), (host_b, console_b) = za_seat(a), za_seat(b)
    play_a, play_b = za_player(console_a, pick_a), za_player(console_b, pick_b)
    clock = [10.0]

    def step():
        play_a(clock[0])
        play_b(clock[0])
        console_a.run(clock[0] + 0.05, clock[0])
        console_b.run(clock[0] + 0.05, clock[0])
        clock[0] += 0.1

    assert run(hub, now, [a, b], lambda: host_a.trades == host_b.trades == 1, extra=step)
    shown_a = [x[2] for x in console_a.game_heard() if x[2][:2] == b"\x01\x01"]
    assert [m[-1] for m in shown_a] == [1, 0] and shown_a[1] == pick_b
    shown_b = [x[2] for x in console_b.game_heard() if x[2][:2] == b"\x01\x01"]
    assert shown_b[1] == pick_a
    sent_a = [x[2].hex() for x in console_a.game_heard() if x[2][:2] in (b"\x01\x02", b"\x01\x04")]
    assert sent_a == ["0102b90100", "0104b90100"]
    assert a.round == b.round == 2


def test_two_arceus_boxes_trade_their_consoles_pokemon_online():
    """Each console offers (selector 4), confirms (5) once the partner's offer shows, and counts
    the trade once its 5 is mirrored: the mirror goes only when both consoles confirmed."""
    from pokeldn.pla import trade_box
    hub, now = Hub(loss=0.2, seed=13), [1000.0]
    a, b = partners(hub, now, 2, game="pla")
    sides = []
    for partner, mon in ((a, bytes([0xA1]) * 376), (b, bytes([0xB2]) * 376)):
        sides.append({"box": trade_box.OnlineBox(partner), "mon": mon, "got": None, "confirmed": False,
                      "mirrored": [], "offered": False})

    def console(side):
        box = side["box"]
        answers = []
        if not side["offered"]:
            side["offered"] = True
            answers += box.on_box({"selector": trade_box.SELECTOR_OFFERING, "counter": 1,
                                   "record": side["mon"]})
        offers, mirrors = box.tick()
        answers += offers
        side["mirrored"] += mirrors
        for selector, counter, record in answers:
            assert selector == trade_box.SELECTOR_OFFERING and counter == 1
            side["got"] = record
        if side["got"] and not side["confirmed"]:
            side["confirmed"] = True
            side["mirrored"] += box.on_selector(trade_box.SELECTOR_CONFIRMING, b"\x05\x01")
        if side["mirrored"] and not side.get("done"):
            side["done"] = True
            box.done()

    assert run(hub, now, [a, b], lambda: all(s.get("done") for s in sides),
               extra=lambda: [console(s) for s in sides])
    assert sides[0]["got"] == sides[1]["mon"] and sides[1]["got"] == sides[0]["mon"]
    assert sides[0]["mirrored"] == sides[1]["mirrored"] == [b"\x05\x01"]


def test_a_lets_go_host_answers_with_the_partner_record_and_holds_a2_for_their_vote(tmp_path, monkeypatch):
    """The console's kind 2 waits for the partner's record; its 1 1 1 on the offered clone gets
    A 1 at once and A 2 (the console's save) only once the partner's console voted."""
    from pokeldn.ldn import clone, reliable3
    from pokeldn.lgpe import pb7
    from tests import test_lgpe_host_commit as ref
    lgpe_host = ref.lgpe_host
    hub, now = Hub(), [1000.0]
    a, b = partners(hub, now, 2, game="lgpe")
    assert run(hub, now, [a, b], lambda: a.paired and b.paired)
    clk = ref.Clock()
    monkeypatch.setattr(lgpe_host.time, "monotonic", clk)
    args = lgpe_host.build_parser().parse_args(["--first", "echo", "--our-trainer", "41234:12345"])
    s = lgpe_host.Session(ref.Radio(), lgpe_host.Advertisement(0x2952124b, 0xe28ef1be), args,
                          lambda **kw: None, partner=a)
    s.peer_ip, s.peer_mac = "169.254.38.2", bytes.fromhex("48f1eb209b22")
    s.joined = True
    s.new_clone()
    sent = []
    monkeypatch.setattr(s, "send", lambda payload, protocol, **kw: sent.append((protocol, payload)))
    s.trade["step"] = 10
    s.clone.state_word = 10
    s.window.expected = reliable3.FIRST_SEQUENCE + 11
    for cid in (1, 2, 3):
        s.clone.held.add(cid)

    def body(byte):
        plain = bytearray(pb7.BOX_SIZE)
        struct.pack_into("<I", plain, 0, 0x5a1c3300 | byte)
        struct.pack_into("<H", plain, 8, 25)
        return pb7.encrypt(bytes(plain))

    mine, theirs = body(0xA1), body(0xB2)

    def offers_sent():
        out = []
        for protocol, payload in sent:
            r = reliable3.parse(payload) if protocol == reliable3.PROTOCOL else None
            if r and r["size"]:
                m = pb7.parse_message(r["payload"])
                if m["kind"] == pb7.OFFER_MESSAGE:
                    out.append(m["body"])
        return out

    def votes(cid=3):
        out = []
        for protocol, payload in sent:
            d = clone.parse_data_message(payload) if protocol == clone.PROTOCOL else None
            if d and d["type"] == clone.STATE_DATA and d["clone_id"] == cid and d["ctype"] == 2 \
                    and d["record"]:
                data = d["record"]["data"]
                out.append([int.from_bytes(data[i:i + 4], "little") for i in (0, 4, 8, 16)])
        return out

    def advance(seconds):
        end = clk.t + seconds
        while clk.t < end:
            clk.t += 0.01
            now[0] += 0.01
            for p in (a, b):
                p.tick()
            hub.deliver()
            if s.window.pending and clk.t - s.window.pending[0][2] >= 0.03:
                s.handle(reliable3.PROTOCOL, reliable3.build_ack(s.window.sequence))
            s.tick()

    seq = s.window.expected
    s.handle(reliable3.PROTOCOL, reliable3.build(pb7.build_message(pb7.OFFER_MESSAGE, mine, step=12),
                                                 seq, reliable3.FIRST_SEQUENCE))
    advance(2.0)
    assert offers_sent() == [] and b.theirs().offer == mine
    b.offer(theirs)
    advance(2.0)
    assert offers_sent() == [theirs]
    rec = clone.build_state_record(3, ref.JOINER, 3, s.clone.ms(clk()),
                                   ref.ONES + struct.pack("<I", 12) + bytes(4))
    s.handle(clone.PROTOCOL, clone.build_data_message(clone.STATE_DATA, 2, ref.JOINER, 3,
                                                      s.clone.frame(clk()), rec, flags=3))
    advance(5.0)
    assert votes()[-1] == [1, 1, 1, 1] and [1, 2, 2, 2] not in votes() and b.theirs().accepted
    b.accept()
    advance(3.0)
    assert votes()[-1] == [1, 2, 2, 2]


def test_two_bdsp_rooms_trade_their_consoles_pokemon_online():
    """Each console's 0x13 is answered with the far console's, and the ready-ok that lets a console
    save goes only once both consoles sent theirs."""
    from types import SimpleNamespace
    from pokeldn.bdsp import host as bdsp, room
    hub, now = Hub(loss=0.2, seed=17), [1000.0]
    a, b = partners(hub, now, 2, game="bdsp")
    joiner = SimpleNamespace(join_acked=True, tx_pending={})
    sides = [{"p": bdsp.TradePartner(bytes(0), complete=True, remote=r), "mon": bytes([m]) * 328,
              "got": None, "ready": False, "said": False} for r, m in ((a, 0xA1), (b, 0xB2))]

    def say(side, message):
        g = room.parse(message)
        return side["p"].game(joiner, g, message, now[0])

    def console(side):
        out = []
        if not side["said"]:
            side["said"] = True
            out += say(side, room.build_trade_poke(side["mon"]))
            assert out == []
        out += side["p"].tick(joiner, now[0])
        for message in out:
            g = room.parse(message)
            if g["data_id"] == room.TRADE_POKE:
                side["got"] = g["body"]
                assert say(side, room.build_fields(room.TRADE_POKE_CHECK_OK, 1)) == \
                    [room.build_fields(room.TRADE_POKE_CHECK_OK, 1)]
                assert say(side, room.build_trade_ready_ok(room.TRADE_STATE_WAIT, 0)) == []
            elif g["data_id"] == room.TRADE_READY_OK:
                side["ready"] = True

    assert run(hub, now, [a, b], lambda: all(s["ready"] for s in sides),
               extra=lambda: [console(s) for s in sides])
    assert sides[0]["got"] == sides[1]["mon"] and sides[1]["got"] == sides[0]["mon"]
    for side, remote in zip(sides, (a, b)):
        out = []
        for state in (1, 2, 3, 4, 5):
            out += say(side, room.build_trade_ready_ok(state, 1))
        assert out[-1] == room.build_trade_ready_ok(room.mirror_trade_state(5), 1)
        assert side["p"].trades == 1 and remote.round == 2


def test_two_firered_hosts_relay_the_parties_and_trade_the_picks_online():
    """Each console gets the far console's party pair by pair, the far player's pick as our
    SET_MONS, and START_TRADE only once both said YES (docs/online.md, FireRed)."""
    from pokeldn.frlg.link.host_trade import HostTradeEngine
    from pokeldn.frlg.save import mon
    from tests.test_host_trade_engine import ScriptedChild, _mon
    hub, now = Hub(loss=0.1, seed=19), [1000.0]
    a, b = partners(hub, now, 2, game="frlg")
    party_a, party_b = [_mon(0x21), _mon(0x22)], [_mon(0x31), _mon(0x32)]
    hosts = [HostTradeEngine([mon.Mon(bytes(100))], anim_delay=1, partner=p) for p in (a, b)]
    children = [ScriptedChild(h, party, offered=(pick,))
                for h, party, pick in ((hosts[0], party_a, 1), (hosts[1], party_b, 0))]
    warped = [False, False]

    def step():
        for n, (h, c) in enumerate(zip(hosts, children)):
            for _ in range(20):
                c.consume_host_words(h.tick())
                if h.established and not warped[n]:
                    warped[n] = True
                    c.send_standby(0)
                c.maybe_select()

    assert run(hub, now, [a, b], lambda: all(h.commits == 1 for h in hosts), seconds=600,
               extra=step)
    assert [m.raw for m in hosts[0].received_mons] == [party_a[1].raw]
    assert [m.raw for m in hosts[1].received_mons] == [party_b[0].raw]
    assert children[0].party[1].raw == party_b[0].raw
    assert children[1].party[0].raw == party_a[1].raw
    queued = [x[1] for x in hosts[0].trace if x[0] == "queue_block"]
    assert queued.count("host:party:0:partner") == 1 and queued.count("SET_MONS_TO_TRADE") == 1
    assert queued.index("SET_MONS_TO_TRADE") < queued.index("START_TRADE")
