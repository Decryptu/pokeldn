"""The ldn_mitm host side: what an emulated console reads out of our scan answer, and what a join
does to the network. Both ends are ours, so the two modules check each other."""

import socket
import time

import pytest

from pokeldn.ldn import ldn_mitm, ldn_mitm_host

COMM_ID = 0x01006fa0233f8000
HOST_IP = "127.0.0.1"
PEER_IP = "127.0.0.2"
# Not the real ports: a live host on this machine holds those, and a test must not need them free.
DISCOVERY_PORT = 21452
PIA_PORT = 22345


def _info(**kw):
    args = dict(local_comm_id=COMM_ID, scene_id=22287, host_ip=HOST_IP,
                host_mac=bytes.fromhex("021122334455"),
                session_id=bytes(range(16)), advertise_data=b"\xde\xad\xbe\xef",
                host_name=b"PkCamp")
    args.update(kw)
    return ldn_mitm_host.build_network_info(**args)


def test_the_advertised_session_id_is_the_key_the_host_encrypts_pia_with():
    """crypto.PiaCrypto keys off the LDN ssid, so the value advertised as NetworkId.SessionId and
    the value the host hands the Pia layer have to be one 16-byte value."""
    from pokeldn.ldn import crypto
    host = ldn_mitm_host.IpHostTransport(our_ip=HOST_IP, log=lambda *_a, **_k: None)
    info = host._build_info()
    assert len(host.ssid) == 16
    assert info[ldn_mitm.OFF_SESSION_ID:ldn_mitm.OFF_SESSION_ID + 16] == host.ssid
    length = info[ldn_mitm.OFF_SSID]
    assert info[ldn_mitm.OFF_SSID + 1:ldn_mitm.OFF_SSID + 1 + length] == host.ssid.hex().encode()
    assert len(crypto.PiaCrypto(host.ssid).session_key) == 16
    with pytest.raises(ValueError):
        ldn_mitm_host.IpHostTransport(our_ip=HOST_IP, ssid=b"short", log=lambda *_a, **_k: None)


def test_the_host_advertises_the_application_version_where_the_console_carries_its_own():
    """A NetworkInfo read out of the running game puts the console's own 88 at node+0x2E, so the
    field is a u16 aligned after the byte at 0x2C. `dumps/003_networkinfo_as_game_sees_it.bin`."""
    host = ldn_mitm_host.IpHostTransport(our_ip=HOST_IP, log=lambda *_a, **_k: None)
    assert ldn_mitm_host.OFF_NODE_LOCAL_COMM_VERSION == 0x2E
    assert ldn_mitm_host.node_local_comm_version(host._build_info(), 0) == 88
    assert host.APPLICATION_VERSION == 88


def test_network_info_reads_back_through_the_joiner_side():
    info = _info()
    assert len(info) == ldn_mitm.NETWORK_INFO_SIZE
    assert int.from_bytes(info[0:8], "little") == COMM_ID
    assert int.from_bytes(info[0x0A:0x0C], "little") == 22287
    assert ldn_mitm.host_mac(info) == bytes.fromhex("021122334455")
    assert ldn_mitm.advertise_data(info) == b"\xde\xad\xbe\xef"
    ip, mac, node_id, connected, name = ldn_mitm_host.read_node(info, 0)
    assert (ip, node_id, connected, name) == (HOST_IP, 0, 1, b"PkCamp")
    assert mac == bytes.fromhex("021122334455")


def test_advertise_data_larger_than_the_field_is_refused():
    with pytest.raises(ValueError):
        _info(advertise_data=b"\0" * 0x181)
    with pytest.raises(ValueError):
        _info(session_id=b"short")


