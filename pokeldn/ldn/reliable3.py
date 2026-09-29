"""Pia 5.11's reliable sliding window, protocol 0x7C, where Let's Go's game data is.

Header layout: docs/lgpe_session.md, The Reliable Protocol (0x7C).
"""
import struct

PROTOCOL = 0x7C
HEADER_SIZE = 0x18
FIRST_SEQUENCE = 0xFFFFF82F
GAME_STREAM = 3
__all__ = ["PROTOCOL", "HEADER_SIZE", "FIRST_SEQUENCE", "GAME_STREAM", "build", "build_ack",
           "parse", "Window"]


def build(payload, sequence, expected, stream=GAME_STREAM, flags=0):
    return (struct.pack(">BBHIII", flags, stream, len(payload), 0, sequence & 0xFFFFFFFF,
            expected & 0xFFFFFFFF) + bytes(8) + bytes(payload))


def build_ack(expected):
    """The header alone, carrying the next sequence id expected."""
    return build(b"", 0, expected, stream=0)


def parse(data):
    """-> dict of the header fields and the payload, or None."""
    if len(data) < HEADER_SIZE:
        return None
    flags, stream, size, _, sequence, expected = struct.unpack_from(">BBHIII", data, 0)
    return {"flags": flags, "stream": stream, "size": size, "sequence": sequence,
            "expected": expected, "payload": data[HEADER_SIZE:HEADER_SIZE + size]}


class Window:
    """One station's side: sends payloads in order and acknowledges the peer's."""

    # Over 120 messages to a retail console none waited past 0.104 s: a net under a lost datagram.
    RETRANSMIT_AFTER = 0.5

    def __init__(self):
        self.sequence = FIRST_SEQUENCE
        self.expected = FIRST_SEQUENCE
        self.received = []
        # (sequence, message, sent at), oldest first; kept only when a clock is set.
        self.clock = None
        self.pending = []

    def send(self, payload):
        """-> the message carrying `payload`; with a clock set it is held for `due` until the
        peer's next-expected id passes it."""
        out = build(payload, self.sequence, self.expected)
        if self.clock is not None:
            self.pending.append((self.sequence, out, self.clock()))
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        return out

    def receive(self, data):
        """-> [payload] to send in answer: an ack for a payload, nothing for an ack."""
        m = parse(data)
        if m is None:
            return []
        self.pending = [p for p in self.pending
                        if ((p[0] - m["expected"]) & 0xFFFFFFFF) < 0x80000000]
        if not m["size"]:
            return []
        if m["sequence"] == self.expected:
            self.expected = (self.expected + 1) & 0xFFFFFFFF
            self.received.append(m["payload"])
        return [build_ack(self.expected)]

    def due(self, now):
        """-> pending messages older than RETRANSMIT_AFTER, byte for byte as first sent, as a
        retail station repeats them; their clock restarts."""
        out = []
        for i, (seq, msg, at) in enumerate(self.pending):
            if now - at >= self.RETRANSMIT_AFTER:
                out.append(msg)
                self.pending[i] = (seq, msg, now)
        return out
