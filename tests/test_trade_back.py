"""Trade back (pokeldn.trade_back): the trade after each queued one returns, byte for byte, the Pokemon the
console just sent, in every title and both roles."""
import pytest

from test_host_end_to_end import ImpairedRadio, ScriptedFireRedChild, _mon
from pokeldn.frlg.link import trade
from pokeldn.frlg.link.host_session import HostSession
from pokeldn.trade_back import Rounds, TradeBack


@pytest.mark.parametrize("count", [1, 6])
def test_a_firered_host_returns_the_console_pokemon_in_the_slot_it_offered(count):
    """TradeMons puts the received mon in the offered slot [trade_scene.c:1054-1083]; offering that slot
    again sends it back, and the console's party carries its own Pokemon again. Six queued make twelve trades."""
    ours, theirs = [_mon(0x11 + n) for n in range(count)], [_mon(0x21 + n) for n in range(count)]
    slots = trade.trade_back_slots(list(range(count)))
    host = HostSession(ours, trades=2 * count, offered_slots=slots, anim_delay=1,
                       reliable_kwargs={"ack_period_ms": 5, "rto_bootstrap_ms": 20},
                       rfu_kwargs={"host_session_id": b"\xb7\xf1"})
    child = ScriptedFireRedChild(theirs, offered=slots, trades=2 * count)
    radio = ImpairedRadio()
    for emission in child.start(0):
        radio.send("child", emission, 0)
    for now in range(12000 * count):
        for packet in radio.deliver(now):
            if packet.direction == "child":
                host.receive_reliable(packet.wire, now)
            else:
                child.receive(packet.wire, now)
        for emission in host.tick(now):
            radio.send("host", emission, now)
        for emission in child.advance(now):
            radio.send("child", emission, now)
        if host.trade.done and child.disconnect_seen and not radio.pending:
            break
    assert host.trade.commits == child.confirmed == 2 * count
    assert [m.raw for m in host.trade.received_mons] == [m.raw for pair in zip(theirs, ours) for m in pair]
    assert [m.raw for m in child.party] == [m.raw for m in theirs]
    assert [m.raw for m in host.trade.party] == [m.raw for m in ours]


@pytest.mark.parametrize("slots,ok", [([0, 0, 1, 1], True), ([0, 1, 1], True), ([0, 0, 0], False),
                                      ([0, 1, 0], False), ([0, 0, 1, 0], False)])
def test_a_firered_slot_is_offered_again_only_by_the_next_trade(slots, ok):
    assert trade.distinct_but_returned(slots) is ok


def test_rounds_alternate_the_queue_with_what_came_back():
    rounds = Rounds([b"A", b"B"], log=lambda *a: None)
    seen = []
    for got in (b"x", b"A", b"y", b"B", b"z"):
        seen.append(rounds.current())
        rounds.done(got)
    assert seen == [b"A", b"x", b"B", b"y", b"B"]
    assert rounds.current() == b"z"


def test_a_round_whose_pokemon_was_not_kept_moves_on_to_the_queue():
    rounds = Rounds([b"A", b"B"], log=lambda *a: None)
    rounds.done(None)
    assert rounds.current() == b"B"


@pytest.mark.parametrize("screen_open", [True, False])
def test_a_scarlet_host_returns_the_console_record(screen_open):
    """A console still on its way to the trade screen loses an offer sent then: ours goes once the console's
    own is up."""
    from test_online import ScarletConsole, scarlet_host
    from pokeldn.sv import trade as sv
    ours, theirs = bytes([0x11]) * 348, bytes([0xA1]) * 348
    console = ScarletConsole(theirs, screen_open=screen_open)
    stage, step = scarlet_host(console, TradeBack("sv", [ours], log=lambda *a: None))
    for _ in range(5):
        step()
    if not screen_open:
        console.open()
    for _ in range(200):
        step()
        if stage.trades == 1:
            break
    assert stage.trades == 1 and console.got == ours
    console.out.append((0, sv.build(sv.KEY_TRADE, sv.KIND_OFFER, 0, console.got)))
    for _ in range(200):
        step()
        if stage.trades == 2:
            break
    assert stage.trades == 2 and console.got == theirs and stage.joiner_offers == [theirs, ours]


