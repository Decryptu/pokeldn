"""bin/pla_host.py against a scripted Arceus console, with packets lost and with a second trade in
the same session. The host's own main loop runs over a loopback transport on a fake clock.

The console is `pokeldn.pla.joiner.JoinerSession` driving the trade as a player would, behind the
console's own 0x7c receive window: every message's lowest-pending field walks the window base over
empty slots (`0x74c250`, before the flag dispatch at `0x74c3ac`), a message below the base is
discarded with an acknowledgement, the rest are handed to the game in order, and the
acknowledgement is the base with the held ones in the mask (`0x74ee1c`). It acts on the host's phase
only under the host's selector 2 (`0x26d7e5c` reads the pair only selector 2 writes, `0x26d7f90`).
docs/pla.md, Acknowledgement and The completed trade."""
import importlib.util
import os
import struct
import sys
import types

import pytest

from pokeldn import gen8, pla
from pokeldn.ldn import pia6, reliable5
from pokeldn.pla import channel_table, data_exchange, game_channel, joiner, trade_box
from pokeldn.pla import pokemon as pla_pokemon

ROOT = os.path.join(os.path.dirname(__file__), "..")
HOST_PATH = os.path.join(ROOT, "bin", "pla_host.py")
spec = importlib.util.spec_from_file_location("pla_host", HOST_PATH)
pla_host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pla_host)

SSID = bytes.fromhex("00112233445566778899aabbccddeeff")
HOST_IP, CONSOLE_IP = "169.254.1.1", "169.254.1.2"
CONSOLE_MAC = bytes.fromhex("0200a9fe0102")
SECONDS = 90.0                      # the host's --seconds, on the fake clock
SETTLE = 2.0                        # run on after the goal so the host reads the console's close


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _faithful_trade_box():
    """`trade_box` as the console reads it: a phase counts only under the host's selector 2."""
    def read_phase(payload):
        phase = trade_box.read_phase(payload)
        return phase if phase is None or phase[0] == trade_box.PHASE_SELECTOR_HOST else None
    proxy = types.ModuleType("trade_box")
    proxy.__dict__.update(trade_box.__dict__)
    proxy.read_phase = read_phase
    return proxy


