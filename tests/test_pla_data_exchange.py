"""The 0x81 data exchange, against the bytes two reference stations sent.

Every constant here is a capture of a Ryujinx pair that reached the trade screen: the host's content
message, its acknowledgement, and the stream open both stations send. `docs/pla.md`, The data
exchange.
"""

import zlib

import pytest

from pokeldn.ldn import reliable5
from pokeldn.pla import data_exchange

# The host's content message on 0x81 port 0, whole, and the joiner's on port 1. They differ only in
# the destination bitmap: the payload behind them is byte for byte the same.
HOST_CONTENT = bytes.fromhex(
    "1f00003d000100010100000002484b626448618080060634d03ef7339b3e0303138cefc650c4900"
    "a84c10c190cd960760e4326548e155d3310306211c30700000000ffff0300ea23078e")
JOINER_CONTENT = bytes.fromhex(
    "1f00003d000100010100000001484b626448618080060634d03ef7339b3e0303138cefc650c4900"
    "a84c10c190cd960760e4326548e155d3310306211c30700000000ffff0300ea23078e")
HOST_ACK = bytes.fromhex(
    "0000002cffff00010100000002000200000100010000000000000000000000000000000000000200"
    "0100000000000000000000000000000000")
STREAM_OPEN = bytes.fromhex("0f00000b0001000101000000010000000000008000000000")


def test_content_message_is_the_reference_byte_for_byte():
    built = data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x02)
    assert built == HOST_CONTENT


def test_the_two_directions_differ_only_in_the_destination_bitmap():
    assert data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x01) \
        == JOINER_CONTENT
    assert reliable5.parse(HOST_CONTENT)["payload"] == reliable5.parse(JOINER_CONTENT)["payload"]


def test_the_acknowledgement_is_the_reference_byte_for_byte():
    assert data_exchange.build_ack_message([1, 2], 0x02) == HOST_ACK


def test_the_stream_open_is_the_reference_byte_for_byte():
    assert data_exchange.build_stream_open(0x01) == STREAM_OPEN


def test_the_record_round_trips_through_the_games_zlib_framing():
    payload = reliable5.parse(HOST_CONTENT)["payload"]
    record = data_exchange.decompress(payload)
    assert len(record) == data_exchange.RECORD_SIZE
    assert data_exchange.compress(record) == payload


def test_the_reference_record_carries_the_player_the_game_shows():
    assert data_exchange.read_record(data_exchange.REFERENCE_RECORD) == dict(
        player_id=bytes.fromhex("879df306"), name="FreeShkreli")


def test_a_built_record_carries_the_name_and_id_written_into_it():
    record = data_exchange.build_record(player_id=bytes.fromhex("01020304"), name="POKELDN")
    assert len(record) == data_exchange.RECORD_SIZE
    assert data_exchange.read_record(record) == dict(
        player_id=bytes.fromhex("01020304"), name="POKELDN")
    # Every byte outside the two fields is the reference's.
    for offset in range(data_exchange.RECORD_SIZE):
        in_id = (data_exchange.PLAYER_ID_OFFSET
                 <= offset < data_exchange.PLAYER_ID_OFFSET + data_exchange.PLAYER_ID_SIZE)
        in_name = (data_exchange.NAME_OFFSET
                   <= offset < data_exchange.NAME_OFFSET + data_exchange.NAME_SIZE)
        if not in_id and not in_name:
            assert record[offset] == data_exchange.REFERENCE_RECORD[offset], hex(offset)


def test_a_name_past_the_field_is_refused_rather_than_written_into_the_next():
    with pytest.raises(ValueError):
        data_exchange.build_record(name="X" * (data_exchange.NAME_SIZE // 2 + 1))


def test_the_content_message_declares_one_destination_bit_and_the_zlib_flag():
    message = reliable5.parse(data_exchange.build_content_message(
        data_exchange.REFERENCE_RECORD, 0x02))
    assert message["flags"] & reliable5.FLAG_ZLIB
    assert message["destination_bits"] == 1
    assert message["bitmap"] == [0x02]
    assert message["sequence_id"] == data_exchange.SEQUENCE_ID


def test_the_framing_is_not_a_plain_zlib_compress():
    # The game sync-flushes before it finishes, so the trailer carries an empty stored block. A
    # record built with `zlib.compress` is a different length and would not reproduce a capture.
    record = data_exchange.REFERENCE_RECORD
    assert data_exchange.compress(record) != zlib.compress(record)
    assert zlib.decompress(data_exchange.compress(record)) == record


def test_the_stream_and_rtt_are_addressed_to_the_mesh_and_the_rest_to_the_station():
    """Both reference stations put the mesh destination in the header for 0x58 and 0x81 and name the
    recipient in the plaintext footer; the session, clock and reliable protocols carry the peer's
    variable id in the header with no footer. A 0x81 message addressed the second way never reaches
    the game's stream."""
    import pla_host
    from pokeldn.ldn import pia6
    from pokeldn.pla import session as pla_session

    keys = pla_session.session_keys(bytes(range(16)))
    console_var = 0x44E6

    for protocol in (pla_host.PROTO_RTT, pla_host.PROTO_BROADCAST_RELIABLE):
        packet = pla_host.build_reply(keys, "172.16.86.128", b"\x00", console_var, b"\1" * 8,
                                      protocol=protocol)
        header = pia6.PiaHeader6.parse(packet)
        assert header.dst_var == pla_host.MESH_DESTINATION, hex(protocol)
        assert pia6.footer(packet, header.footer_size) == [console_var], hex(protocol)

    for protocol in (pla_host.PROTO_SESSION, pla_host.PROTO_CLONE_CLOCK, 0x7C):
        packet = pla_host.build_reply(keys, "172.16.86.128", b"\x00", console_var, b"\1" * 8,
                                      protocol=protocol)
        header = pia6.PiaHeader6.parse(packet)
        assert header.dst_var == console_var, hex(protocol)
        assert header.footer_size == 0, hex(protocol)


# The whole packet a reference host sends when it answers the console's stream open: the record on
# port 0 and the host's own stream open on port 1, in one packet.
REFERENCE_BUNDLE_PLAINTEXT = bytes.fromhex(
    "7f00004a8100000000000000000000001f00003d000100010100000002484b6264486180800606"
    "34d03ef7339b3e0303138cefc650c4900a84c10c190cd960760e4326548e155d3310306211c307"
    "00000000ffff0300ea23078e060018810000010f00000b000100010100000002000000000000800"
    "0000000ffffffffffffff")


def test_the_host_packet_is_the_reference_bundle_byte_for_byte():
    import pla_host
    from pokeldn.ldn import pia6

    content = data_exchange.build_content_message(data_exchange.REFERENCE_RECORD, 0x02)
    opened = data_exchange.build_stream_open(0x02)
    plaintext = pia6.pad_payload(
        pia6.build_message(content, protocol=data_exchange.PROTOCOL,
                           port=data_exchange.HOST_PORT, message_flags=0)
        + pia6.build_message(opened, protocol=data_exchange.PROTOCOL,
                             port=data_exchange.JOINER_PORT, message_flags=0, inherit="port"))
    assert plaintext == REFERENCE_BUNDLE_PLAINTEXT
    assert pla_host.JOINER_BITMAP == 0x02


def test_the_bundle_reads_back_as_two_messages_on_two_ports():
    from pokeldn.ldn import pia6

    messages = pia6.parse_messages(REFERENCE_BUNDLE_PLAINTEXT)
    assert [(m.protocol, m.port, len(m.payload)) for m in messages] == [(0x81, 0, 74), (0x81, 1, 24)]
