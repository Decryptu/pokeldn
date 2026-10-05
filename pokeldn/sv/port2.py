"""Port 2 of the game's reliable protocols: the type-7 announcement a host relays, the type-3 join
and the type-9 answer (dispatcher `0x1954aec`). Tagged encoding as `pokeldn.pla.channel_table`,
plus `0xbc` for a byte string (docs/sv.md, Port 2).
"""

import struct
import zlib

from pokeldn.ldn.channel_table import TUPLE, decode_uint, encode_uint

BYTES = 0xBC
TYPE_JOIN = 3
TYPE_ANNOUNCE = 7
TYPE_ACCEPT = 9

JOIN_BLOB_SIZE = 9
ANNOUNCE_BLOB_SIZE = 128

# The channel declarations a Scarlet Tera Raid host sent before accepting a player.  Port 1
# declares the raid's two application keys (0x8033 and 0x8034).  Port 2 is the relay setup; its
# captured station id occurs twice and is replaced by build_raid_open().
RAID_CHANNEL_TABLE = bytes.fromhex(
    "b90106b902b9027b0001b902b902320101b902b902320201b902b902320301"
    "b902b90280803301b902b90280803401")
_RAID_OPEN_STATION = bytes.fromhex("000048f1c751b3eb")
_RAID_OPEN_TEMPLATE = zlib.decompress(bytes.fromhex(
    "484b62dbc90a846cac2c0c7b381960604f4303c3c0839d8ccd0c0c1e1f8f076e7ecdb08b0589b79391"
    "0182f6b080d4313200000000ffff0300e24412d1"))

# The host's first lobby-state records after its two type-9 accepts.  Delay is from the type-3
# join, the boolean is the reliable ZLIB flag, and the bytes are the wire payload (compressed when
# flagged).  Records 1-3 describe the raid and its metadata; 4 onward drive the lobby countdown.
RAID_LOBBY_MESSAGES = (
    (0.12, True, bytes.fromhex(
        "484b6a30d6616c6200011d060478c18c603301b1208ccd01a18da17c00000000ffff0300850902ca")),
    (0.12, False, bytes.fromhex(
        "80332d018300000000000c00000000000000080000000400040004000000")),
    (0.12, False, bytes.fromhex(
        "80332e018400000000005801000000000000c05959b70000e383a974c4283165"
        "a64c8a1135f75d114e9a7f6df2ed5664f484f065a5303d5d9ba363bee5fe3c76"
        "1b5a192dada9d6c65a99ae710b0b31a823b791f058d48a3bb2dc13b21c8a97f7"
        "da49fae91d3ed1a147ffc63dfa389d4277c68a711e8b7ae253e04c4b32d07b9b"
        "94638bbc149af24f655e5eab91583253832edaeb7c2d5b72ae97ec3e7a9be34a"
        "39bd696a1ab71d5084ba63be82a91a0d35a6be9bb0823acee26595d07e6e96da"
        "ea6df6da2736e544e7995b6e0a563ce1678abacdabab4f195238d89e0500d2d44"
        "aefc0e4f4f169440c11347813056c45c0f6728bb0d824269f96fe7899cbc2e1d8"
        "8ab2221b8d9327b7e6192ec56972a10492fdb171467d2da8b23f29049f0bff960"
        "ce6be7402dddae87b79478ad392e27bed907be8517aa19178a8474d2f005cb581"
        "37451835eaade00300b10abec22ddd6aa7724f081187b89ee174b8285665ab4c9"
        "b1125f752114e9a")),
    (0.56, False, bytes.fromhex(
        "8033300185000000000014000000000000000c0000000000060008000400060000008f000000")),
    (1.59, False, bytes.fromhex(
        "8033300186000000000014000000000000000c0000000000060008000400060000008e000000")),
    (2.56, True, bytes.fromhex(
        "484b6a30d6656c670001090608e001936c409a054832303042c501000000ffff03003e6201aa")),
    (2.58, False, bytes.fromhex(
        "8033300188000000000014000000000000000c0000000000060008000400060000008d000000")),
    (3.56, False, bytes.fromhex(
        "8033300189000000000014000000000000000c0000000000060008000400060000008c000000")),
    (4.59, False, bytes.fromhex(
        "803330018a000000000014000000000000000c0000000000060008000400060000008b000000")),
    (5.64, False, bytes.fromhex(
        "803330018b000000000014000000000000000c0000000000060008000400060000008a000000")),
    (6.69, False, bytes.fromhex(
        "803330018c000000000014000000000000000c00000000000600080004000600000089000000")),
    (7.48, True, bytes.fromhex(
        "484b6a30d665ec650001090608e001936c409a0548c2f80c0c00000000ffff03003f9e01bb")),
)


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


def build_raid_open(host_station_id):
    """-> the raid relay's initial port-2 configuration for this host station."""
    packed = struct.pack("<Q", host_station_id)
    if _RAID_OPEN_TEMPLATE.count(_RAID_OPEN_STATION) != 2:
        raise AssertionError("the raid-open template must contain two station ids")
    return _RAID_OPEN_TEMPLATE.replace(_RAID_OPEN_STATION, packed)
