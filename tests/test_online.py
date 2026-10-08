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
