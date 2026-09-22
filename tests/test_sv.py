"""Scarlet / Violet: the advertisement and the reliable acks, pinned to the retail bytes.

Every expected value here was read off a retail Scarlet 4.0.0: `sv01` (three scans of a console
searching alone) and `sv02` (a passive capture of the two consoles' own trade).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import sv
from pokeldn.ldn import pia6, reliable5

# The application data a searching console advertises, and the same beacon once a second console
# has joined it: the two differ in the number-of-players byte alone.
SV01_APP_DATA = bytes.fromhex(
    "005c150015000000000000000000000000000000000101000000010120000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000")
SV02_APP_DATA = bytes.fromhex(
    "005c150015000000000000000000000000000000000102000000010120000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000")
# The joiner's bulk ack on 0x81 port 1 in sv02, and the host's on the same port, whole
# messages, both with the ack payload's first byte zero (it is 0 or 1 across the capture).
SV02_JOINER_ACK_81_1 = bytes.fromhex(
    "00000056ffff002f030000000100040000020002000000000000000000000000"
    "0000000000000100010000000000000000000000000000000000000100010000"
    "0000000000000000000000000000000001000100000000000000000000000000"
    "000000")
SV02_HOST_ACK_81_1 = bytes.fromhex(
    "00000056ffff0002030000000200040000010001000000000000000000000000"
    "0000000000002f002f0000000000000000000000000000000000000100010000"
    "0000000000000000000000000000000001000100000000000000000000000000"
    "000000")


def test_the_advertisement_reproduces_a_searching_console():
    assert sv.build_advertise_data() == SV01_APP_DATA


def test_the_advertisement_reproduces_a_full_session():
    assert sv.build_advertise_data(num_players=2) == SV02_APP_DATA


def test_the_advertisement_is_132_bytes_and_parses_back():
    out = sv.parse_advertise_data(SV01_APP_DATA)
    assert len(SV01_APP_DATA) == 132
    assert out["sys_comm_ver"] == sv.SYS_COMM_VERSION
    assert out["app_comm_ver"] == sv.APP_COMM_VERSION
    assert out["num_players"] == 1
    assert out["nickname"] == sv.ADVERTISE_NAME
    assert out["game_data"] == bytes(sv.GAME_DATA_SIZE)


def test_the_game_data_must_be_its_measured_width():
    with pytest.raises(ValueError):
        sv.build_advertise_data(game_data=b"\x00" * 8)


def test_the_title_constants_are_the_ones_in_the_binary():
    assert sv.GAME_KEY == b"p1frXqxmeCZWFv0X"
    assert sv.PASSPHRASE.startswith(b"W3GoSMEn7RIIUQ89rzqBHGhG")
    assert len(sv.PASSPHRASE) == 64
    assert sv.COMM_ID_SCARLET == 0x0100A3D008C5C000
    assert sv.COMM_ID_VIOLET == 0x01008F6008C5E000
    assert (sv.PIA_VERSION, sv.PIA_HEADER_SIZE, sv.PIA_TAG_SIZE) == (11, 0x1C, 8)
    assert sv.PLATFORM == 1


def test_the_session_key_comes_from_the_ssid_alone():
    ssid = bytes.fromhex("64229bbb0edfffda60a00f08ceb3d8aa")
    keys = sv.session_keys(ssid)
    assert keys.session_key == pia6.ldn_session_key(sv.GAME_KEY, ssid)
    assert keys.network_id == pia6.ldn_network_id(ssid)


def _ack_fields(message):
    parsed = reliable5.parse(message)
    return parsed, reliable5.parse_ack_payload(parsed["payload"])


def test_the_retail_acks_put_each_station_ack_at_its_own_index():
    """entry[k] acknowledges station k's stream: the joiner fills entry 0, the host entry 1."""
    joiner, jack = _ack_fields(SV02_JOINER_ACK_81_1)
    host, hack = _ack_fields(SV02_HOST_ACK_81_1)
    assert joiner["is_ack"] and host["is_ack"]
    assert jack["count"] == hack["count"] == 4
    assert [e["ack_id"] for e in jack["entries"]] == [2, 1, 1, 1]
    assert [e["ack_id"] for e in hack["entries"]] == [1, 47, 1, 1]
    assert all(e["stream_id"] == 0 for e in jack["entries"] + hack["entries"])
    assert joiner["destination_bits"] == host["destination_bits"] == 3
    assert joiner["bitmap"] == [1] and host["bitmap"] == [2]


def test_the_joiner_ack_reproduces_the_retail_message():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "bin"))
    import sv_join
    assert sv_join.build_bulk_ack(1, 0x2F) == SV02_JOINER_ACK_81_1


def test_the_host_ack_reproduces_the_retail_message():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "bin"))
    import sv_host
    assert sv_host.build_bulk_ack({1: 46}, 2) == SV02_HOST_ACK_81_1


