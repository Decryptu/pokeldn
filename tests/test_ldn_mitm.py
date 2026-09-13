"""The ldn_mitm discovery and join protocol, pinned to bytes captured from a real emulated join.

The vectors are the Connect a joining instance sent and the wire lengths the three payloads of that
exchange compressed to.
"""

from pokeldn.ldn import ldn_mitm

# what a joining instance sent as its Connect body: ip 127.0.0.3, mac 02:00:7f:00:00:03, "RyuPlayer"
CONNECT_BODY = bytes.fromhex(
    "0300007f02007f0000030001527975506c617965720000000000000000000000") + bytes(0x20)


def test_the_connect_body_is_built_the_way_an_instance_sends_it():
    assert ldn_mitm.build_node_info("127.0.0.3", bytes.fromhex("02007f000003")) == CONNECT_BODY


def test_the_measured_wire_lengths():
    """A 0x40-byte Connect went out as 37 bytes on the wire, header included."""
    assert len(ldn_mitm.compress(CONNECT_BODY)) + ldn_mitm.HEADER_SIZE == 37


def test_a_zero_run_costs_two_bytes_and_round_trips():
    for blob in (b"", b"\0", b"\0" * 256, b"\0" * 257, b"\x01\0\0\x02", bytes(range(256)),
                 CONNECT_BODY):
        assert ldn_mitm.decompress(ldn_mitm.compress(blob)) == blob


def test_a_run_longer_than_256_is_split():
    assert ldn_mitm.compress(b"\0" * 300) == bytes((0, 255, 0, 43))


def test_a_datagram_round_trips_through_the_header():
    pkt = ldn_mitm.build(ldn_mitm.CONNECT, CONNECT_BODY)
    assert len(pkt) == 37
    assert ldn_mitm.parse(pkt) == (ldn_mitm.CONNECT, CONNECT_BODY)


def test_a_scan_carries_no_payload():
    pkt = ldn_mitm.build(ldn_mitm.SCAN)
    assert len(pkt) == ldn_mitm.HEADER_SIZE
    assert ldn_mitm.parse(pkt) == (ldn_mitm.SCAN, b"")


def test_a_foreign_magic_is_refused():
    import pytest
    with pytest.raises(ValueError):
        ldn_mitm.parse(b"\0" * 16)


def test_the_advertise_data_is_read_at_the_declared_size():
    """A NetworkInfo declares its advertise size at +0x26a and the session key derives from the
    bytes at +0x26c."""
    import struct
    ni = bytearray(ldn_mitm.NETWORK_INFO_SIZE)
    ni[ldn_mitm.OFF_HOST_MAC:ldn_mitm.OFF_HOST_MAC + 6] = bytes.fromhex("02007f000002")
    struct.pack_into("<H", ni, ldn_mitm.OFF_ADVERTISE_SIZE, 24)
    ni[ldn_mitm.OFF_ADVERTISE_DATA:ldn_mitm.OFF_ADVERTISE_DATA + 24] = bytes(range(24))
    assert ldn_mitm.advertise_data(bytes(ni)) == bytes(range(24))
    assert ldn_mitm.host_mac(bytes(ni)) == bytes.fromhex("02007f000002")
