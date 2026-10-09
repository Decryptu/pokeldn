"""The LZ4 block format, without frame or checksum: what a Tera Raid's `0x012f` message carries after
its 18-byte header (docs/sv_raid.md, The battle bootstrap). The game decompresses any valid block.
"""

MIN_MATCH = 4
LAST_LITERALS = 5          # the format's end rule: the last five bytes are literals
MATCH_LIMIT = 12           # and no match starts in the last twelve
MAX_OFFSET = 0xFFFF


def _length(out, value):
    while value >= 255:
        out.append(255)
        value -= 255
    out.append(value)


def compress(raw):
    """-> one block: greedy matches found through a table of four-byte prefixes."""
    raw = bytes(raw)
    out, table = bytearray(), {}
    anchor = i = 0
    while i < len(raw) - MATCH_LIMIT:
        key = raw[i:i + MIN_MATCH]
        candidate, table[key] = table.get(key), i
        if candidate is None or i - candidate > MAX_OFFSET:
            i += 1
            continue
        length = MIN_MATCH
        while i + length < len(raw) - LAST_LITERALS and raw[candidate + length] == raw[i + length]:
            length += 1
        literals = i - anchor
        out.append(min(literals, 15) << 4 | min(length - MIN_MATCH, 15))
        if literals >= 15:
            _length(out, literals - 15)
        out += raw[anchor:i]
        out += (i - candidate).to_bytes(2, "little")
        if length - MIN_MATCH >= 15:
            _length(out, length - MIN_MATCH - 15)
        i = anchor = i + length
    literals = len(raw) - anchor
    out.append(min(literals, 15) << 4)
    if literals >= 15:
        _length(out, literals - 15)
    out += raw[anchor:]
    return bytes(out)


def decompress(block, size):
    """-> exactly `size` bytes, or ValueError for a malformed block."""
    out, i = bytearray(), 0
    try:
        while True:
            token = block[i]
            i += 1
            literals = token >> 4
            if literals == 15:
                while block[i] == 255:
                    literals += 255
                    i += 1
                literals += block[i]
                i += 1
            out += block[i:i + literals]
            i += literals
            if i >= len(block):
                break
            offset = int.from_bytes(block[i:i + 2], "little")
            i += 2
            length = token & 15
            if length == 15:
                while block[i] == 255:
                    length += 255
                    i += 1
                length += block[i]
                i += 1
            start = len(out) - offset
            if offset == 0 or start < 0:
                raise ValueError(f"match offset {offset} outside the output")
            for k in range(length + MIN_MATCH):
                out.append(out[start + k])
    except IndexError:
        raise ValueError("the block ends inside a sequence") from None
    if len(out) != size:
        raise ValueError(f"the block holds {len(out)} bytes, not {size}")
    return bytes(out)
