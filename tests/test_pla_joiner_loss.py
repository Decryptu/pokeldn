"""The Legends Arceus joiner against bin/pla_host.py behind a console's receive window (`0x74c250`),
one packet lost (docs/pla.md, Acknowledgement)."""
import importlib.util
import os
import sys
import types

import pytest

from pokeldn import pla
from pokeldn.ldn import pia6, reliable5
from pokeldn.pla import channel_table, data_exchange, game_channel, joiner, trade_box

ROOT = os.path.join(os.path.dirname(__file__), "..")
spec = importlib.util.spec_from_file_location("pla_host", os.path.join(ROOT, "bin", "pla_host.py"))
pla_host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pla_host)

SSID = bytes.fromhex("00112233445566778899aabbccddeeff")
HOST_IP, JOINER_IP = "169.254.1.1", "169.254.1.2"
JOINER_MAC = bytes.fromhex("0200a9fe0102")
SECONDS = 90.0                      # the host's --seconds, on the fake clock
SETTLE = 2.0                        # run on after the trade so the host reads the phase-key close
JOINER = joiner.JoinerSession


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


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


class ConsoleReceiver:
    """The hosting console's window over the joiner's 0x7c stream on each port. -> whether a
    message reaches the host; `skipped` holds each (port, seq) the base walked over unreceived."""

    def __init__(self):
        self.windows, self.skipped = {}, []

    def admit(self, port, cm):
        window = self.windows.setdefault(port, [1, set()])      # base, sequences held
        while window[0] < cm["lowest_pending"] and window[0] not in window[1]:
            self.skipped.append((port, window[0]))
            window[0] += 1
        if not cm["flags"] & reliable5.FLAG_APPLICATION_DATA:
            return True
        if cm["sequence_id"] < window[0]:
            return False
        window[1].add(cm["sequence_id"])
        while window[0] in window[1]:
            window[1].discard(window[0])
            window[0] += 1
        return True


def run(monkeypatch, capsys, drop_host=None, drop_joiner=None):
    """Run the host's main against the joiner until it has traded, plus SETTLE. `drop_host` and
    `drop_joiner` lose the first matching 0x7c data message. -> .joiner, .log, .jlog, .lost, .copies, .receiver"""
    clock = Clock()
    keys = pla.session_keys(SSID)
    exchange = data_exchange.build_record(player_id=bytes.fromhex("504b4c44"), name="PkCamp")
    offer = trade_box.build_our_record(**data_exchange.read_record(exchange))
    jlog = []
    r = types.SimpleNamespace(
        joiner=JOINER(keys, JOINER_IP, JOINER_MAC, offer, exchange, drive=True,
                      log=lambda *a: jlog.append(" ".join(map(str, a))), clock=clock),
        copies=[], lost=None, done_at=None, receiver=ConsoleReceiver())

    def lose(direction, drop, messages, pkt):
        for port, cm, raw in _data(messages):
            if drop and r.lost is None and drop(port, cm["payload"]):
                r.lost = (port, cm["sequence_id"], raw, direction)
                return True
            r.copies.append((direction, port, cm["sequence_id"], raw, pkt))
        return False

    class Loopback:
        ssid, our_ip, our_mac = SSID, HOST_IP, bytes.fromhex("0200a9fe0101")
        participants = [(0, JOINER_IP)]
        join_events = 1

        def __init__(self, **_kw):
            self.inbox = []

        def start(self):
            pass

        def stop(self):
            pass

        def send(self, pkt, ip):
            _, plain, _ = pia6.parse_packet(keys.session_key, HOST_IP, keys.network_id, pkt)
            messages = pia6.parse_messages(plain)
            if not lose("host", drop_host, messages, pkt):
                self.to_host(r.joiner.receive(messages))

        def to_host(self, packets):
            for pkt in packets:
                _, plain, _ = pia6.parse_packet(keys.session_key, JOINER_IP, keys.network_id, pkt)
                messages = pia6.parse_messages(plain)
                if lose("joiner", drop_joiner, messages, pkt):
                    continue
                if all(m.protocol != reliable5.PROTOCOL
                       or r.receiver.admit(m.port, reliable5.parse(m.payload)) for m in messages):
                    self.inbox.append(pkt)

        def wait_readable(self, seconds):
            clock.t += seconds
            self.to_host(r.joiner.poll())
            if r.done_at is None and r.joiner.traded:
                r.done_at = clock.t
            if r.done_at is not None and clock.t - r.done_at >= SETTLE:
                clock.t += SECONDS              # past the host's deadline: its loop ends

        def recv(self):
            out, self.inbox = [(p, JOINER_IP) for p in self.inbox], []
            return out

    monkeypatch.setattr(pla_host, "IpHostTransport", Loopback)
    monkeypatch.setattr(pla_host, "time", types.SimpleNamespace(time=clock, monotonic=clock))
    monkeypatch.setattr(sys, "argv", [
        "pla_host.py", "--ip-host", "--our-ip", HOST_IP, "--seconds", str(SECONDS),
        "--session-update", "--sustain", "--clock", "--data-exchange", "--game-channel",
        "--trade-box", "--trade-box-ours", "--data-exchange-name", "HOST",
        "--data-exchange-id", "11223344"])
    capsys.readouterr()
    assert pla_host.main() == 0
    r.log, r.jlog = capsys.readouterr().out, "\n".join(jlog)
    return r


