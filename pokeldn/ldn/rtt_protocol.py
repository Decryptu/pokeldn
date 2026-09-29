"""Pia's RTT Protocol (protocol 0x58), the round-trip timer the mesh runs under everything.

Version 9 (BDSP) is thirteen bytes; versions 4 (Sword) and 3 (Let's Go) are sixteen. Silence never
drops a station (docs/pia.md, "The RTT protocol").
"""

import struct

PROTOCOL = 0x58
VERSION = 3                       # 0x015ada18 returns 3, 0x015ada10 returns 0x58
PORT = 0
SIZE = 13                         # 0x015adab4: `mov w0, #0xd`
MESSAGE_FLAGS = 0x01              # what the console itself sends on this protocol

REQUEST = 0
RESPONSE = 1
KIND_NAMES = {REQUEST: "REQUEST", RESPONSE: "RESPONSE"}

ANY_TARGET = 0                    # 0x015ad000 accepts a target of 0 without comparing anything


def build(kind, timestamp, target=ANY_TARGET):
    """The thirteen bytes, in the order 0x015ada24 writes them."""
    return (bytes([kind & 0xFF]) + struct.pack(">Q", timestamp & ((1 << 64) - 1))
            + struct.pack(">I", target & 0xFFFFFFFF))


def parse(data):
    """-> dict. The console's own parser refuses anything shorter than thirteen bytes."""
    if len(data) < SIZE:
        raise ValueError(f"an RTT message is {SIZE} bytes, got {len(data)}: {data.hex()}")
    kind = data[0]
    return {"kind": kind, "name": KIND_NAMES.get(kind, f"unknown {kind:#04x}"),
            "timestamp": struct.unpack_from(">Q", data, 1)[0],
            "target": struct.unpack_from(">I", data, 9)[0]}


# Version 4 (Sword/Shield): sixteen bytes, parser 0x0185d2a0 (`mov w3, #0x10` at 0x0185d320). [0]
# kind, [8] a rising big-endian u64; bytes 1..7 are zero in every request seen and unknown. The
# console sends to destination 2 (station index 1) where BDSP broadcasts.
SIZE_V4 = 0x10                    # 0x0185d320: `mov w3, #0x10`
TIMESTAMP_OFF_V4 = 8              # the only field the wire distinguishes


def parse_v4(data):
    """Only what sixteen bytes of a version-4 RTT message distinguish."""
    if len(data) != SIZE_V4:
        raise ValueError(f"a version-4 RTT message is {SIZE_V4} bytes, got {len(data)}: "
                         f"{data.hex()}")
    kind = data[0]
    return {"kind": kind, "name": KIND_NAMES.get(kind, f"unknown {kind:#04x}"),
            "timestamp": struct.unpack_from(">Q", data, TIMESTAMP_OFF_V4)[0],
            "unread": data[1:TIMESTAMP_OFF_V4]}


def response_for_v4(data):
    """The request's own sixteen bytes with the kind set to 1: bytes 1..7 are unread, so they are
    echoed rather than given an invented layout."""
    if len(data) != SIZE_V4:
        raise ValueError(f"a version-4 RTT message is {SIZE_V4} bytes, got {len(data)}")
    if data[0] != REQUEST:
        raise ValueError(f"only a request is answered, this is kind {data[0]:#04x}")
    return bytes([RESPONSE]) + data[1:]


def response_for(data, target=ANY_TARGET):
    """-> the answer to an RTT request, or None. Built like 0x015ad024's, with target 0, which the
    receiver accepts without comparison (0x015ad000)."""
    if len(data) < SIZE or data[0] != REQUEST:
        return None
    return build(RESPONSE, struct.unpack_from(">Q", data, 1)[0], target)


# Version 3 (Let's Go, Pia 5.11): sixteen bytes, the kind a big-endian u32 at [0], the sender's 19.2
# MHz tick at [8], echoed by the response (docs/lgpe_session.md).
SIZE_V3 = 0x10
TIMESTAMP_OFF_V3 = 8
TICK_HZ_V3 = 19_200_000


def build_v3(kind, timestamp):
    """The sixteen bytes: the kind as a big-endian u32, four zero bytes, the timestamp u64."""
    return struct.pack(">IIQ", kind & 0xFFFFFFFF, 0, timestamp & ((1 << 64) - 1))


def parse_v3(data):
    if len(data) < SIZE_V3:
        raise ValueError(f"a version-3 RTT message is {SIZE_V3} bytes, got {len(data)}: "
                         f"{data.hex()}")
    kind = struct.unpack_from(">I", data, 0)[0]
    return {"kind": kind, "name": KIND_NAMES.get(kind, f"unknown {kind:#x}"),
            "timestamp": struct.unpack_from(">Q", data, TIMESTAMP_OFF_V3)[0]}


def response_for_v3(data):
    """The request's own bytes with the kind set to 1, or None if this is not a request."""
    if len(data) < SIZE_V3 or struct.unpack_from(">I", data, 0)[0] != REQUEST:
        return None
    return struct.pack(">I", RESPONSE) + bytes(data[4:SIZE_V3])
