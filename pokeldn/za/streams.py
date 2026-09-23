"""The game's own stream layer: what rides on Reliable (10) and Broadcast Reliable (11).

Both protocols carry the sub-header `pokeldn.ldn.reliable` codes. What is true of this title is
the shape of a Broadcast Reliable payload: four bytes naming the sending station, then the
application data, and, on an acknowledgement, four station entries rather than the single entry a
unicast acknowledgement carries.

Measured on a reference pair's trade: the joiner prefixes 00000001 and the host 00000002. The
reliable sub-header's length on protocol 11 counts the bytes after the prefix, so a frame carries
four bytes more than it declares; a frame cut at the declared length is dropped by the host.
"""
from pokeldn.ldn import reliable

PROTO_RELIABLE = 10
PROTO_BROADCAST = 11

PREFIX_JOINER = bytes.fromhex("00000001")
PREFIX_HOST = bytes.fromhex("00000002")

ACK_STATIONS = 4                  # entries a broadcast acknowledgement carries
PREFIX_SIZE = 4                   # the station prefix, outside the sub-header's declared length
IDLE_NEXT = 0xFFF0                # the sequence base a station that has sent nothing reports


def build_ack(next_expected, mask=b"\x00" * 16):
    """The unicast acknowledgement of protocol 10: stream, marker, next expected, mask."""
    return reliable.build_bulk_ack(next_expected, mask)


def build_broadcast_ack(next_expected, mask=b"\x00" * 16, *, prefix=PREFIX_JOINER):
    """The acknowledgement of protocol 11: the prefix, then four 18-byte station entries, 78 bytes."""
    out = bytearray(prefix)
    out += bytes([0x00, ACK_STATIONS])
    out += (next_expected & 0xFFFF).to_bytes(2, "big") + bytes(mask).ljust(16, b"\x00")[:16]
    for _ in range(ACK_STATIONS - 1):
        out += IDLE_NEXT.to_bytes(2, "big") + bytes(16)
    return bytes(out)


def build_broadcast(payload, *, prefix=PREFIX_JOINER):
    """Application data on protocol 11 carries the sending station's four bytes in front."""
    return bytes(prefix) + bytes(payload)


def frame(seq, ack, payload, flags_a, recipients):
    """A protocol-11 reliable frame: `payload` starts with the station prefix, which the declared
    length leaves out."""
    out = bytearray(reliable.build_reliable(seq, ack, payload, flagsA=flags_a,
                                            recipients=recipients))
    out[1:3] = (len(payload) - PREFIX_SIZE).to_bytes(2, "big")
    return bytes(out)


def frame_payload(message):
    """The whole payload of a received protocol-11 frame, prefix included."""
    return message[8:8 + int.from_bytes(message[1:3], "big") + PREFIX_SIZE]
