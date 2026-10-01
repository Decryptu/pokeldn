import queue
import json
from collections import deque
import threading
import time

import pytest

from pokeldn.frlg.link import linkplayer
from pokeldn.frlg.remote.config import RemoteTradeConfig
from pokeldn.frlg.remote.journal import JournalError, RemoteJournal
from pokeldn.frlg.remote.phase_gate import FilePhaseGate
from pokeldn.frlg.remote.policy import RemoteTradePolicy
from pokeldn.frlg.remote.protocol import (
    PHASE_ORDER, PHASE_SIZES, validate_message,
)
from pokeldn.frlg.remote.transport import TransportEvent


RUN = "11" * 16


class MemoryTransport:
    def __init__(self, sender_id):
        self.sender_id = sender_id
        self.peer = None
        self.run_id = RUN
        self.error = None
        self.sequence = 1
        self.incoming = deque()

    def send(self, message_type, payload, *, phase=None):
        message = validate_message({
            "protocol_version": 1,
            "room_id": "22" * 16,
            "run_id": RUN,
            "sender_id": self.sender_id,
            "seq": self.sequence,
            "ack_seq": 0,
            "type": message_type,
            "phase": phase,
            "payload": payload,
        })
        self.sequence += 1
        self.peer.incoming.append(TransportEvent("message", message=message))

    def poll(self, limit=32):
        result = []
        while self.incoming and len(result) < limit:
            result.append(self.incoming.popleft())
        return result


def test_two_probe_policies_exchange_every_phase_and_wait_for_both_snapshots():
    host_transport = MemoryTransport("host")
    join_transport = MemoryTransport("join")
    host_transport.peer = join_transport
    join_transport.peer = host_transport
    host = RemoteTradePolicy(host_transport)
    join = RemoteTradePolicy(join_transport)

    for index, phase in enumerate(PHASE_ORDER):
        if phase == "link_player":
            host_data = linkplayer.build_block(linkplayer.LinkPlayer(name="HOST")).ljust(200, b"\0")
            join_data = linkplayer.build_block(linkplayer.LinkPlayer(name="JOIN")).ljust(200, b"\0")
        else:
            host_data = bytes([index + 1]) * PHASE_SIZES[phase]
            join_data = bytes([index + 20]) * PHASE_SIZES[phase]

        host.publish_local_block(phase, host_data)
        join.publish_local_block(phase, join_data)
        host.poll()
        join.poll()
        assert host.take_remote_block(phase) == join_data
        assert join.take_remote_block(phase) == host_data
        host.phase_settled(phase)
        join.phase_settled(phase)

    host.poll()
    join.poll()
    assert host.coordinator.both_snapshots_ready
    assert join.coordinator.both_snapshots_ready
    assert host.report()["local_snapshot_digest"] != host.report()["remote_snapshot_digest"]


def test_remote_config_requires_a_specific_address_and_128_bit_key():
    with pytest.raises(ValueError, match="wildcard"):
        RemoteTradeConfig("host", listen="0.0.0.0", room_key=b"k" * 32)
    with pytest.raises(ValueError, match="128 bits"):
        RemoteTradeConfig("join", connect="192.168.1.2", room_key=b"short")
    valid = RemoteTradeConfig("host", listen="127.0.0.1", room_key=b"k" * 32)
    assert valid.probe_only is True


def test_remote_journal_persists_only_digests_and_rejects_block_data(tmp_path):
    journal = RemoteJournal(RUN, root=tmp_path)
    journal.append("local_block_received", phase="mail", length=220, digest="a" * 64)
    with pytest.raises(ValueError, match="cannot store"):
        journal.append("unsafe", data=bytes(220))
    journal.close()
    records = [json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["digest"] == "a" * 64
    assert "data" not in records[0]


def test_remote_journal_reports_writer_failure(tmp_path):
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied", encoding="utf-8")
    journal = RemoteJournal(RUN, root=blocked_parent)
    for _ in range(100):
        if journal.failure is not None:
            break
        time.sleep(0.01)
    assert journal.failure is not None
    with pytest.raises(JournalError, match="write failed"):
        journal.append("probe_summary")
    with pytest.raises(JournalError, match="write failed"):
        journal.close()


def test_remote_journal_reports_a_full_queue_without_blocking(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def blocked_writer(_journal):
        entered.set()
        release.wait(timeout=2)

    monkeypatch.setattr(RemoteJournal, "_writer", blocked_writer)
    journal = RemoteJournal(RUN, root=tmp_path)
    assert entered.wait(timeout=1)
    journal._queue = queue.Queue(maxsize=1)
    journal.append("one")
    with pytest.raises(JournalError, match="queue is full"):
        journal.append("two")
    journal._queue.get_nowait()
    release.set()
    journal.close()


def test_policy_holds_only_the_configured_phase_until_local_release(tmp_path):
    host_transport = MemoryTransport("host")
    join_transport = MemoryTransport("join")
    host_transport.peer = join_transport
    join_transport.peer = host_transport
    release_file = tmp_path / "release"
    messages = []
    host = RemoteTradePolicy(
        host_transport,
        log=messages.append,
        phase_gate=FilePhaseGate("link_player", release_file),
    )
    remote = linkplayer.build_block(linkplayer.LinkPlayer(name="Remote")).ljust(200, b"\0")

    RemoteTradePolicy(join_transport).publish_local_block("link_player", remote)
    host.poll()
    assert host.take_remote_block("link_player") is None
    assert host.take_remote_block("link_player") is None
    assert sum("test gate holding" in message for message in messages) == 1

    release_file.touch()
    host.phase_gate._next_check = 0.0
    assert host.take_remote_block("link_player") == remote
    assert host.take_remote_block("link_player") is None
    assert sum("test gate released" in message for message in messages) == 1


def test_peer_cancel_then_tcp_eof_is_a_normal_close():
    host_transport = MemoryTransport("host")
    join_transport = MemoryTransport("join")
    host_transport.peer = join_transport
    join_transport.peer = host_transport
    host = RemoteTradePolicy(host_transport)
    join = RemoteTradePolicy(join_transport)

    join.stop("cancelled")
    host_transport.error = "LAN peer disconnected"
    host.poll()

    assert host.report()["lan_failure"] is None
    assert host.report()["remote_stop_reason"] == "cancelled"


def test_tcp_eof_without_a_stop_intent_is_still_a_failure():
    transport = MemoryTransport("host")
    transport.error = "LAN peer disconnected"
    policy = RemoteTradePolicy(transport)

    policy.poll()

    assert policy.report()["lan_failure"] == "LAN peer disconnected"


def test_queued_tcp_eof_after_peer_cancel_is_not_reclassified_as_empty_message():
    host_transport = MemoryTransport("host")
    join_transport = MemoryTransport("join")
    host_transport.peer = join_transport
    join_transport.peer = host_transport
    host = RemoteTradePolicy(host_transport)
    join = RemoteTradePolicy(join_transport)

    join.stop("cancelled")
    host_transport.incoming.append(TransportEvent(
        "error", error="LAN peer disconnected"))
    host.poll()

    assert host.report()["lan_failure"] is None


def test_local_cancel_also_protects_against_a_racing_tcp_eof():
    transport = MemoryTransport("host")
    peer = MemoryTransport("join")
    transport.peer = peer
    peer.peer = transport
    policy = RemoteTradePolicy(transport)
    policy.stop("cancelled")
    transport.error = "LAN peer disconnected"

    policy.poll()

    assert policy.report()["lan_failure"] is None
