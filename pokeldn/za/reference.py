"""The game messages a reference Legends Z-A joiner sends, recorded from an emulated pair whose
player is Player: identity10 on protocol 10; open11, identity11 and identity11b on 11; the 1211-byte selection
record (docs/za.md). identity11b is stored with the joiner's four-byte station prefix. `named` puts
another player name in an identity.
"""
import os
import struct
import zlib

from pokeldn.ldn.channel_table import TUPLE, decode_uint

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
NAMES = ("identity10", "open11", "identity11", "identity11b", "selection")
BYTES = 0xBC
NAME_SIZE = 26     # twelve UTF-16 characters and a terminator (docs/za.md, The game's own exchange)


def load(name, directory=DIR):
    with open(os.path.join(directory, f"{name}.bin"), "rb") as fh:
        return fh.read()


def _expect(data, pos, tag, count=None):
    if pos >= len(data) or data[pos] != tag:
        raise ValueError(f"expected tag {tag:#04x} at {pos}")
    value, pos = decode_uint(data, pos + 1)
    if count is not None and value != count:
        raise ValueError(f"tag {tag:#04x} at {pos} holds {value}, expected {count}")
    return value, pos


def name_offset(identity, prefix=0):
    """-> where the player name of a 1400 identity starts; `prefix` bytes of station prefix lead it."""
    if identity[prefix:prefix + 2] != b"\x14\x00":
        raise ValueError("not a 1400 identity")
    _, pos = _expect(identity, prefix + 2, TUPLE, 2)
    _, pos = decode_uint(identity, pos)
    _, pos = _expect(identity, pos, TUPLE, 1)
    _, pos = _expect(identity, pos, BYTES)
    _, pos = _expect(identity, pos, TUPLE, 6)
    for _ in range(3):
        _, pos = decode_uint(identity, pos)
    _, pos = _expect(identity, pos, BYTES, NAME_SIZE)
    return pos


def named(identity, name, prefix=0):
    """-> `identity` with its player called `name`, at most twelve characters."""
    raw = name.encode("utf-16-le")
    if not name or len(raw) > NAME_SIZE - 2:
        raise ValueError(f"a Z-A player name is 1 to {(NAME_SIZE - 2) // 2} characters, not {name!r}")
    at = name_offset(identity, prefix)
    return identity[:at] + raw.ljust(NAME_SIZE, b"\0") + identity[at + NAME_SIZE:]


def sync_message(identity, prefix=0):
    """-> the 1403 SyncDataSet for a 1400 identity: crc32(le32(fnv1a32(value))) over its one value
    (`0xc4b270`, docs/za.md, The game's own exchange). A stale one stalls the console before 0100."""
    at = name_offset(identity, prefix) - 11      # b906 82<u32> 01 02 bc1a, then the name
    if identity[at - 2:at] != b"\xbc\x5d":
        raise ValueError("not a 1400 identity with a 0x5d-byte value")
    h = 0x811C9DC5
    for c in identity[at:at + 0x5D]:
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return b"\x14\x03\xb9\x01\x82" + struct.pack("<I", zlib.crc32(struct.pack("<I", h)))


def player_name(identity, prefix=0):
    at = name_offset(identity, prefix)
    return identity[at:at + NAME_SIZE].decode("utf-16-le").split("\0", 1)[0]
