"""The game's own stream layer: what rides on Reliable (10) and Broadcast Reliable (11).

Both protocols carry the sub-header `pokeldn.ldn.reliable` codes. What is true of this title is
the shape of a Broadcast Reliable payload: four bytes naming the sending station, then the
application data, and, on an acknowledgement, four station entries rather than the single entry a
unicast acknowledgement carries.

Measured on a reference pair's trade: the joiner prefixes 00000001 and the host 00000002, and a
broadcast acknowledgement is 74 bytes whose last entry is cut short of its mask.
"""
from pokeldn.ldn import reliable

PROTO_RELIABLE = 10
PROTO_BROADCAST = 11

PREFIX_JOINER = bytes.fromhex("00000001")
PREFIX_HOST = bytes.fromhex("00000002")

ACK_STATIONS = 4                  # entries a broadcast acknowledgement carries
ACK_SIZE = 74                     # and its total size, the last entry short of its mask
BROADCAST_TAIL = bytes(4)         # every protocol-11 message runs 4 bytes past its declared length
IDLE_NEXT = 0xFFF0                # the sequence base a station that has sent nothing reports


def build_ack(next_expected, mask=b"\x00" * 16):
    """The unicast acknowledgement of protocol 10: stream, marker, next expected, mask."""
    return reliable.build_bulk_ack(next_expected, mask)


def build_broadcast_ack(next_expected, mask=b"\x00" * 16, *, prefix=PREFIX_JOINER):
    """The 74-byte acknowledgement of protocol 11: our own entry, then the idle stations'."""
    out = bytearray(prefix)
    out += bytes([0x00, ACK_STATIONS])
    out += (next_expected & 0xFFFF).to_bytes(2, "big") + bytes(mask).ljust(16, b"\x00")[:16]
    for _ in range(ACK_STATIONS - 1):
        out += IDLE_NEXT.to_bytes(2, "big") + bytes(16)
    return bytes(out[:ACK_SIZE])


def build_broadcast(payload, *, prefix=PREFIX_JOINER):
    """Application data on protocol 11 carries the sending station's four bytes in front."""
    return bytes(prefix) + bytes(payload)