def test_a_sword_host_returns_the_console_record(monkeypatch):
    """The second trade on one session (tests/test_swsh_host_trade.py) offers what the first received."""
    import struct
    from test_swsh_host_trade import HOST, JOINER, ScriptedJoiner
    from pokeldn.swsh import host_trade, trade as swsh
    now = [1000.0]
    monkeypatch.setattr(host_trade.time, "time", lambda: now[0])
    ours, theirs = bytes([0x11]) * 0x158, bytes(range(256)) + bytes(0x158 - 256)
    joiner, to_joiner, offered = ScriptedJoiner(theirs), [], []
    host = host_trade.HostTrade(
        HOST, JOINER, snapshot=bytes(3456), offer_pk8=ours,
        send=lambda protocol, port, payload: to_joiner.append(("data", protocol, port, payload)),
        send_broadcast=lambda port, msg, packed: to_joiner.append(("bcast", 0x84, port, msg, packed)),
        send_mesh=lambda payload: to_joiner.append(("mesh", 0x18, 1, payload)),
        log=lambda *a: None, partner=TradeBack("swsh", [ours], log=lambda *a: None))

    def run(until):
        for _ in range(4000):
            host.tick(now[0])
            for item in to_joiner:
                if item[0] == "data":
                    if struct.unpack_from("<I", item[3])[0] == swsh.POKEMON_TRADE:
                        pk8 = swsh.offered_pokemon(item[3])
                        if pk8 is not None:
                            offered.append(pk8)
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
            if until():
                return
            now[0] += 0.01
    run(lambda: host.trades == 1 and host.stage == "saving")
    now[0] += 3.0
    joiner.pk8 = ours
    joiner.pings.clear()
    joiner.pairs.clear()
    joiner.commands_sent.clear()
    host.on_data(0x7C, 0, swsh.pokemon_trade(ours), now[0])
    host.on_data(0x7C, 0, swsh.box_sync_state(1), now[0])
    run(lambda: host.trades == 2 and host.stage == "saving")
    assert host.trades == 2 and offered == [ours, theirs]
    assert host.elements[50].values[0][0] == theirs and host.elements[50].values[1][0] == ours


def test_an_arceus_box_returns_the_console_record():
    from pokeldn.pla import trade_box
    ours, theirs = bytes([0x11]) * 376, bytes([0xA1]) * 376
    box = trade_box.OnlineBox(TradeBack("pla", [ours], log=lambda *a: None))
    got = []
    for mon in (theirs, ours):
        answers = box.on_box({"selector": trade_box.SELECTOR_OFFERING, "counter": 1, "record": mon})
        offers, mirrors = box.tick()
        got += [record for _, _, record in answers + offers]
        mirrors += box.on_selector(trade_box.SELECTOR_CONFIRMING, b"\x05\x01")
        assert mirrors == [b"\x05\x01"]
        box.done()
    assert got == [ours, theirs]


def test_a_brilliant_diamond_room_returns_the_console_record():
    from types import SimpleNamespace
    from pokeldn.bdsp import host as bdsp, room
    ours, theirs = bytes([0x11]) * 328, bytes([0xA1]) * 328
    joiner = SimpleNamespace(join_acked=True, tx_pending={})
    p = bdsp.TradePartner(bytes(0), complete=True, remote=TradeBack("bdsp", [ours], log=lambda *a: None))
    got = []

    def say(message):
        return p.game(joiner, room.parse(message), message, 0.0)
    for mon in (theirs, ours):
        out = say(room.build_trade_poke(mon)) + p.tick(joiner, 0.0)
        got += [room.parse(m)["body"] for m in out if room.parse(m)["data_id"] == room.TRADE_POKE]
        say(room.build_fields(room.TRADE_POKE_CHECK_OK, 1))
        say(room.build_trade_ready_ok(room.TRADE_STATE_WAIT, 0))
        p.tick(joiner, 0.0)
        for state in (1, 2, 3, 4, 5):
            say(room.build_trade_ready_ok(state, 1))
        say(room.build_fields(room.RETURN_SELECT, 0))
    assert p.trades == 2 and got == [ours, theirs]


