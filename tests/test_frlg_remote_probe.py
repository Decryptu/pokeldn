import base64
import hashlib
import hmac
import socket
import struct
import threading
import time

import pytest

from pokeldn.frlg.link import linkplayer, trade
from pokeldn.frlg.link.host_trade import H_SELECT, HostTradeEngine
from pokeldn.frlg.remote.coordinator import ProbeCoordinator, snapshot_digest
from pokeldn.frlg.remote.config import RemoteTradeConfig
from pokeldn.frlg.remote.protocol import (
    AUTH_TAG_BYTES, MAX_FRAME_BYTES, PHASE_ORDER, PHASE_SIZES, FrameDecoder,
    LanMessage, ProtocolError, decode_payload, encode_frame, logical_bytes,
)
from pokeldn.frlg.remote.transport import (
    RemoteTransport, _handshake_host, _handshake_join,
)


KEY = b"remote-probe-test-key-32-bytes!!!"
ROOM = "a1" * 16
RUN = "b2" * 16


def _message(seq, message_type="PING", payload=None, *, sender="host", phase=None,
             ack_seq=0):
    if payload is None:
        payload = {"time_ns": seq}
    return LanMessage(1, ROOM, RUN, sender, seq, ack_seq, message_type, phase, payload)


def _block_message(seq, phase, data, *, sender="join"):
    raw = bytes(data)
    logical = logical_bytes(phase, raw)
    return _message(seq, "PEER_BLOCK", {
        "data": base64.b64encode(raw).decode("ascii"),
        "digest": hashlib.sha256(logical).hexdigest(),
    }, sender=sender, phase=phase)


def test_authenticated_decoder_handles_fragmented_and_coalesced_frames():
    first = encode_frame(_message(1), KEY)
    second = encode_frame(_message(2), KEY)
    decoder = FrameDecoder(KEY)
    assert decoder.feed(first[:3]) == []
    assert decoder.feed(first[3:11]) == []
    assert decoder.feed(first[11:] + second) == [_message(1), _message(2)]
    decoder.eof()


def test_authenticated_decoder_rejects_bad_mac_length_and_truncated_eof():
    frame = bytearray(encode_frame(_message(1), KEY))
    frame[-1] ^= 0x80
    with pytest.raises(ProtocolError, match="authentication"):
        FrameDecoder(KEY).feed(frame)
    with pytest.raises(ProtocolError, match="length"):
        FrameDecoder(KEY).feed(struct.pack(">I", MAX_FRAME_BYTES + 1))
    decoder = FrameDecoder(KEY)
    decoder.feed(encode_frame(_message(1), KEY)[:7])
    with pytest.raises(ProtocolError, match="EOF"):
        decoder.eof()


def test_message_schema_rejects_unknown_fields_bad_data_and_duplicate_json_keys():
    raw = bytearray(encode_frame(_message(1), KEY))
    with pytest.raises(ProtocolError, match="authentication"):
        decode_payload(bytes(raw[4:]), b"wrong-key" * 4)

    malformed = _message(1, "PEER_BLOCK", {
        "data": "not base64!", "digest": "0" * 64,
    }, phase="mail")
    with pytest.raises(ProtocolError, match="Base64"):
        encode_frame(malformed, KEY)

    body = b'{"protocol_version":1,"protocol_version":1}'
    prefix = struct.pack(">I", len(body) + AUTH_TAG_BYTES)
    tag = hmac.new(KEY, prefix + body, hashlib.sha256).digest()
    with pytest.raises(ProtocolError, match="duplicate"):
        decode_payload(body + tag, KEY)


def test_pairing_handshake_authenticates_both_sides_and_keeps_direction_sequences():
    host_sock, join_sock = socket.socketpair()
    result = {}
    errors = []

    def run_host():
        try:
            result["host"] = _handshake_host(host_sock, KEY, "LDN-A")
        except Exception as exc:  # surfaced below so the worker cannot hide test failures
            errors.append(exc)

    thread = threading.Thread(target=run_host)
    thread.start()
    try:
        room_id, run_id, join_state, host_name = _handshake_join(join_sock, KEY, "LDN-B")
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert not errors
        host_room, host_run, host_state, join_name = result["host"]
        assert (room_id, run_id) == (host_room, host_run)
        assert (host_name, join_name) == ("LDN-A", "LDN-B")
        assert host_state.tx_seq == join_state.tx_seq == 3
        assert host_state.rx_seq == join_state.rx_seq == 3

        frame = host_state.frame("PING", {"time_ns": 123})
        message = FrameDecoder(join_state.receive_key).feed(frame)[0]
        join_state.accept(message)
        assert message.sender_id == "host" and message.seq == 3
    finally:
        host_sock.close()
        join_sock.close()
        thread.join(timeout=2)


