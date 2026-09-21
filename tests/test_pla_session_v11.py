"""Byte-exact regressions for the Pia 6.16-6.30 (version 11) Session join reply.

The request is the 115 bytes a retail Legends Arceus sent to a hosted network. The expected ack and
response bytes are what the console's own type-1 (0x737534) and type-2 (0x7379c0) parsers require,
read from the binary.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.ldn import pia_connect as pc


JOIN_REQUEST = bytes.fromhex(
    "000a2c0058036801740077007c02800381039800a40093b59570ac5601100002000000003dbe0000000000000000000000000000000000000000000000000000000000000000000000ac1056013039ac56801000020000000000c6010100000000000000010000000000000000000000010120")


def test_parse_recovers_ids_and_station():
    j = pc.parse_session_join_v11(JOIN_REQUEST)
    assert j is not None
    assert j["source_constant_id"].hex() == "ac56011000020000"   # the console
    assert j["source_var"] == 0x3dbe
    assert j["destination_constant_id"].hex() == "ac56801000020000"  # the host, as the console recorded it
    assert j["destination_var"] == 0x00c6
    assert j["ip"] == "172.16.86.1"
    assert j["port"] == 12345
    assert dict(j["protocols"])[0x98] == 0                       # Session version stated


def test_ack_matches_console_parser():
    j = pc.parse_session_join_v11(JOIN_REQUEST)
    ack = pc.build_session_join_ack_v11(
        j["destination_constant_id"], j["destination_var"],
        j["source_constant_id"], j["source_var"])
    assert len(ack) == 25
    assert ack.hex() == (
        "01"
        "ac56801000020000" "0000" "00c6"
        "ac56011000020000" "0000" "3dbe")


def test_response_matches_console_writer():
    j = pc.parse_session_join_v11(JOIN_REQUEST)
    resp = pc.build_session_join_response_v11(
        j["destination_constant_id"], j["destination_var"],
        j["source_constant_id"], j["source_var"],
        version=dict(j["protocols"])[0x98], sequence_id=1)
    assert len(resp) == 43
    assert resp.hex() == (
        "0298" "00" "01"                    # type, protocol, version, status 1 (accept)
        "0000000000000000"                  # random, unread on the accept path
        "ac56801000020000" "0000" "00c6"    # host location id
        "ac56011000020000" "0000" "3dbe"    # console location id
        "00" "01" "01"                      # route A/B, station index (first joiner)
        "0001"                              # join order
        "0001")                             # sequence id the update must reach


def test_response_status_and_sequence_are_settable():
    resp = pc.build_session_join_response_v11(
        bytes.fromhex("ac56801000020000"), 0x00c6,
        bytes.fromhex("ac56011000020000"), 0x3dbe,
        status=1, sequence_id=0x1234)
    assert resp[3] == 1
    assert resp[-2:] == b"\x12\x34"


def test_parse_rejects_truncated():
    assert pc.parse_session_join_v11(JOIN_REQUEST[:40]) is None
    assert pc.parse_session_join_v11(b"\x01\x00") is None       # wrong type


def test_update_header_offsets():
    host_const = bytes.fromhex("ac56801000020000")
    player = dict(player_id=pc.DEFAULT_PLAYER_ID, name=" ")
    stations = [
        dict(constant_id=host_const, variable_id=0x00c6, ip="172.16.86.128", port=12345,
             station_index=0, route=(0, 0), join_order=0, token=b"\x00" * 32, players=[player]),
        dict(constant_id=bytes.fromhex("ac56011000020000"), variable_id=0xc52b,
             ip="172.16.86.1", port=12345, station_index=1, route=(0, 1), join_order=1,
             token=b"\x00" * 32, players=[player]),
    ]
    u = pc.build_session_update_v11(host_const, 0x00c6, stations, sequence_id=1)
    # Seven-byte fragment header: type, sequence, count 1, index 0, offset 3.
    assert u[:7].hex() == "05000101000003"
    # Reassemble the way 0x7404a8 does: seed the buffer with the first three bytes, copy the
    # fragment payload at the offset, then check the 0x73897c layout.
    offset = int.from_bytes(u[5:7], "big")
    buf = bytearray(3 + len(u[7:]))
    buf[0:3] = u[0:3]
    buf[offset:] = u[7:]
    b = bytes(buf)
    assert b[0] == 5 and b[1:3] == b"\x00\x01"          # reassembly byte, sequence
    assert b[3:11] == host_const                        # host constant id
    assert b[0x0b:0x0f] == bytes.fromhex("000000c6")    # host var as [0000 | var] u32
    assert b[0x0f] == 2                                  # station count
    assert b[0x10:0x14] == b"\x00\x00\x00\x00"          # IPv6 bitmap, all IPv4
    # First station entry (host), the 0x739050 IPv4 layout.
    e = b[0x14:]
    assert e[0:8] == host_const
    assert e[8:12] == bytes.fromhex("000000c6")         # [0000 | var]
    assert e[12:16] == bytes([172, 16, 86, 128])        # IPv4
    assert e[16:18] == (12345).to_bytes(2, "big")       # port
    assert e[18:21] == bytes([0, 0, 0])                 # route A, route B, index
    assert e[21:23] == b"\x00\x00"                      # join order
    assert e[23:25] == b"\x00\x00"                      # nat mapping, private-IPv6 flag
    assert e[25:57] == b"\x00" * 32                      # token
    assert e[57] == 1 and e[58] == 1                     # player count, participant count
    # 6.32-style player record: id 16, length u32 BE, encoding, name.
    assert e[59:75] == pc.DEFAULT_PLAYER_ID
    assert e[75:79] == (1).to_bytes(4, "big") and e[79] == 1 and e[80:81] == b" "


# Four of a console's own type-3 leave requests, two per session, off the ph44 capture. The random
# field is the only part that moves, including between retransmissions of one leave.
CONSOLE_LEAVES = (
    "031ea65baaac560110000200000000e76700ac1056013039",
    "0307961814ac560110000200000000e76700ac1056013039",
    "03f48f035aac560110000200000000270f00ac1056013039",
    "0317829b90ac560110000200000000270f00ac1056013039",
)


def test_the_leave_request_is_the_consoles_own_bytes():
    """A station saying it is going: type, a random word, its location id, a reason byte, its
    address. `docs/pla.md`, Leaving."""
    for hexed in CONSOLE_LEAVES:
        raw = bytes.fromhex(hexed)
        var = int.from_bytes(raw[15:17], "big")
        built = pc.build_session_leave_v11(raw[5:13], var, "172.16.86.1", 12345,
                                           random4=raw[1:5])
        assert built.hex() == hexed
    assert len(bytes.fromhex(CONSOLE_LEAVES[0])) == 24


def test_the_leave_carries_the_senders_own_location_and_address():
    """The host's leave is the same message with its own ids, which is the only way it can be
    read: the captures have no host-side leave in them."""
    built = pc.build_session_leave_v11(bytes.fromhex("ac56801000020000"), 0x00C6,
                                       "172.16.86.128", 12345, random4=b"\x01\x02\x03\x04")
    assert built[0] == pc.SESSION_LEAVE_REQUEST == 3
    assert built[1:5] == b"\x01\x02\x03\x04"
    assert built[5:17].hex() == "ac56801000020000000000c6"
    assert built[17] == 0                                   # the reason, 0 on all four captured
    assert built[18:22] == bytes([172, 16, 86, 128])
    assert built[22:24] == (12345).to_bytes(2, "big")
    assert len(built) == 24


def test_builder_reproduces_the_retail_request():
    """`pia6.build_session_join` writes the retail request byte for byte from its fields: the ten
    (id, version) pairs, the four-byte nonce, both location ids, the seven-byte station address
    and the one player record. Scarlet's own writer 0x6d5464 lays it out the same way."""
    from pokeldn.ldn import pia6

    j = pc.parse_session_join_v11(JOIN_REQUEST)
    built = pia6.build_session_join(
        j["source_constant_id"], j["source_var"], j["ip"],
        j["destination_constant_id"], j["destination_var"], " ", j["app4"])
    assert built == JOIN_REQUEST
    assert len(built) == 115
    assert j["protocols"] == pia6.BAND_PROTOCOLS