def _wait(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def host():
    h = ldn_mitm_host.IpHostTransport(app_data=b"\x01\x02\x03", nickname="PkCamp",
                                      our_ip=HOST_IP, log=lambda *_a, **_k: None,
                                      discovery_port=DISCOVERY_PORT, pia_port=PIA_PORT)
    h.start()
    try:
        yield h
    finally:
        h.stop()


def test_the_host_answers_a_scan_and_seats_a_join(host):
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(3)
    udp.sendto(ldn_mitm.build(ldn_mitm.SCAN), (HOST_IP, DISCOVERY_PORT))
    kind, info = ldn_mitm.parse(udp.recvfrom(65535)[0])
    assert kind == ldn_mitm.SCAN_RESP
    assert int.from_bytes(info[0:8], "little") == COMM_ID
    assert ldn_mitm.advertise_data(info) == b"\x01\x02\x03"
    assert ldn_mitm_host.read_node(info, 0)[0] == HOST_IP

    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(3)
    tcp.connect((HOST_IP, DISCOVERY_PORT))
    tcp.sendall(ldn_mitm.build(
        ldn_mitm.CONNECT,
        ldn_mitm.build_node_info(PEER_IP, bytes.fromhex("aabbccddeeff"), b"Ryujinx")))
    kind, synced = ldn_mitm.parse(tcp.recv(65535))
    assert kind == ldn_mitm.SYNC_NETWORK
    assert synced[ldn_mitm_host.OFF_NODE_COUNT] == 2
    assert ldn_mitm_host.read_node(synced, 1) == (
        PEER_IP, bytes.fromhex("aabbccddeeff"), 1, 1, b"Ryujinx")
    assert _wait(lambda: host.join_events == 1)
    assert host.participants == [(1, PEER_IP, bytes.fromhex("aabbccddeeff"), b"Ryujinx")]
    tcp.close()
    udp.close()


def test_the_pia_port_carries_a_datagram_from_the_console(host):
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind((PEER_IP, 0))
    peer.sendto(b"\x01\x02\x03\x04payload", (HOST_IP, PIA_PORT))
    assert _wait(lambda: host.recv() or host._rx_seen)
    peer.close()


def test_new_application_data_replaces_what_a_later_scan_reads(host):
    host.set_application_data(b"\x09" * 40)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(3)
    udp.sendto(ldn_mitm.build(ldn_mitm.SCAN), (HOST_IP, DISCOVERY_PORT))
    _kind, info = ldn_mitm.parse(udp.recvfrom(65535)[0])
    assert ldn_mitm.advertise_data(info) == b"\x09" * 40
    udp.close()


def test_the_host_mac_encodes_its_address_the_way_the_peer_does():
    """An emulated console at 172.16.86.1 gives itself 02:00:ac:10:56:01. The host follows suit."""
    import socket

    from pokeldn.ldn.ldn_mitm_host import IpHostTransport

    t = IpHostTransport(our_ip="172.16.86.128")
    assert t.our_mac == b"\x02\x00" + socket.inet_aton("172.16.86.128")
    assert t.our_mac.hex() == "0200ac105680"
    assert IpHostTransport(our_ip="172.16.86.128", mac=b"\x02\x01\x02\x03\x04\x05").our_mac == \
        b"\x02\x01\x02\x03\x04\x05"


def test_a_station_that_leaves_frees_its_node_and_the_next_scan_says_so(host):
    """A station's node info states its own address, which need not be the address its connection
    comes from: a peer on this machine connects from one and advertises another. The node slot is
    tracked by the connection, because a session capped at two advertises as full while a slot is
    held by a station that has gone, and the console will not join."""
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(3)
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(3)
    tcp.connect((HOST_IP, DISCOVERY_PORT))          # connects from 127.0.0.1
    tcp.sendall(ldn_mitm.build(
        ldn_mitm.CONNECT,
        ldn_mitm.build_node_info(PEER_IP, bytes.fromhex("02007f000002"), b"RyuPlayer")))
    kind, synced = ldn_mitm.parse(tcp.recv(65535))   # advertises 127.0.0.2
    assert kind == ldn_mitm.SYNC_NETWORK
    assert synced[ldn_mitm_host.OFF_NODE_COUNT] == 2

    tcp.close()
    assert _wait(lambda: host.participants == [])
    udp.sendto(ldn_mitm.build(ldn_mitm.SCAN), (HOST_IP, DISCOVERY_PORT))
    _kind, info = ldn_mitm.parse(udp.recvfrom(65535)[0])
    assert info[ldn_mitm_host.OFF_NODE_COUNT] == 1, "the seat is free again"
    assert ldn_mitm_host.read_node(info, 1) == ("0.0.0.0", bytes(6), 0, 0, b"")
    assert ldn_mitm_host.read_node(info, 0)[0] == HOST_IP
    udp.close()
