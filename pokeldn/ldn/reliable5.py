"""Pia 5.29-5.43's reliable sliding window, protocol 0x7c, where BDSP's game data is; version 4
(Sword) parses with no change. `reliable.py` is Pia 6.32's, a different header.

Header, ack payload and receive discards: docs/pia.md, The reliable sliding window (0x7c).
"""

import struct

PROTOCOL = 0x7C
VERSION = 3                       # the wiki pins version 3 to Pia 5.31-5.43
PORT = 0
MESSAGE_FLAGS = 0x01              # what the console itself sends on this protocol

HEADER_SIZE = 9                   # plus 4 bytes per bitmap word
MAX_PAYLOAD = 0x5A0               # 0x0159756c refuses 0x5a1 and above
MAX_DESTINATION_BITS = 31         # `cmp #0x20 / b.lo`; the wiki says 32
MAX_ACK_ENTRIES = 32              # `cmp #0x21 / b.lo`
ACK_ENTRY_SIZE = 21               # 0x0159716c: n * 0x14 + n + 2

FLAG_APPLICATION_DATA = 0x01
FLAG_MESSAGE_START = 0x02
FLAG_MESSAGE_END = 0x04
FLAG_IS_INITIALIZED = 0x08
FLAG_ZLIB = 0x10
# On a reset, byte 1 is a counter that must be the stored one plus one (0x0159fa24, 0x0159fa4c),
# and the station's record[0x1f] must be non-zero (0x0159f9b4); a mismatch is dropped in silence.
FLAG_RESET = 0x20
FLAG_RESET_ACK = 0x40
FLAG_NAMES = [(FLAG_APPLICATION_DATA, "APPLICATION_DATA"), (FLAG_MESSAGE_START, "START"),
              (FLAG_MESSAGE_END, "END"), (FLAG_IS_INITIALIZED, "INITIALIZED"),
              (FLAG_ZLIB, "ZLIB"), (FLAG_RESET, "RESET"), (FLAG_RESET_ACK, "RESET_ACK")]


def flag_names(flags):
    """-> the set bits, named."""
    out = [name for bit, name in FLAG_NAMES if flags & bit]
    rest = flags & ~sum(bit for bit, _ in FLAG_NAMES)
    if rest:
        out.append(f"unknown {rest:#04x}")
    return out


def header_size(destination_bits):
    """9, or 13 once there is a bitmap: the console's own arithmetic."""
    return HEADER_SIZE + (((destination_bits + 0x1F) >> 3) & 0x3C)


def build_header(flags, sequence_id, payload_size, lowest_pending=0, stream_id=0,
                 destination_bits=0, bitmap=()):
    if destination_bits > MAX_DESTINATION_BITS:
        raise ValueError(f"{destination_bits} destination bits; the console refuses 0x20 and above")
    if payload_size > MAX_PAYLOAD:
        raise ValueError(f"payload {payload_size}; the console refuses 0x5a1 and above")
    out = (bytes([flags & 0xFF, stream_id & 0xFF]) + struct.pack(">H", payload_size)
           + struct.pack(">H", sequence_id & 0xFFFF) + struct.pack(">H", lowest_pending & 0xFFFF)
           + bytes([destination_bits & 0xFF]))
    words = (header_size(destination_bits) - HEADER_SIZE) // 4
    bitmap = list(bitmap) + [0] * (words - len(bitmap))
    return out + b"".join(struct.pack(">I", w & 0xFFFFFFFF) for w in bitmap[:words])


