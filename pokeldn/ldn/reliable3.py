"""Pia 5.11's reliable sliding window - protocol 0x7C, where Let's Go's game data is.

The header is 24 bytes, not the 9 or 13 of 5.29-5.43 (`reliable5`), and the sequence ids are 32
bits and start at 0xFFFFF82F on both stations. Measured between two Let's Go Pikachu endpoints:
the joiner sends a 376-byte payload once the clone elements are up, the host acknowledges it with
a header and no payload and sends its own of the same size.

    0x00  1  flags
    0x01  1  stream id, 3 for the game's stream and 0 on an acknowledgement
    0x02  2  payload size, big-endian
    0x04  4  zero
    0x08  4  sequence id, big-endian
    0x0C  4  the next sequence id expected from the peer, big-endian
    0x10  8  zero
    0x18     the payload

An acknowledgement is the header alone with the stream and the size zero, and the peer's sequence
id plus one at 0x0C.
"""
import struct

PROTOCOL = 0x7C
HEADER_SIZE = 0x18
FIRST_SEQUENCE = 0xFFFFF82F
GAME_STREAM = 3
__all__ = ["PROTOCOL", "HEADER_SIZE", "FIRST_SEQUENCE", "GAME_STREAM", "build", "build_ack",
           "parse", "Window"]


def build(payload, sequence, expected, stream=GAME_STREAM, flags=0):
    """One reliable message: the 24-byte header and the payload after it."""
    return (struct.pack(">BBHIII", flags, stream, len(payload), 0, sequence & 0xFFFFFFFF,
            expected & 0xFFFFFFFF) + bytes(8) + bytes(payload))


def build_ack(expected):
    """The acknowledgement: the header alone, carrying the next sequence id we expect."""
    return build(b"", 0, expected, stream=0)


def parse(data):
    """-> dict of a reliable message's header fields and its payload, or None."""
    if len(data) < HEADER_SIZE:
        return None
    flags, stream, size, _, sequence, expected = struct.unpack_from(">BBHIII", data, 0)
    return {"flags": flags, "stream": stream, "size": size, "sequence": sequence,
            "expected": expected, "payload": data[HEADER_SIZE:HEADER_SIZE + size]}


class Window:
    """One station's side of the window: it sends payloads in order and acknowledges the peer's."""

    # a message the peer has not acknowledged goes again after this long. Over 120 messages to a
    # retail console none waited past 0.104 s, so this is a net under a lost datagram, not a pace.
    RETRANSMIT_AFTER = 0.5

    def __init__(self):
        self.sequence = FIRST_SEQUENCE
        self.expected = FIRST_SEQUENCE
        self.received = []
        # (sequence, message, sent at): what the peer has yet to acknowledge, oldest first. Kept
        # only when a clock is set: a station that never polls `due` holds nothing.
        self.clock = None
        self.pending = []

    def send(self, payload):
        """-> the message carrying `payload`, and move our sequence on. With a clock set the
        message is held for `due` until the peer's next-expected id passes it."""
        out = build(payload, self.sequence, self.expected)
        if self.clock is not None:
            self.pending.append((self.sequence, out, self.clock()))
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        return out

    def receive(self, data):
        """-> [payload] to send in answer: an acknowledgement of a payload, nothing for an ack.
        Every message from the peer carries the next id it expects, which settles our pending."""
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
        """-> the pending messages older than RETRANSMIT_AFTER, byte for byte as first sent, and
        their clock restarted. A retail station repeats an unacknowledged message the same way."""
        out = []
        for i, (seq, msg, at) in enumerate(self.pending):
            if now - at >= self.RETRANSMIT_AFTER:
                out.append(msg)
                self.pending[i] = (seq, msg, now)
        return out
