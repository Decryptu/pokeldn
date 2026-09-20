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