def test_the_streams_module_reproduces_the_retail_opening():
    """Every byte here is a message from the retail pair's first second (sv11)."""
    from pokeldn.sv import streams
    entry = "00" + "0001" + "0001" + "00" * 16
    assert streams.build_ack({}, 1, streams.JOINER_INDEX, unknown0=1).hex() == (
        "00000056ffff00010300000001" + "01" + "04" + entry * 4)
    assert streams.build_ack({}, 1, streams.HOST_INDEX, unknown0=1).hex() == (
        "00000056ffff00010300000002" + "01" + "04" + entry * 4)
    assert streams.build_open(0, streams.JOINER_INDEX).hex() == \
        "0f00000b0001000103000000010000000000f38800000000"
    assert streams.build_open(4, streams.JOINER_INDEX).hex() == \
        "0f00000b000100010300000001000400000ff00800000000"
    assert streams.build_open(1, streams.HOST_INDEX).hex() == \
        "0f00000b0001000103000000020000000000f38800000000"
    assert streams.build_open(5, streams.HOST_INDEX).hex() == \
        "0f00000b000100010300000002000500000ff00800000000"


def test_the_eleven_streams_are_the_ones_both_stations_acknowledge():
    from pokeldn.sv import streams
    assert streams.every_stream() == [(0x80, 0), (0x80, 1), (0x80, 2)] + \
        [(0x81, p) for p in range(8)]
    assert streams.bitmap_for(streams.HOST_INDEX) == 0x02
    assert streams.bitmap_for(streams.JOINER_INDEX) == 0x01


def test_a_record_is_zlib_with_a_four_kilobyte_window():
    """A retail record off the wire, and the framing reproduces its own round trip."""
    from pokeldn.sv import streams
    rec = bytes.fromhex("484b6262b0640003d60c8651300a46c1281805340500000000ffff0300946900a9")
    plain = streams.decompress(rec)
    assert len(plain) == 1395
    assert plain[:8].hex() == "0200390000000000"
    assert streams.compress(plain).startswith(streams.ZLIB_HEADER)
    assert streams.decompress(streams.compress(plain)) == plain


def test_the_rtt_pair_is_the_one_both_consoles_send():
    from pokeldn.sv import streams
    request = bytes.fromhex("000000002c0c6d4d700000")
    assert streams.build_rtt_request(bytes.fromhex("0000002c0c6d4d70")) == request
    assert streams.build_rtt_response(request, 0x28A3).hex() == "010000002c0c6d4d7028a3"


# Port 2 of the game's own protocols, from the emulated pair that traded (docs/sv.md, Port 2).
PAIR_HOST_CONSTANT_ID = bytes.fromhex("7f00020000020000")
PAIR_ANNOUNCE_WIRE = bytes.fromhex("484b62dfc9b89375271b2313c31e4e0618d8d3d0c030f06027633303031308d5"
                                   "3300000000ffff0300f5c30683")
PAIR_JOIN = bytes.fromhex("03b90200bc09000000000000000000")
PAIR_ACCEPT = bytes.fromhex("09b9030000b90183000002000002007f")


def test_the_station_id_is_the_constant_id_read_big_endian():
    from pokeldn.ldn.pia_connect import ldn_constant_id
    from pokeldn.sv import port2
    assert ldn_constant_id(bytes.fromhex("02007f000002")) == PAIR_HOST_CONSTANT_ID
    assert port2.station_id(PAIR_HOST_CONSTANT_ID) == 0x7F00020000020000


def test_the_announcement_reproduces_the_pair_host_inflated():
    import zlib
    from pokeldn.sv import port2
    body = port2.build_announce(port2.station_id(PAIR_HOST_CONSTANT_ID))
    assert body == zlib.decompress(PAIR_ANNOUNCE_WIRE)
    assert zlib.decompress(port2.deflate_announce(body)) == body


def test_the_join_parses_and_the_accept_reproduces_the_pair_host():
    from pokeldn.sv import port2
    assert port2.parse_join(PAIR_JOIN) == 0
    assert port2.parse_join(PAIR_JOIN[:-1]) is None
    assert port2.parse_join(b"\x0d\xb9\x01\x01") is None
    assert port2.build_accept(port2.station_id(PAIR_HOST_CONSTANT_ID)) == PAIR_ACCEPT


def test_the_trade_stage_follows_the_pair_host_message_for_message():
    """The emulated pair's 0x7C exchange from the key-0x80 open to the close of key 0x0180, both
    directions, drives the host's state machine: fed the joiner's messages in order it must send
    the host's, in order, byte for byte."""
    from pokeldn.sv import trade
    path = os.path.join(os.path.dirname(__file__), "data", "sv_pair_trade.txt")
    rows = [line.split() for line in open(path) if line.strip()]
    rows = rows[2:]                                   # the key-0x80 opens belong to the seat
    host_offer = bytes.fromhex(rows[0][2])[4:]
    assert rows[0][0] == "TX" and len(host_offer) == trade.OFFER_SIZE
    stage = trade.TradeStage(host_offer)
    sent = []
    for direction, port, hx in rows:
        if direction != "RX":
            continue
        for _delay, out_port, payload in stage.on_message(int(port), bytes.fromhex(hx)):
            sent.append((out_port, payload.hex()))
    expected = [(int(port), hx) for direction, port, hx in rows if direction == "TX"]
    assert sent == expected
    assert stage.done
    assert stage.joiner_offer == host_offer         # the pair traded a clone for itself


