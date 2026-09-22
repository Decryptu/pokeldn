"""Port 2 of the game's reliable protocols: the announcement a host relays and the join it answers.

The game's messages on 0x7C port 2 (one station) and 0x80 port 2 (every station) share one
dispatcher, `0x1954aec`, keyed on the first byte, types 1 to 0xD. Three of them open a trade:

    type 7   host -> all, 0x80 port 2, zlib     the host's announcement: a relayed type 1
    type 3   joiner -> host, 0x7C port 2        the join, a slot byte and nine zero bytes
    type 9   host -> all, 0x80 port 2           the answer, carrying the joiner's station id

The type-1 handler `0x18ceb70` copies the 0x8e-byte body, appends the sender's station id and
queues it as a type 7, so a host announcing alone relays its own. The type-3 handler `0x1981e94`
queues the type 9; its receiver `0x18b65c8` compares the id in it with the station's own, at
`[[0x46d0a08]] + 0xb8`. That id is the Pia constant id read as a big-endian u64: the 127.0.0.2
instance of a pair carries `7f00020000020000`, `ldn_constant_id` of its MAC `02:00:7f:00:00:02`.

The encoding is the tagged one `pokeldn.pla.channel_table` describes, plus `0xbc` for a byte string:
the tag, the length as an integer, the bytes. `docs/sv.md`, Port 2.
"""

import struct
import zlib

from pokeldn.pla.channel_table import TUPLE, decode_uint, encode_uint

BYTES = 0xBC
TYPE_JOIN = 3
TYPE_ANNOUNCE = 7
TYPE_ACCEPT = 9

JOIN_BLOB_SIZE = 9
ANNOUNCE_BLOB_SIZE = 128


def station_id(constant_id):
    """-> the u64 the game calls a station: the eight constant-id bytes read big-endian."""
    cid = bytes(constant_id)
    if len(cid) != 8:
        raise ValueError(f"a constant id is 8 bytes, not {len(cid)}")
    return int.from_bytes(cid, "big")


def encode_bytes(data):
    return bytes([BYTES]) + encode_uint(len(data)) + bytes(data)


def encode_u64(value):
    """The station id always goes out at full width, tag 0x83, whatever its value."""
    return bytes([0x83]) + struct.pack("<Q", value)


def build_announce(host_station_id, slot=1, kind=2, state=0):
    """-> the inflated type-7 body a pair's host broadcasts first, 167 bytes."""
    inner = (encode_uint(slot) + encode_uint(kind) + encode_uint(state)
             + encode_bytes(bytes(JOIN_BLOB_SIZE)) + encode_bytes(bytes(ANNOUNCE_BLOB_SIZE))
             + encode_uint(0))
    outer = (bytes([TUPLE]) + encode_uint(6) + inner + encode_uint(0) + encode_uint(0)
             + bytes([TUPLE]) + encode_uint(1) + encode_u64(host_station_id) + encode_uint(0))
    return (bytes([TYPE_ANNOUNCE, TUPLE]) + encode_uint(1)
            + bytes([TUPLE]) + encode_uint(5) + outer)


def deflate_announce(body):
    """-> the body as the wire carries it: zlib, 4 KB window, the same as the records."""
    c = zlib.compressobj(level=6, wbits=12)
    return c.compress(body) + c.flush()


def parse_join(data):
    """-> the slot byte of a type-3 join, or None when `data` is not one."""
    if len(data) < 6 or data[0] != TYPE_JOIN or data[1] != TUPLE:
        return None
    count, pos = decode_uint(data, 2)
    if count != 2:
        return None
    slot, pos = decode_uint(data, pos)
    if pos >= len(data) or data[pos] != BYTES:
        return None
    size, pos = decode_uint(data, pos + 1)
    if size != JOIN_BLOB_SIZE or len(data) != pos + size:
        return None
    return slot


def build_accept(joiner_station_id, slot=0, code=0):
    """-> the type-9 answer, 16 bytes: the slot the join named, the result, the joiner's id."""
    return (bytes([TYPE_ACCEPT, TUPLE]) + encode_uint(3) + encode_uint(slot) + encode_uint(code)
            + bytes([TUPLE]) + encode_uint(1) + encode_u64(joiner_station_id))
