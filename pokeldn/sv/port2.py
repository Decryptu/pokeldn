"""Port 2 of the game's reliable protocols: the type-7 announcement a host relays, the type-3 join
and the type-9 answer (dispatcher `0x1954aec`). Tagged encoding as `pokeldn.pla.channel_table`,
plus `0xbc` for a byte string (docs/sv.md, Port 2).
"""

import struct
import zlib

from pokeldn.ldn.channel_table import TUPLE, decode_uint, encode_uint

BYTES = 0xBC
LIST = 0xBA
TYPE_JOIN = 3
TYPE_SESSION = 6
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


def build_announce(host_station_id, kind=1, capacity=2, zero=0, key=0):
    """-> the inflated type-7 body a pair's host broadcasts first, 167 bytes. `key` is the relay's
    count of type 1s relayed since its queues were reset (`0x12fbef0`); a join must name it."""
    inner = (encode_uint(kind) + encode_uint(capacity) + encode_uint(zero)
             + encode_bytes(bytes(JOIN_BLOB_SIZE)) + encode_bytes(bytes(ANNOUNCE_BLOB_SIZE))
             + encode_uint(0))
    outer = (bytes([TUPLE]) + encode_uint(6) + inner + encode_uint(key) + encode_uint(0)
             + bytes([TUPLE]) + encode_uint(1) + encode_u64(host_station_id) + encode_uint(0))
    return (bytes([TYPE_ANNOUNCE, TUPLE]) + encode_uint(1)
            + bytes([TUPLE]) + encode_uint(5) + outer)


def build_session(host_station_id, kind=5, capacity=4):
    """-> the type 6 a raid host sends on 0x7C port 2 after the seat: the type 7's session block
    under kind 5, then the four slots, the host's station in the first (docs/sv_raid.md)."""
    session = (bytes([TUPLE]) + encode_uint(6) + encode_uint(kind) + encode_uint(capacity)
               + encode_uint(0) + encode_bytes(bytes(JOIN_BLOB_SIZE))
               + encode_bytes(bytes(ANNOUNCE_BLOB_SIZE)) + encode_uint(0))
    block = (bytes([TUPLE]) + encode_uint(5) + session + encode_uint(0) + encode_uint(0)
             + bytes([TUPLE]) + encode_uint(1) + encode_u64(host_station_id) + encode_uint(0))
    slots = (bytes([LIST]) + encode_uint(capacity)
             + bytes([TUPLE]) + encode_uint(1) + encode_u64(host_station_id)
             + (bytes([TUPLE]) + encode_uint(1) + encode_uint(0)) * (capacity - 1))
    return (bytes([TYPE_SESSION, TUPLE]) + encode_uint(5) + block + slots
            + encode_bytes(bytes(4)) + encode_uint(1) + encode_uint(0))


def _skip_field(data, pos):
    if data[pos] == BYTES:
        size, pos = decode_uint(data, pos + 1)
        return pos + size
    return decode_uint(data, pos)[1]


def announce_key(body):
    """-> the key of an inflated type 7, the first integer after its six-tuple, or None. The type-3
    handler `0x1981ed4` refuses a join whose first field differs, with code 1."""
    try:
        if body[0] != TYPE_ANNOUNCE:
            return None
        pos = 1
        for count in (1, 5, 6):
            if body[pos] != TUPLE:
                return None
            n, pos = decode_uint(body, pos + 1)
            if n != count:
                return None
        for _ in range(6):
            pos = _skip_field(body, pos)
        return decode_uint(body, pos)[0]
    except (ValueError, IndexError):
        return None


def build_join(key=0):
    """-> the type-3 join answering an announcement under `key`."""
    return (bytes([TYPE_JOIN, TUPLE]) + encode_uint(2) + encode_uint(key)
            + encode_bytes(bytes(JOIN_BLOB_SIZE)))


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
