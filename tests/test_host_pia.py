"""Transport-independent tests for host-side Pia framing and state."""

from types import SimpleNamespace
from unittest import mock

from pokeldn.ldn import crypto, pia_connect, reliable
from pokeldn.ldn.host_pia import (
    HostPeerProtocol,
    PIA_HOST_VAR,
    PiaNonceSequence,
    build_message,
    build_messages,
    decode_datagram,
    reliable_output_batches,
)
from pokeldn.ldn.reliable import FLAGSA_CTRL, FLAGSA_GBA, ReliableEmission


def _network():
    return SimpleNamespace(
        ssid=bytes.fromhex("5c42961f018902911a2f1c9548c8e9c4"),
        our_ip="169.254.88.1",
        our_mac=bytes.fromhex("3ca9abf73c06"),
        broadcast="169.254.88.255",
        participants=[],
        max_participants=6,
    )


def test_nonce_modes_increment_wrap_and_generate_random_bytes():
    native = PiaNonceSequence(native=True, initial=0xFFFFFFFFFFFFFFFF)
    assert native.take() == b"\xff" * 8
    assert native.take() == b"\x00" * 8
    assert native.take() == b"\x00" * 7 + b"\x01"
    with mock.patch("pokeldn.ldn.host_pia.os.urandom", lambda size: b"R" * size):
        random = PiaNonceSequence(native=False)
        assert random.take() == random.take() == b"R" * 8


def test_reliable_batches_end_at_control_and_retransmit_emissions():
    data1 = ReliableEmission(0xFFF0, FLAGSA_GBA, 0xFFF0, b"A")
    ack = ReliableEmission(0xFFF0, FLAGSA_CTRL, 0xFFF1, b"ack")
    data2 = ReliableEmission(0xFFF1, FLAGSA_GBA, 0xFFF0, b"T")
    assert reliable_output_batches([data1, ack, data2]) == [[data1, ack], [data2]]

    retransmit = ReliableEmission(
        0xFFF2, FLAGSA_GBA, 0xFFF0, b"retry", retransmitted=True)
    assert reliable_output_batches([data1, retransmit, data2]) == [
        [data1, retransmit], [data2]
    ]


def test_build_and_decode_messages_round_trip_padding_and_flags():
    network = _network()
    pia_crypto = crypto.PiaCrypto(network.ssid)
    datagram = build_messages(
        network,
        pia_crypto,
        [(pia_connect.PROTO_RTT, b"request"),
         (pia_connect.PROTO_RELIABLE, b"payload", 0x20)],
        dst_var=0x7171,
        src_var=PIA_HOST_VAR,
        pktid=9,
        footer_var=0x7171,
        establishing=True,
        nonce_source=PiaNonceSequence(native=True, initial=7),
    )
    decoded, error = decode_datagram(datagram, network.our_ip, pia_crypto)
    assert error is None
    header, messages = decoded
    assert (header.dst, header.src, header.pktid, header.footer) == (
        0x7171, PIA_HOST_VAR, 9, 2)
    assert header.nonce8 == b"\x00" * 7 + b"\x07"
    assert [(message.proto, message.payload, message.msgflags) for message in messages] == [
        (pia_connect.PROTO_RTT, b"request", 0),
        (pia_connect.PROTO_RELIABLE, b"payload", 0x20),
    ]


def test_decode_rejects_non_ff_padding():
    network = _network()
    pia_crypto = crypto.PiaCrypto(network.ssid)
    message = reliable.build_message(pia_connect.PROTO_RTT, b"request")
    pad = (-len(message)) % 16
    plaintext = message + b"\xff" * (pad - 1) + b"\x00"
    header = crypto.PiaHeader(
        dst=0x7171, src=PIA_HOST_VAR, pktid=9,
        nonce8=b"N" * 8, flags=pad << 4, footer=0)
    datagram = pia_crypto.encrypt(plaintext, network.our_ip, header)
    decoded, error = decode_datagram(datagram, network.our_ip, pia_crypto)
    assert decoded is None
    assert error == f"invalid {pad}-byte padding"