def _host_offer():
    """-> the record the host offers under those flags, as its own `build_offer` makes it."""
    exchange = data_exchange.build_record(player_id=bytes.fromhex("11223344"), name="HOST")
    return trade_box.build_our_record(template=trade_box.REFERENCE_RECORD,
                                      **data_exchange.read_record(exchange))


def _nth(match, n):
    """-> a drop predicate losing the n-th message (from 0) that `match(port, payload)` is true of."""
    seen = []

    def drop(port, payload):
        if match(port, payload):
            seen.append(port)
            return len(seen) == n + 1
        return False
    return drop


ZERO = bytes(game_channel.KEY_SIZE)
SHOWING = (lambda port, pl: port == 0 and (trade_box.read_payload(pl) or {}).get("selector")
           == trade_box.SELECTOR_SHOWING)

JOINER_LOSSES = {
    "the joiner's mirror of the port-0 open, its showing right behind it":
        lambda port, pl: port == 0 and pl == ZERO + b"\x01\x00",
    "the joiner's showing back, its offer right behind it": _nth(SHOWING, 1),
    "the joiner's offer":
        lambda port, pl: port == 0 and (trade_box.read_payload(pl) or {}).get("selector")
        == trade_box.SELECTOR_OFFERING,
    "the joiner's selector 7, its phase key open right behind it":
        lambda port, pl: port == 0 and pl == ZERO + b"\x07\x00",
    "the joiner's phase 6":
        lambda port, pl: port == 0 and pl == trade_box.PHASE_KEY + b"\x01\x06",
}
HOST_LOSSES = {
    "the host's port-0 open":
        lambda port, pl: port == 0 and pl == ZERO + b"\x01\x00",
    "the host's confirmation 05 00":
        lambda port, pl: port == 0 and pl == ZERO + b"\x05\x00",
    "the host's mirror of phase 3, its phase 3 right behind it":
        lambda port, pl: port == 0 and pl == trade_box.PHASE_KEY + b"\x01\x03",
    "the host's phase 3":
        lambda port, pl: port == 0 and pl == trade_box.PHASE_KEY + b"\x02\x03",
    "the host's phase key open on port 1":
        lambda port, pl: port == 1 and channel_table.is_announcement(pl)
        and channel_table.parse(pl) == [(trade_box.PHASE_KEY, True)],
}


@pytest.mark.parametrize("lost", ["nothing"] + sorted(JOINER_LOSSES) + sorted(HOST_LOSSES))
def test_one_lost_message_and_the_trade_still_completes(monkeypatch, capsys, lost):
    """A joiner acknowledging a sequence plus one lets a console's base walk over unseen messages; a
    lost message is resent."""
    r = run(monkeypatch, capsys, drop_host=HOST_LOSSES.get(lost),
            drop_joiner=JOINER_LOSSES.get(lost))
    assert r.receiver.skipped == [], lost
    assert r.joiner.traded, lost
    assert r.joiner.received == _host_offer()
    assert r.log.count("trade complete, the phase key closed") == 1
    if lost == "nothing":
        assert r.lost is None
        assert "resend" not in r.log and "resend" not in r.jlog and "held behind" not in r.jlog
        return
    port, seq, message, direction = r.lost
    copies = [c for c in r.copies if c[:3] == (direction, port, seq)]
    assert copies, "the lost message was never sent again"
    assert copies[0][3] == message                                  # same sequence, same bytes
    log = r.jlog if direction == "joiner" else r.log
    assert f"game channel resend (port {port}, seq {seq})" in log
