#!/usr/bin/env python3
"""The host Pia Reliable state machine."""

from pokeldn.ldn import reliable


def _payloads(deliveries):
    return [delivery.payload for delivery in deliveries]


def test_stream_open_and_delayed_ack():
    leader = reliable.HostReliableSession()
    child = reliable.HostReliableSession()

    opening = child.open(reliable.METADATA_FRAME, 0)
    parsed = reliable.parse_reliable(opening.serialize())
    assert parsed.seq == 0xFFF0
    assert parsed.ack == 0xFFF0
    assert parsed.flagsA == reliable.FLAGSA_INIT
    assert parsed.payload == reliable.METADATA_FRAME
    assert opening.message_flags is None

    delivered = leader.receive(opening.serialize(), 1)
    assert leader.peer_opened
    assert _payloads(delivered) == [reliable.METADATA_FRAME]
    assert leader.poll(33) == []

    ack = leader.poll(34)
    assert len(ack) == 1
    assert ack[0].flagsA == reliable.FLAGSA_CTRL
    assert ack[0].message_flags == 0x40
    ack_frame = reliable.parse_reliable(ack[0].serialize())
    ack_id, mask = reliable.parse_bulk_ack(ack_frame.payload)
    assert ack_id == 0xFFF1
    assert mask == b"\x00" * 16

    # A native leader ACKs the child's metadata with its own stream closed, then opens fff0 with RFU
    # A.
    assert not leader.local_opened
    rfu_accept = bytes.fromhex("57410600b7f180840000")
    leader_opening = leader.open(rfu_accept, 35)
    assert leader_opening.seq == 0xFFF0
    assert leader_opening.flagsA == reliable.FLAGSA_INIT
    assert leader_opening.payload == rfu_accept

    child.receive(ack[0].serialize(), 36)
    assert child.inflight == 0


def test_gap_sack_fast_retransmit_and_ordered_delivery():
    sender = reliable.HostReliableSession(ack_period_ms=0)
    receiver = reliable.HostReliableSession(ack_period_ms=0)

    sender.open(reliable.METADATA_FRAME, 0)
    sender.receive(reliable.build_reliable(
        0xFFF0, 0xFFF1, reliable.build_bulk_ack(0xFFF1),
        reliable.FLAGSA_CTRL), 1)
    first = sender.send(b"first", 2)
    second = sender.send(b"second", 2)
    third = sender.send(b"third", 2)

    # DATA fff1 is lost; later frames are SACKed and held back.
    receiver.receive(reliable.build_reliable(
        0xFFF0, 0xFFF0, reliable.METADATA_FRAME,
        reliable.FLAGSA_INIT), 0)
    receiver.poll(0)
    assert receiver.receive(second.serialize(), 3) == []
    assert receiver.receive(third.serialize(), 3) == []
    sack = receiver.poll(3)[0]
    ack_id, mask = reliable.parse_bulk_ack(sack.payload)
    assert ack_id == 0xFFF1
    # The bitmap starts at ack_id + 1, measured over 591 masks in three hardware captures
    # [reliable.MASK_ORIGIN_OFFSET].
    assert mask[0] & 0b111 == 0b011

    sender.receive(sack.serialize(), 4)
    retransmits = sender.poll(4)
    assert [(tx.seq, tx.payload) for tx in retransmits] == [(first.seq, b"first")]
    assert retransmits[0].retransmitted
    assert retransmits[0].message_flags == 0x20

    delivered = receiver.receive(retransmits[0].serialize(), 5)
    assert _payloads(delivered) == [b"first", b"second", b"third"]
    assert receiver.receive(retransmits[0].serialize(), 6) == []

    cumulative = receiver.poll(6)[0]
    sender.receive(cumulative.serialize(), 7)
    assert sender.inflight == 0


def test_bootstrap_timeout_then_rtt_driven_timeout():
    session = reliable.HostReliableSession(rto_bootstrap_ms=200)
    opening = session.open(b"leader A", 0)
    assert session.poll(199) == []
    retry = session.poll(200)
    assert len(retry) == 1
    assert retry[0].seq == opening.seq
    assert retry[0].payload == opening.payload
    assert retry[0].message_flags == 0x20

    # Native RTO becomes 33 + 1.4*10 = 47 ms for the next frame.
    session.receive(reliable.build_reliable(
        0xFFF0, 0xFFF1, reliable.build_bulk_ack(0xFFF1),
        reliable.FLAGSA_CTRL), 201)
    session.note_rtt(10)
    data = session.send(b"rfu", 210)
    assert session.poll(256) == []
    retry = session.poll(257)
    assert [(tx.seq, tx.payload) for tx in retry] == [(data.seq, b"rfu")]


def test_window_backpressure_and_malformed_input():
    session = reliable.HostReliableSession(max_inflight=2)
    assert session.receive(b"short", 0) == []
    malformed_open = reliable.build_reliable(
        0xFFF0, 0xFFF0, b"not initialized", reliable.FLAGSA_GBA)
    assert session.receive(malformed_open, 0) == []
    assert session.recv_next == 0xFFF0
    assert not session.peer_opened
    session.open(b"leader A", 0)
    session.send(b"one slot left", 1)
    try:
        session.send(b"overflow", 2)
    except BufferError:
        pass
    else:
        raise AssertionError("full Reliable window did not apply backpressure")


def main():
    test_stream_open_and_delayed_ack()
    test_gap_sack_fast_retransmit_and_ordered_delivery()
    test_bootstrap_timeout_then_rtt_driven_timeout()
    test_window_backpressure_and_malformed_input()
    print("host reliable tests passed")