def test_joiner_side_parsers_round_trip_the_host_builders():
    j = pc.parse_session_join_v11(JOIN_REQUEST)
    resp = pc.build_session_join_response_v11(
        j["destination_constant_id"], j["destination_var"],
        j["source_constant_id"], j["source_var"], sequence_id=7)
    r = pc.parse_session_join_response_v11(resp)
    assert r["status"] == 1 and r["status_name"] == "accepted"
    assert r["host_var"] == 0x00c6 and r["console_var"] == 0x3dbe
    assert r["station_index"] == 1 and r["route"] == (0, 1) and r["sequence_id"] == 7

    update = pc.build_session_update_v11(
        j["destination_constant_id"], j["destination_var"], [
            dict(constant_id=j["destination_constant_id"], variable_id=j["destination_var"],
                 ip="172.16.86.2", port=12345, station_index=0,
                 players=[{"player_id": bytes(15) + b"\x01", "name": b" "}]),
            dict(constant_id=j["source_constant_id"], variable_id=j["source_var"],
                 ip=j["ip"], port=j["port"], station_index=1, route=(0, 1), join_order=1,
                 players=[{"player_id": bytes(7) + b"\x01" + bytes(8), "name": b" "}]),
        ], sequence_id=7)
    u = pc.parse_session_update_v11(update)
    assert u["sequence_id"] == 7 and "truncated" not in u
    assert [st["ip"] for st in u["stations"]] == ["172.16.86.2", "172.16.86.1"]
    assert u["stations"][1]["variable_id"] == 0x3dbe
    assert u["stations"][1]["players"][0]["name"] == b" "

    ack = pc.build_session_update_ack_v11(j["source_constant_id"], 7)
    assert ack.hex() == "06" "ac56011000020000" "0000" "0007"