def test_peer_rejects_malformed_session_without_mutating_identity():
    network = _network()
    session = SimpleNamespace(trade=SimpleNamespace(established=False))
    profile = SimpleNamespace(session_name="EMU")
    logs = []
    peer = HostPeerProtocol(network, profile, session, b"app", log=logs.append)
    peer.on_participant_joined()
    malformed = build_message(
        network, peer.pia_crypto, pia_connect.PROTO_SESSION,
        bytes([pia_connect.SESSION_JOIN_REQUEST]),
        dst_var=PIA_HOST_VAR, src_var=0x7171,
        nonce_source=PiaNonceSequence(native=True, initial=1))
    assert peer.receive(malformed, network.our_ip, now=1.0) == []
    assert not peer.session_join_seen
    assert peer.session_join is None
    assert peer.guest_var is None and peer.guest_ip is None
    assert peer.drain() == []
    assert any("malformed or unsupported Session join" in line for line in logs)


# The GBA app's join (an emulated "EMU" player, tests/test_pia_host_session.py) and a leave request
# in the layout a retail FireRed sent four times on leaving: type, random, constant id, variable id,
# reason, IPv4, port.
_EMU_JOIN = bytes.fromhex(
    "00060100030505010a030d070f00005838a074cc3c33006094930000c4930000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "ab3c06f7a93c000000c6010100a9fe580230390000000000000001000000000000"
    "00000000000301454d55")
_RETAIL_LEAVE = bytes.fromhex("03439e6bc0eb9b2220f1480000696800a9fe4a023039")


def _console_session(peer, payload, src_var=0xC493, pktid=1):
    console = SimpleNamespace(our_ip="169.254.88.2")
    return peer.receive(build_message(
        console, peer.pia_crypto, pia_connect.PROTO_SESSION, payload,
        dst_var=PIA_HOST_VAR, src_var=src_var, pktid=pktid, footer_var=PIA_HOST_VAR,
        nonce_source=PiaNonceSequence(native=True, initial=pktid)), "169.254.88.2", now=1.0)


def _session_replies(peer, network):
    out = []
    for item in peer.drain():
        decoded, error = decode_datagram(item.data, network.our_ip, peer.pia_crypto)
        assert error is None
        header, messages = decoded
        out += [(item.destination, header, m.payload) for m in messages
                if m.proto == pia_connect.PROTO_SESSION]
    return out


def test_leave_request_is_answered_in_the_form_the_leaver_checks():
    """The leaver's type-4 check `0xba028` (GBA app main): 15 bytes, its own constant id at 5 and
    variable id at 13. Unanswered, it resends every 500 ms and leaves after the fourth."""
    assert pia_connect.build_session_leave_response(_RETAIL_LEAVE, b"RAND") == (
        b"\x04RAND" + bytes.fromhex("eb9b2220f1480000") + bytes.fromhex("6968"))

    network = _network()
    session = SimpleNamespace(trade=SimpleNamespace(established=False))
    peer = HostPeerProtocol(network, SimpleNamespace(session_name="EMU"), session, b"app")
    peer.on_participant_joined()
    _console_session(peer, _EMU_JOIN)
    _console_session(peer, pia_connect.build_session_finalize(b"\x3c\x33\x00\x60\x94\x93"),
                     pktid=2)
    assert peer.session_finalized
    peer.drain()

    leave = (bytes([pia_connect.SESSION_LEAVE_REQUEST]) + b"\x11\x22\x33\x44"
             + bytes.fromhex("3c33006094930000") + bytes.fromhex("c493") + b"\x00"
             + bytes.fromhex("a9fe5802") + (12345).to_bytes(2, "big"))
    for n in range(4):
        _console_session(peer, leave, pktid=3 + n)
    replies = _session_replies(peer, network)
    assert len(replies) == 4 and peer.leave_requests_in == 4
    for destination, header, payload in replies:
        assert destination == "169.254.88.2"
        assert (header.dst, header.src) == (0xC493, PIA_HOST_VAR)
        assert len(payload) == 15 and payload[0] == 4
        assert payload[5:13] == bytes.fromhex("3c33006094930000")
        assert payload[13:15] == bytes.fromhex("c493")
    assert len({h.pktid for _, h, _ in replies}) == 4

    stranger = leave[:13] + bytes.fromhex("7171") + leave[15:]
    _console_session(peer, stranger, pktid=9)
    _console_session(peer, leave, src_var=0x7171, pktid=10)
    assert _session_replies(peer, network) == [] and peer.leave_requests_in == 4