def test_the_trade_stage_ignores_what_is_not_the_next_step():
    from pokeldn.sv import trade
    stage = trade.TradeStage(bytes(trade.OFFER_SIZE))
    assert stage.on_message(1, bytes.fromhex("b90101b902b90280800001")) == []
    assert stage.on_message(0, bytes.fromhex("80010103")) == []      # no commit yet
    assert stage.on_message(0, bytes.fromhex("80000200") + bytes(10)) == []
    out = stage.on_message(0, bytes.fromhex("80000200") + bytes(trade.OFFER_SIZE))
    assert [(p, d[:4].hex()) for _, p, d in out] == [(0, "80000200"), (0, "80000300")]
    assert stage.on_message(0, bytes.fromhex("80000200") + bytes(trade.OFFER_SIZE)) == []
    assert trade.table_update(trade.KEY_EXCHANGE, True).hex() == "b90101b902b90280800101"
    assert trade.table_update(trade.KEY_TRADE, True).hex() == "b90101b902b90280800001"


def test_a_host_that_offers_first_still_confirms_on_the_joiner_offer():
    from pokeldn.sv import trade
    stage = trade.TradeStage(bytes(trade.OFFER_SIZE))
    first = stage.offer_first()
    assert [(p, d[:4].hex()) for _, p, d in first] == [(0, "80000200")]
    assert stage.offer_first() == []
    out = stage.on_message(0, bytes.fromhex("80000200") + bytes(trade.OFFER_SIZE))
    assert [(p, d.hex()) for _, p, d in out] == [(0, "80000300")]


def test_the_joiner_stage_follows_the_pair_joiner_message_for_message():
    """The same exchange from the other side: fed the host's messages in order, the joiner's state
    machine must send the pair joiner's, in order, byte for byte, from its own key-0x80 open to
    its mirror of the close of key 0x0180."""
    from pokeldn.sv import trade
    path = os.path.join(os.path.dirname(__file__), "data", "sv_pair_trade.txt")
    rows = [line.split() for line in open(path) if line.strip()]
    joiner_offer = bytes.fromhex(rows[3][2])[4:]
    assert rows[3][0] == "RX" and len(joiner_offer) == trade.OFFER_SIZE
    stage = trade.JoinerTradeStage(joiner_offer)
    sent = []
    for direction, port, hx in rows:
        if direction != "TX":
            continue
        for _delay, out_port, payload in stage.on_message(int(port), bytes.fromhex(hx)):
            sent.append((out_port, payload.hex()))
    assert sent == [(int(port), hx) for direction, port, hx in rows if direction == "RX"]
    assert stage.done
    assert stage.host_offer == joiner_offer


def test_the_joiner_stage_answers_nothing_before_the_host_opens_the_key():
    from pokeldn.sv import trade
    stage = trade.JoinerTradeStage(bytes(trade.OFFER_SIZE))
    assert stage.on_message(0, bytes.fromhex("80010103")) == []
    assert stage.on_message(1, trade.table_update(trade.KEY_EXCHANGE, True)) == []
    assert [p for _, p, _ in stage.on_message(1, trade.table_update(trade.KEY_TRADE, True))] == [1]
    assert stage.on_message(1, trade.table_update(trade.KEY_TRADE, True)) == []
    out = stage.on_message(0, bytes.fromhex("80000200") + bytes(trade.OFFER_SIZE))
    assert [(p, d[:4].hex()) for _, p, d in out] == [(0, "80000200")]
    out = stage.on_message(0, bytes.fromhex("80000300"))
    assert [(p, d.hex()) for _, p, d in out] == [(0, "80000300"), (0, "80000500")]


def test_a_joiner_that_offers_first_does_not_offer_twice():
    from pokeldn.sv import trade
    stage = trade.JoinerTradeStage(bytes(trade.OFFER_SIZE))
    assert [(p, d[:4].hex()) for _, p, d in stage.offer_first()] == [(0, "80000200")]
    assert stage.offer_first() == []
    assert stage.on_message(0, bytes.fromhex("80000200") + bytes(trade.OFFER_SIZE)) == []
    assert stage.host_offer == bytes(trade.OFFER_SIZE)


def test_a_cancelled_trade_stops_the_joiner_stage():
    from pokeldn.sv import trade
    stage = trade.JoinerTradeStage(bytes(trade.OFFER_SIZE))
    stage.on_message(1, trade.table_update(trade.KEY_TRADE, True))
    assert stage.on_message(0, bytes.fromhex("8000040100")) == []
    assert stage.done
    assert stage.on_message(0, bytes.fromhex("80000200") + bytes(trade.OFFER_SIZE)) == []