class Console(joiner.JoinerSession):
    """`JoinerSession` behind the console's receive window. `delivered` is every (port, sequence)
    of the host's the game was handed, in order."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.windows = {}              # port -> [base, {seq: message held}]
        self.delivered = []

    def _game(self, msg):
        try:
            cm = reliable5.parse(msg.payload)
        except ValueError:
            return []
        window = self.windows.setdefault(msg.port, [1, {}])
        while window[0] < cm["lowest_pending"] and window[0] not in window[1]:
            window[0] += 1
        if not cm["flags"] & reliable5.FLAG_APPLICATION_DATA:
            return super()._game(msg)
        if cm["sequence_id"] >= window[0]:
            window[1].setdefault(cm["sequence_id"], msg)
        out = []
        while window[0] in window[1]:
            self.delivered.append((msg.port, window[0]))
            out += self._game_message(msg.port, reliable5.parse(window[1].pop(window[0]).payload))
            window[0] += 1
        ack = game_channel.build_ack(window[0], lowest_pending=self._own_lowest(msg.port),
                                     mask=reliable5.build_mask(window[1], window[0]))
        return [self._packet(ack, joiner.PROTO_GAME, msg.port)] + out


def _data(messages):
    """-> [(port, reliable message, bytes)] of the 0x7c application data among `messages`."""
    out = []
    for m in messages:
        if m.protocol != reliable5.PROTOCOL:
            continue
        try:
            cm = reliable5.parse(m.payload)
        except ValueError:
            continue
        if cm["flags"] & reliable5.FLAG_APPLICATION_DATA:
            out.append((m.port, cm, m.payload))
    return out


def run_host(monkeypatch, capsys, console_class, goal, drop=None):
    """Run the host's main against `console_class` until `goal(console)` holds (plus SETTLE) or the
    run ends. `drop(port, payload)` loses the first host 0x7c message it matches on the air.
    -> .console, .log (the host's), .sent (every host 0x7c data (port, seq)), .copies
    [(port, seq, message bytes, packet)] of those that reached the console, .lost (one of those)."""
    clock = Clock()
    keys = pla.session_keys(SSID)
    exchange = data_exchange.build_record(player_id=bytes.fromhex("504b4c44"), name="PkCamp")
    offer = trade_box.build_our_record(**data_exchange.read_record(exchange))
    run = types.SimpleNamespace(
        console=console_class(keys, CONSOLE_IP, CONSOLE_MAC, offer, exchange, drive=True,
                              log=lambda *a: None, clock=clock),
        sent=set(), copies=[], lost=None, done_at=None)

    class Loopback:
        ssid, our_ip, our_mac = SSID, HOST_IP, bytes.fromhex("0200a9fe0101")
        participants = [(0, CONSOLE_IP)]
        join_events = 1

        def __init__(self, **_kw):
            self.inbox = []

        def start(self):
            pass

        def stop(self):
            pass

        def send(self, pkt, ip):
            header, plain, _ = pia6.parse_packet(keys.session_key, HOST_IP, keys.network_id, pkt)
            messages = pia6.parse_messages(plain)
            for port, cm, raw in _data(messages):
                run.sent.add((port, cm["sequence_id"]))
                if drop and run.lost is None and drop(port, cm["payload"]):
                    run.lost = (port, cm["sequence_id"], raw, pkt)
                    return
                run.copies.append((port, cm["sequence_id"], raw, pkt))
            self.inbox += run.console.receive(messages)

        def wait_readable(self, seconds):
            clock.t += seconds
            self.inbox += run.console.poll()
            if run.done_at is None and goal(run.console):
                run.done_at = clock.t
            if run.done_at is not None and clock.t - run.done_at >= SETTLE:
                clock.t += SECONDS              # past the host's deadline: its loop ends

        def recv(self):
            out, self.inbox = [(p, CONSOLE_IP) for p in self.inbox], []
            return out

    monkeypatch.setattr(pla_host, "IpHostTransport", Loopback)
    monkeypatch.setattr(pla_host, "time", types.SimpleNamespace(time=clock, monotonic=clock))
    monkeypatch.setattr(joiner, "trade_box", _faithful_trade_box())
    monkeypatch.setattr(sys, "argv", [
        "pla_host.py", "--ip-host", "--our-ip", HOST_IP, "--seconds", str(SECONDS),
        "--session-update", "--sustain", "--clock", "--data-exchange", "--game-channel",
        "--trade-box", "--trade-box-ours", "--data-exchange-name", "HOST",
        "--data-exchange-id", "11223344"])
    capsys.readouterr()
    assert pla_host.main() == 0
    run.log = capsys.readouterr().out
    return run


def _host_offer():
    """-> the record the host offers under those flags, as its own `build_offer` makes it."""
    exchange = data_exchange.build_record(player_id=bytes.fromhex("11223344"), name="HOST")
    return trade_box.build_our_record(template=trade_box.REFERENCE_RECORD,
                                      **data_exchange.read_record(exchange))


class ConsoleLosesItsOffer(Console):
    """The console's offer lost on the air, and a showing of another Pokemon right behind it: two
    messages in flight, the second acknowledged first."""
    lost = False

    def _drive(self, now):
        if not self.lost and self.shown and self.host_showed and not self.offered:
            self.lost = self.offered = True
            self.answered.add(("ours", trade_box.SELECTOR_OFFERING, 0))
            self._send_box(trade_box.SELECTOR_OFFERING, 0)      # kept for its resend, not sent
            saved = self.offer
            self.offer = pla_pokemon.encrypt(gen8.fresh_identity(pla_pokemon.decrypt(saved),
                                                                 rand=os.urandom))
            showing = self._send_box(trade_box.SELECTOR_SHOWING, 0)
            self.offer = saved
            return [showing] + super()._drive(now)
        return super()._drive(now)


HOST_LOSSES = {
    "the host's confirmation 05 00":
        lambda port, pl: port == 0 and pl == bytes(8) + b"\x05\x00",
    "the host's phase 3":
        lambda port, pl: port == 0 and pl == trade_box.PHASE_KEY + b"\x02\x03",
    "the host's mirror of phase 3, sent just ahead of its phase 3":
        lambda port, pl: port == 0 and pl == trade_box.PHASE_KEY + b"\x01\x03",
    "the host's phase key open on port 1":
        lambda port, pl: port == 1 and channel_table.is_announcement(pl)
        and channel_table.parse(pl) == [(trade_box.PHASE_KEY, True)],
}


@pytest.mark.parametrize("lost", ["nothing"] + sorted(HOST_LOSSES) + ["the console's offer"])
def test_one_lost_message_and_the_trade_still_completes(monkeypatch, capsys, lost):
    """Any one of about a dozen host answers lost on the air stalled a trade with every message
    acknowledged: the host sent each once. A console message lost ahead of another was released by
    the host's acknowledgement of the later one and never resent (0x74f0ec). A host message lost
    ahead of another was skipped by the console's base walk when the second declared its own
    sequence as lowest pending. With nothing lost the host resends nothing."""
    console_class = ConsoleLosesItsOffer if lost == "the console's offer" else Console
    run = run_host(monkeypatch, capsys, console_class, lambda c: c.traded,
                   drop=HOST_LOSSES.get(lost))
    assert run.console.traded, lost
    assert run.console.received == _host_offer()
    assert sorted(run.console.delivered) == sorted(run.sent)
    assert run.log.count("trade complete, the phase key closed") == 1
    if lost == "nothing":
        assert "resend" not in run.log and "held behind" not in run.log
    elif run.lost is None:
        assert "held behind" in run.log              # the showing waited for the resent offer
    else:
        port, seq, message, packet = run.lost
        copies = [c for c in run.copies if c[:2] == (port, seq)]
        assert copies, "the lost message was never sent again"
        assert copies[0][2] == message and copies[0][3] != packet      # same sequence, new nonce
        assert f"game channel resend (port {port}, seq {seq})" in run.log


class TwoTrades(Console):
    """After a trade the console's reset `0x26d8fd0` zeroes its counters and frees the job, so the
    second trade sends 05 00, 07 00 and phases 3, 6, 11, 14 again, byte for byte, and opens the
    phase key again on port 1. The box cursor sits on the Pokemon just received, which it shows
    (docs/pla.md, The completed trade)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.trades = []

    def _advance(self):
        out = super()._advance()
        if self.traded and len(self.trades) < 2:
            self.trades.append(self.received)
            if len(self.trades) == 1:
                self.traded = False
                self.offer, self.received = self.received, None
                self.shown = self.host_showed = self.offered = self.confirmed = False
                self.host_confirmed_at, self.sent_seven = None, False
                self.phase_index, self.phase_ready_at, self.host_phase = 0, None, 0
                self.phase_closed = False
                self.answered = {a for a in self.answered if a[0] not in ("step", "ours", "box")}
                out += self._advance()
        return out


def test_a_second_trade_in_the_same_session_completes(monkeypatch, capsys):
    """The host de-duplicated on content, so the second trade's 05 00 was dropped as answered and
    the console waited on the trade screen. Its acknowledgement of the console's second phase-key
    open declared the console's sequence as lowest pending, past its own re-announcement, which
    the console's base walk then discarded."""
    run = run_host(monkeypatch, capsys, TwoTrades, lambda c: len(c.trades) == 2)
    assert run.console.trades == [_host_offer(), _host_offer()]
    assert sorted(run.console.delivered) == sorted(run.sent)
    assert run.log.count("trade step (confirming, 0500)") == 2
    assert run.log.count("trade complete, the phase key closed") == 2
    assert [run.log.count(f"trade phase {p} as the host") for p in joiner.PHASES] == [2, 2, 2, 2]


MAIN = os.path.join(ROOT, "scratchpad", "pla", "main_111.bin")      # Legends Arceus 1.1.1


@pytest.mark.skipif(not os.path.exists(MAIN), reason="needs the Legends Arceus 1.1.1 main")
@pytest.mark.parametrize("pending, ack_id, held", [
    ([4, 5], 5, ()),
    ([4, 5], 6, ()),
    ([4, 5], 4, (5,)),
    ([3, 4, 5, 6, 7, 8], 3, (5, 8)),
    ([3, 4, 5, 6, 7, 8], 5, (6, 7, 8)),
    ([1, 34, 96, 128], 1, (34, 128)),        # word 1 bit 0 and word 3 bit 30; 96 not held
])
def test_the_consoles_window_releases_what_the_mask_says(pending, ack_id, held):
    """The console's own consumer `0x74f0ec`, run on a window holding `pending` for the host, given
    the acknowledgement our host builds: it keeps exactly what `SendWindow` keeps for the same
    bytes. That pins the mask's word order both ways."""
    from nso_run import Runner, SCRATCH
    runner = Runner(MAIN)
    uc = runner.uc
    win, ent, mask_at = SCRATCH + 0x20000, SCRATCH + 0x30000, SCRATCH + 0x28000
    uc.mem_write(win, bytes(0x500))
    uc.mem_write(ent, bytes(0x5d0 * 8))
    uc.mem_write(win + 0x20, struct.pack("<Q", ent))
    uc.mem_write(win + 0x28, struct.pack("<H", 8))                    # ring capacity
    uc.mem_write(win + 0x30, struct.pack("<HH", pending[0], len(pending)))   # base, count
    for i, seq in enumerate(pending):
        uc.mem_write(ent + i * 0x5d0 + 0x24, struct.pack("<H", seq))
        uc.mem_write(ent + i * 0x5d0 + 0x28, b"\x01")               # per-station bits in use
        uc.mem_write(ent + i * 0x5d0 + 0x2c, struct.pack("<I", 1))  # pending for station 0
    mask = reliable5.build_mask(held, ack_id)
    uc.mem_write(mask_at, mask)
    runner.call(0x74f0ec, (win, 0, ack_id, mask_at), stops=(0x74f2b0,))
    theirs = [seq for i, seq in enumerate(pending)
              if struct.unpack("<I", bytes(uc.mem_read(ent + i * 0x5d0 + 0x2c, 4)))[0] & 1]
    ours = reliable5.SendWindow(0.4)
    for seq in pending:
        ours.sent("console", seq, None, 0)
    ours.acked("console", ack_id, mask)
    assert theirs == sorted(seq for _, seq in ours.pending)