def test_tcp_worker_pairs_once_and_delivers_structured_business_events():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    host = RemoteTransport(RemoteTradeConfig(
        role="host", listen="127.0.0.1", port=port, room_key=KEY,
        discovery_name="LDN-A", connect_timeout=3))
    join = RemoteTransport(RemoteTradeConfig(
        role="join", connect="127.0.0.1", port=port, room_key=KEY,
        discovery_name="LDN-B", connect_timeout=3))
    result, errors = {}, []

    def start_host():
        try:
            result["host"] = host.start()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=start_host, daemon=True)
    thread.start()
    try:
        join.start()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert not errors
        assert host.peer_name == "LDN-B"
        assert join.peer_name == "LDN-A"
        host.send("LOCAL_LINK_STATE", {"state": "connected"})
        deadline = time.monotonic() + 2
        received = []
        while time.monotonic() < deadline and not received:
            received = join.poll()
            time.sleep(0.01)
        assert len(received) == 1
        assert received[0].message.type == "LOCAL_LINK_STATE"
        assert received[0].message.payload == {"state": "connected"}
    finally:
        host.close()
        join.close()
        thread.join(timeout=2)


def test_probe_coordinator_requires_ordered_blocks_and_both_presented_snapshots():
    coordinator = ProbeCoordinator(RUN)
    blocks = {phase: bytes([index + 1]) * PHASE_SIZES[phase]
              for index, phase in enumerate(PHASE_ORDER)}
    final_snapshot = None
    for phase in PHASE_ORDER:
        coordinator.record_local_block(phase, blocks[phase])
        message = _block_message(PHASE_ORDER.index(phase) + 1, phase, blocks[phase])
        coordinator.record_remote_message(message)
        assert coordinator.take_remote_block(phase) == blocks[phase]
        final_snapshot = coordinator.settle_phase(phase)
    assert final_snapshot["phases"] == list(PHASE_ORDER)
    assert coordinator.local_snapshot_digest == final_snapshot["digest"]
    assert not coordinator.both_snapshots_ready
    coordinator.record_remote_snapshot({
        "snapshot_id": "c3" * 16, "digest": snapshot_digest(blocks),
    })
    assert coordinator.both_snapshots_ready

    with pytest.raises(ProtocolError, match="snapshot digest"):
        coordinator.record_remote_snapshot({
            "snapshot_id": "c3" * 16, "digest": "d4" * 32,
        })

    wrong_order = ProbeCoordinator(RUN)
    with pytest.raises(ProtocolError, match="out of order"):
        wrong_order.record_local_block("trainer_card", bytes(100))


def test_parent_role_linkplayer_conversion_changes_only_player_id():
    lp = linkplayer.LinkPlayer(name="Remote", player_id=1)
    raw = bytearray(linkplayer.build_block(lp).ljust(200, b"\xA5"))
    converted = linkplayer.as_parent_role_block(raw)
    assert converted[:40] == raw[:40]
    assert converted[40:42] == b"\x00\x00"
    assert converted[42:] == raw[42:]
    assert linkplayer.parse_block(converted)[1]
    with pytest.raises(ValueError, match="200 bytes"):
        linkplayer.as_parent_role_block(bytes(60))


class _Policy:
    def __init__(self):
        self.local = []
        self.remote = {}
        self.settled = []
        self.identity = None

    def publish_local_block(self, phase, data):
        self.local.append((phase, data))

    def take_remote_block(self, phase):
        return self.remote.pop(phase, None)

    def phase_settled(self, phase):
        self.settled.append(phase)

    def local_identity(self, **identity):
        self.identity = identity


def test_remote_engine_waits_for_real_peer_linkplayer_and_never_starts_trade():
    policy = _Policy()
    engine = HostTradeEngine(remote_policy=policy)
    assert engine.party == []
    assert engine.trainer_card is None
    assert not engine._blocks

    local = linkplayer.build_block(
        linkplayer.LinkPlayer(name="Local", player_id=1)).ljust(200, b"\x00")
    engine._after_child_block(trade.COUNT_PARTY, local)
    assert engine._expected == "remote:link_player"
    assert policy.local == [("link_player", local)]
    assert policy.identity == {"version": 0x4005, "language": 2, "player_id": 1}

    remote = linkplayer.build_block(
        linkplayer.LinkPlayer(name="Peer", player_id=1)).ljust(200, b"\xA5")
    policy.remote["link_player"] = remote
    engine.resume_remote_phase()
    assert engine._expected == "warp0"
    assert engine._blocks[-1][0] == linkplayer.as_parent_role_block(remote)

    engine.state = H_SELECT
    engine._on_child_linkcmd(trade.READY_TO_TRADE, 3)
    assert int.from_bytes(engine._blocks[-1][0][:2], "little") == trade.PLAYER_CANCEL_TRADE
    engine._on_child_linkcmd(trade.INIT_BLOCK, 0)
    assert all(int.from_bytes(block[:2], "little") != trade.START_TRADE
               for block, _label in engine._blocks)
    with pytest.raises(RuntimeError, match="commit is disabled"):
        engine._commit()