def parse(data):
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a reliable message is at least {HEADER_SIZE} bytes, got {len(data)}")
    size = struct.unpack_from(">H", data, 2)[0]
    if size > MAX_PAYLOAD:
        raise ValueError(f"payload size {size:#x} is 0x5a1 or more, which the console refuses")
    bits = data[8]
    if bits > MAX_DESTINATION_BITS:
        raise ValueError(f"{bits} destination bits is 0x20 or more, which the console refuses")
    head = header_size(bits)
    out = {
        "flags": data[0],
        "flag_names": flag_names(data[0]),
        "stream_id": data[1],
        "payload_size": size,
        "sequence_id": struct.unpack_from(">H", data, 4)[0],
        "lowest_pending": struct.unpack_from(">H", data, 6)[0],
        "destination_bits": bits,
        "bitmap": [struct.unpack_from(">I", data, HEADER_SIZE + 4 * i)[0]
                   for i in range((head - HEADER_SIZE) // 4)],
        "header_size": head,
    }
    out["payload"] = data[head:head + size]
    out["truncated"] = len(out["payload"]) < size
    out["is_ack"] = not (data[0] & FLAG_APPLICATION_DATA)
    return out


def parse_ack_payload(data):
    """-> dict, the bulk ack a message with no APPLICATION_DATA flag carries."""
    if len(data) < 2:
        raise ValueError(f"an ack payload is at least two bytes, got {len(data)}")
    count = data[1]
    if count > MAX_ACK_ENTRIES:
        raise ValueError(f"{count} ack entries is 0x21 or more, which the console refuses")
    entries, off = [], 2
    for _ in range(count):
        if off + ACK_ENTRY_SIZE > len(data):
            break
        entries.append({"stream_id": data[off],
                        "ack_id": struct.unpack_from(">H", data, off + 1)[0],
                        "field_0x50": struct.unpack_from(">H", data, off + 3)[0],
                        "mask": data[off + 5:off + 21]})
        off += ACK_ENTRY_SIZE
    return {"unknown0": data[0], "count": count, "entries": entries}


ACK_SEQUENCE = 0xFFFF             # a control message has no sequence of its own


def contiguous_through(sequence_ids, start=0):
    """-> the highest id such that every id from `start` + 1 up to it has been received; a gap
    stops the run."""
    have = set(sequence_ids)
    through = start
    while through + 1 in have:
        through += 1
    return through


def build_ack_message(ack_id, stream_id=0, field_0x50=None, mask=b"", lowest_pending=None,
                      unknown0=0):
    """A whole bulk-ack message as the console sends it: `ack_id` is one more than the highest
    sequence received. Trap: the defaults stand in for the sender's own lowest unacknowledged
    sequence, which the peer advances its window to; pass your own (docs/pia.md)."""
    if field_0x50 is None:
        field_0x50 = max(0, ack_id - 1)
    body = build_ack_payload([{"stream_id": stream_id, "ack_id": ack_id,
                               "field_0x50": field_0x50, "mask": mask}], unknown0=unknown0)
    return build_header(0, ACK_SEQUENCE, len(body),
                        lowest_pending=ack_id if lowest_pending is None else lowest_pending,
                        stream_id=stream_id) + body


def build_ack_payload(entries, unknown0=0):
    """The bulk ack, 2 + 21 per entry. `unknown0` is byte 0, 0 in every captured ack."""
    if len(entries) > MAX_ACK_ENTRIES:
        raise ValueError(f"{len(entries)} ack entries; the console refuses 0x21 and above")
    out = bytes([unknown0 & 0xFF, len(entries)])
    for e in entries:
        mask = bytes(e.get("mask", b"")).ljust(16, b"\0")[:16]
        out += (bytes([e.get("stream_id", 0) & 0xFF])
                + struct.pack(">H", e["ack_id"] & 0xFFFF)
                + struct.pack(">H", e.get("field_0x50", 0) & 0xFFFF) + mask)
    return out


class Reassembler:
    """A receiver's message layer: fragments joined per stream in sequence order, and a sequence id
    already delivered refused. A console resends a message whose ack it did not get; acting on the
    copy answers it twice (docs/bdsp_trade.md, the check-ok)."""

    def __init__(self):
        self.fragments, self.delivered = {}, {}

    def reset(self):
        self.fragments.clear()
        self.delivered.clear()

    def take(self, d):
        """`d` from `parse`, application data. -> ("repeat", None), ("partial", None) or
        ("message", payload)."""
        stream, seq = d["stream_id"], d["sequence_id"]
        delivered = self.delivered.setdefault(stream, set())
        if seq in delivered:
            return "repeat", None
        frag = self.fragments.setdefault(stream, {})
        if d["flags"] & FLAG_MESSAGE_START:
            frag.clear()
        frag[seq] = d["payload"]
        if not d["flags"] & FLAG_MESSAGE_END:
            return "partial", None
        payload = b"".join(frag[k] for k in sorted(frag))
        delivered.update(frag)
        frag.clear()
        return "message", payload


def set_lowest_pending(message, lowest):
    """-> `message` with its header's lowest-pending field replaced. The receiver walks its base up
    to it over empty slots and then discards what arrives below (Arceus `0x74c250`, Scarlet
    `0x6eff28`), so a sender never declares more than its own lowest unacknowledged sequence."""
    return bytes(message[:6]) + struct.pack(">H", lowest & 0xFFFF) + bytes(message[8:])


MASK_BITS = 128                   # 0x74f284: offsets past 0x7f are never released by the mask


def build_mask(held, ack_id):
    """-> the sixteen-byte acknowledgement mask: bit `seq - ack_id - 1` for each held sequence.
    Four little-endian words: Arceus copies the bytes as stored (`0x742da0`) and reads a word at a
    time (`0x74f2a0`). docs/pla.md, Acknowledgement."""
    bits = 0
    for seq in held:
        if 0 <= seq - ack_id - 1 < MASK_BITS:
            bits |= 1 << (seq - ack_id - 1)
    return bits.to_bytes(16, "little")


class ReceiveWindow:
    """One peer stream as the console's own window receives it: messages handed over in sequence
    order, a gap holding everything behind it, a sequence already taken refused. The acknowledgement
    is `next` with the held ones in `mask()` (`0x74ee1c`, docs/pla.md, Acknowledgement)."""

    def __init__(self, start=1):
        self.next, self.held = start, {}

    def take(self, seq, message):
        """-> the messages now deliverable, in order; empty for a repeat or one behind a gap."""
        if seq >= self.next:
            self.held.setdefault(seq, message)
        out = []
        while self.next in self.held:
            out.append(self.held.pop(self.next))
            self.next += 1
        return out

    def mask(self):
        return build_mask(self.held, self.next)


class SendWindow:
    """A sender's data messages, each kept until the peer's acknowledgement releases it and due
    again every `interval` seconds until then. The release rule is the console's (`0x74f0ec`):
    below the ack id, or above it with its mask bit set. Trap: a resend keeps its sequence id."""

    def __init__(self, interval):
        self.interval, self.pending = interval, {}     # (stream, seq) -> [item, last sent]

    def sent(self, stream, seq, item, now):
        self.pending[(stream, seq)] = [item, now]

    def acked(self, stream, ack_id, mask=b""):
        """-> the sequences released on `stream`. An id of 0 applies nothing (`0x74f0fc`)."""
        if not ack_id:
            return []
        bits = int.from_bytes(bytes(mask).ljust(16, b"\0")[:16], "little")
        gone = sorted(seq for s, seq in self.pending if s == stream and (
            seq < ack_id or (0 <= seq - ack_id - 1 < MASK_BITS and bits >> (seq - ack_id - 1) & 1)))
        for seq in gone:
            del self.pending[(stream, seq)]
        return gone

    def lowest(self, stream, default):
        """-> the lowest sequence unacknowledged on `stream`, else `default`: the most a message's
        lowest-pending field may declare (docs/pia.md, What the receiver discards in silence)."""
        return min((seq for s, seq in self.pending if s == stream), default=default)

    def due(self, now):
        """-> [(stream, seq, item)] unacknowledged for `interval`, in order; each is due again."""
        out = []
        for (stream, seq), entry in sorted(self.pending.items(), key=lambda kv: kv[0]):
            if now - entry[1] >= self.interval:
                entry[1] = now
                out.append((stream, seq, entry[0]))
        return out

    def forget(self, drop):
        """Drop every stream `drop(stream)` is true of: a peer that rejoined restarts at 1."""
        self.pending = {k: v for k, v in self.pending.items() if not drop(k[0])}
