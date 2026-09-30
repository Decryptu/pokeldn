import json
from collections import deque

import pytest

from pokeldn.frlg.link import linkplayer
from pokeldn.frlg.remote.config import RemoteTradeConfig
from pokeldn.frlg.remote.journal import RemoteJournal
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
