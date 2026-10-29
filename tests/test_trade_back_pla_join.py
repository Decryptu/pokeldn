"""bin/pla_join.py --trade-back against the scripted console host of tests/test_pla_joiner.py: the second trade
offers back, on the wire, the record the console sent in the first (pokeldn/trade_back.py)."""

import pytest

from pokeldn import pla
from pokeldn.ldn import channel_table
from pokeldn.pla import data_exchange, game_channel, joiner, pokemon, trade_box

import pla_join
from test_pla_joiner import OUR_IP, OUR_MAC, SSID, Clock, _console_trade, _data, _game, _msg, _open, _seat


def test_the_second_trade_returns_the_record_the_console_sent_in_the_first():
    keys, clock = pla.session_keys(SSID), Clock()
    exchange = data_exchange.build_record(player_id=bytes.fromhex("504b4c44"), name="POKELDN")
    queued = trade_box.build_our_record(**data_exchange.read_record(exchange))
    args = pla_join.build_parser().parse_args(["--offer", "unused.pa8", "--trade-back"])
    args.next_offers = []
    s = pla_join.make_session(args, keys, OUR_IP, OUR_MAC, queued, exchange, our_var=0x687E, clock=clock)
    _seat(keys, s)
    s.receive([_msg(data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x02),
                    joiner.PROTO_STREAM, port=0)])
    zero = bytes(game_channel.KEY_SIZE)
    s.receive([_game(channel_table.build([(zero, True)]), 1, 1)])
    sent = _open(keys, s.receive([_msg(game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD), 0x7C, 0)]))
    shown = trade_box.read_payload(_data(sent, 0x7C, 0)[1]["payload"])
    assert shown["selector"] == trade_box.SELECTOR_SHOWING and shown["record"] == queued
    s.receive([_msg(game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD, sequence_id=2), 0x7C, 0)])

    theirs = [pokemon.encrypt(pokemon.write(pokemon.decrypt(trade_box.REFERENCE_RECORD), level=n))
              for n in (33, 34)]
    seq = {0: 3, 1: 2}
    _console_trade(keys, clock, s, theirs[0], seq)      # asserts our offer is s.offer, the queued one

    showing = trade_box.build_message(theirs[0], sequence_id=seq[0], selector=trade_box.SELECTOR_SHOWING)
    seq[0] += 1
    back = trade_box.read_payload(_data(_open(keys, s.receive([_msg(showing, 0x7C, 0)])),
                                        0x7C, 0)[0]["payload"])
    assert back["selector"] == trade_box.SELECTOR_SHOWING and back["record"] == theirs[0]
    _console_trade(keys, clock, s, theirs[1], seq)      # our offer, byte for byte the console's first
    assert s.trades == theirs
    assert s.offer == queued                            # the third trade offers the queue again


@pytest.mark.parametrize("trade_back", [False, True])
def test_hold_after_trade_leaves_only_once_the_queue_is_done(monkeypatch, trade_back):
    """bin/pla_join.py's seat loop after one trade with the scripted host, --hold-after-trade 0.2: with
    nothing queued the leave goes within the second; --trade-back still owes the trade back, so the
    seat stays until --hold ends."""
    import socket
    import time

    import trio

    from pokeldn import ldn

    keys, clock = pla.session_keys(SSID), Clock()
    exchange = data_exchange.build_record(player_id=bytes.fromhex("504b4c44"), name="POKELDN")
    queued = trade_box.build_our_record(**data_exchange.read_record(exchange))
    args = pla_join.build_parser().parse_args(
        ["--offer", "unused.pa8", "--hold", "2", "--hold-after-trade", "0.2"]
        + ["--trade-back"] * trade_back)
    args.next_offers = []
    s = pla_join.make_session(args, keys, OUR_IP, OUR_MAC, queued, exchange, our_var=0x687E, clock=clock)
    _seat(keys, s)
    s.receive([_msg(data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x02),
                    joiner.PROTO_STREAM, port=0)])
    zero = bytes(game_channel.KEY_SIZE)
    s.receive([_game(channel_table.build([(zero, True)]), 1, 1)])
    s.receive([_msg(game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD), 0x7C, 0)])
    s.receive([_msg(game_channel.build_open(game_channel.HOST_OPEN_PAYLOAD, sequence_id=2), 0x7C, 0)])
    monkeypatch.setattr(ldn, "_done_at", None)
    _console_trade(keys, clock, s, trade_box.REFERENCE_RECORD, {0: 3, 1: 2})
    monkeypatch.setattr(pla_join, "make_session", lambda *a, **k: s)
    rows = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("127.0.0.1", 0))
    t0 = time.monotonic()
    try:
        trio.run(pla_join.run_session, args, keys, sock, "127.0.0.1", OUR_IP, OUR_MAC, queued,
                 exchange, lambda **row: rows.append(row))
    finally:
        sock.close()
    took = time.monotonic() - t0
    assert [r["note"] for r in rows if r.get("note") == "leave"]
    assert (took >= 2) == trade_back, took
