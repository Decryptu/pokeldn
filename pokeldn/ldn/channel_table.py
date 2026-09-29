"""Port 1 of the game's reliable channel: the channel table, each station's announcement of the
handler keys it has open. A station sends on a key only after its peer announced it open. Encoding:
the game's tagged serialisation (docs/pla.md, The channel table on port 1).
"""

import struct

TUPLE = 0xB9
KEY_SIZE = 8
STATE_OPEN = 1
STATE_CLOSED = 0


def encode_uint(value):
    if value < 0:
        raise ValueError("unsigned only")
    if value < 0x80:
        return bytes([value])
    if value < 0x100:
        return bytes([0x80, value])
    if value < 0x10000:
        return bytes([0x81]) + struct.pack("<H", value)
    if value < 0x100000000:
        return bytes([0x82]) + struct.pack("<I", value)
    return bytes([0x83]) + struct.pack("<Q", value)


def decode_uint(data, pos):
    """-> (value, next pos) of the unsigned integer at `pos`."""
    tag = data[pos]
    if tag < 0x80:
        return tag, pos + 1
    width = {0x80: 1, 0x81: 2, 0x82: 4, 0x83: 8}.get(tag)
    if width is None:
        raise ValueError(f"tag {tag:#04x} at {pos} is not an unsigned integer")
    end = pos + 1 + width
    if end > len(data):
        raise ValueError("integer runs past the end")
    return int.from_bytes(data[pos + 1:end], "little"), end


def _tuple(data, pos, fields):
    if pos >= len(data) or data[pos] != TUPLE:
        raise ValueError(f"expected a tuple at {pos}")
    count, pos = decode_uint(data, pos + 1)
    if count != fields:
        raise ValueError(f"a tuple of {count} fields at {pos}, expected {fields}")
    return pos


def build(entries):
    """-> the port-1 message announcing `entries`, each (key, opened)."""
    out = bytes([TUPLE]) + encode_uint(1) + encode_uint(len(entries))
    for key, opened in entries:
        key = bytes(key)
        if len(key) != KEY_SIZE:
            raise ValueError(f"a handler key is {KEY_SIZE} bytes, not {len(key)}")
        lo, hi = struct.unpack("<II", key)
        out += (bytes([TUPLE]) + encode_uint(2) + bytes([TUPLE]) + encode_uint(2)
                + encode_uint(lo) + encode_uint(hi)
                + encode_uint(STATE_OPEN if opened else STATE_CLOSED))
    return out


def parse(payload):
    """-> [(key, opened)] of a port-1 message. Raises ValueError on anything else."""
    data = bytes(payload)
    pos = _tuple(data, 0, 1)
    count, pos = decode_uint(data, pos)
    entries = []
    for _ in range(count):
        pos = _tuple(data, pos, 2)
        pos = _tuple(data, pos, 2)
        lo, pos = decode_uint(data, pos)
        hi, pos = decode_uint(data, pos)
        state, pos = decode_uint(data, pos)
        if state not in (STATE_OPEN, STATE_CLOSED):
            raise ValueError(f"key state {state}")
        entries.append((struct.pack("<II", lo, hi), state == STATE_OPEN))
    if pos != len(data):
        raise ValueError(f"{len(data) - pos} bytes after the last entry")
    return entries


def is_announcement(payload):
    """-> whether `payload` parses as a channel-table message."""
    try:
        parse(payload)
    except (ValueError, IndexError):
        return False
    return True