def test_a_za_host_previews_and_picks_the_console_record():
    from test_online import za_player, za_seat
    head = bytes.fromhex("0101b90300bc815801")
    ours, theirs = head + bytes([0x11]) * 344 + b"\x00", head + bytes([0xA1]) * 344 + b"\x00"
    host, console = za_seat(TradeBack("za", [ours], log=lambda *a: None))
    clock, shown = [10.0], []
    for trade_no, pick in ((1, theirs), (2, ours)):
        if trade_no == 2:
            console.heard.clear()       # the first trade's messages would answer the player's checks
        play = za_player(console, pick)
        while host.trades < trade_no and clock[0] < 60 * trade_no:
            play(clock[0])
            console.run(clock[0] + 0.05, clock[0])
            clock[0] += 0.1
        shown.append([x[2] for x in console.game_heard() if x[2][:2] == b"\x01\x01"])
    assert host.trades == 2
    assert shown[0][-1] == ours and shown[1][-1] == theirs


def test_a_lets_go_host_answers_the_next_round_with_the_console_record(monkeypatch):
    """The console's offer of round 2 (kind 4) is answered with the record its round-1 offer carried."""
    import struct
    from pokeldn.ldn import reliable3
    from pokeldn.lgpe import pb7
    from tests import test_lgpe_host_commit as ref
    lgpe_host = ref.lgpe_host
    clk = ref.Clock()
    monkeypatch.setattr(lgpe_host.time, "monotonic", clk)

    def body(byte):
        plain = bytearray(pb7.BOX_SIZE)
        struct.pack_into("<I", plain, 0, 0x5a1c3300 | byte)
        struct.pack_into("<H", plain, 8, 25)
        return pb7.encrypt(bytes(plain))
    ours, theirs = body(0x11), body(0xA1)
    args = lgpe_host.build_parser().parse_args(["--first", "echo", "--our-trainer", "41234:12345"])
    s = lgpe_host.Session(ref.Radio(), lgpe_host.Advertisement(0x2952124b, 0xe28ef1be), args,
                          lambda **kw: None, partner=TradeBack("lgpe", [ours], log=lambda *a: None))
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

    def offers_sent():
        out = []
        for protocol, payload in sent:
            r = reliable3.parse(payload) if protocol == reliable3.PROTOCOL else None
            if r and r["size"]:
                m = pb7.parse_message(r["payload"])
                if m["kind"] in (pb7.OFFER_MESSAGE, pb7.OFFER_MESSAGE + 2):
                    out.append(m["body"])
        return out

    def advance(seconds):
        end = clk.t + seconds
        while clk.t < end:
            clk.t += 0.01
            if s.window.pending and clk.t - s.window.pending[0][2] >= 0.03:
                s.handle(reliable3.PROTOCOL, reliable3.build_ack(s.window.sequence))
            s.tick()

    def say(kind, data, step):
        s.handle(reliable3.PROTOCOL, reliable3.build(pb7.build_message(kind, data, step=step),
                                                     s.window.expected, reliable3.FIRST_SEQUENCE))
    say(pb7.OFFER_MESSAGE, theirs, 12)
    advance(2.0)
    assert offers_sent() == [ours]
    say(pb7.RESULT_MESSAGE, bytes(4), 14)
    advance(1.0)
    assert s.round == 1
    say(pb7.OFFER_MESSAGE + 2, ours, 16)
    advance(2.0)
    assert offers_sent() == [ours, theirs]
