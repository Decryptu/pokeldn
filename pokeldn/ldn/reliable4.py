"""Pia version 4's reliable sliding window: one header class for protocols 0x7C and 0x80, and
the fixed 32-slot, 0x260-byte ack payload. `reliable5` is 5.29-5.43's.

docs/pia.md, Version 4 and Protocol 0x80, the broadcast reliable window.
"""

import struct

from pokeldn.ldn import reliable5

PROTOCOL = reliable5.PROTOCOL             # 0x7C
MESSAGE_FLAGS = reliable5.MESSAGE_FLAGS
ACK_SEQUENCE = reliable5.ACK_SEQUENCE     # 0xFFFF; BDSP's, unmeasured at version 4

ACK_ENTRIES = 32                          # 0x0185bfb0: `cmp x8, #0x20` closes the loop
ACK_ENTRY_SIZE = 19                       # u8 stream id, u16be ack id, 16 mask bytes
ACK_PAYLOAD_SIZE = ACK_ENTRIES * ACK_ENTRY_SIZE            # 0x260, checked at 0x01859a84
MASK_SIZE = 16

__all__ = ["PROTOCOL", "MESSAGE_FLAGS", "ACK_SEQUENCE", "ACK_ENTRIES", "ACK_ENTRY_SIZE",
           "ACK_PAYLOAD_SIZE", "MASK_SIZE", "build_ack_payload", "parse_ack_payload",
           "BROADCAST_PROTOCOL", "BROADCAST_HEADER", "BROADCAST_ID_SIZE",
           "parse_broadcast_message", "parse_message", "build_header", "header_size",
           "build_message", "build_data_message", "MAX_PAYLOAD", "MAX_DESTINATIONS",
           "FLAG_APPLICATION_DATA", "FLAG_MESSAGE_START", "FLAG_MESSAGE_END",
           "FLAG_IS_INITIALIZED", "FIRST_DATA_FLAGS", "DATA_FLAGS", "FIRST_SEQUENCE",
           "max_payload_for", "build_ack_message"]


def build_ack_payload(ack_id, stream_id=0, mask=b"", slots=None, filler=0xFF):
    """The 0x260 bytes. `slots` is which of the 32 to fill; None fills them all, correct whichever
    station index the console reads. An unfilled slot carries stream id 0xFF, which matches no
    stream; the console's own leave 0 (`filler=0`), safe past `max_total`."""
    mask = bytes(mask).ljust(MASK_SIZE, b"\0")[:MASK_SIZE]
    if len(mask) != MASK_SIZE:
        raise ValueError(f"a mask is {MASK_SIZE} bytes")
    if not 0 <= ack_id <= 0xFFFF:
        raise ValueError(f"an ack id is a halfword, got {ack_id}")
    want = set(range(ACK_ENTRIES) if slots is None else slots)
    if not want <= set(range(ACK_ENTRIES)):
        raise ValueError(f"a slot is 0..{ACK_ENTRIES - 1}, got {sorted(want)}")
    out = bytearray()
    for i in range(ACK_ENTRIES):
        if i in want:
            out += bytes([stream_id & 0xFF]) + struct.pack(">H", ack_id) + mask
        else:
            out += bytes([filler & 0xFF]) + b"\0" * (ACK_ENTRY_SIZE - 1)
    assert len(out) == ACK_PAYLOAD_SIZE
    return bytes(out)


def parse_ack_payload(data):
    """-> [dict] of all 32 entries, in slot order."""
    if len(data) != ACK_PAYLOAD_SIZE:
        raise ValueError(f"a version-4 ack payload is {ACK_PAYLOAD_SIZE:#x} bytes, "
                         f"got {len(data):#x} - which is what the console refuses at 0x01859a84")
    return [{"slot": i, "stream_id": data[o], "ack_id": struct.unpack_from(">H", data, o + 1)[0],
             "mask": data[o + 3:o + ACK_ENTRY_SIZE]}
            for i, o in enumerate(range(0, ACK_PAYLOAD_SIZE, ACK_ENTRY_SIZE))]


def build_ack_message(ack_id, stream_id=0, mask=b"", slots=None, lowest_pending=1,
                     destinations=(), filler=0xFF):
    """Header and payload. `ack_id` is one more than the highest sequence id received; a control
    message goes out as sequence 0xFFFF. No destinations is what the receiver never filters."""
    body = build_ack_payload(ack_id, stream_id=stream_id, mask=mask, slots=slots, filler=filler)
    return build_header(0, ACK_SEQUENCE, len(body), lowest_pending=lowest_pending,
                        stream_id=stream_id, destinations=destinations) + body


# `nn::pia::transport::BroadcastReliableProtocol` (vfunc4 0x0184d880); always zlib-compressed.
# Decompressed, a console's is 625 bytes: `00 00 0260 ffff 0001 01 <our constant id>` then the 0x260
# ack payload (docs/pia.md, Protocol 0x80).
BROADCAST_PROTOCOL = 0x80
BROADCAST_HEADER = 9                      # before the destination ids
BROADCAST_ID_SIZE = 8


def parse_broadcast_message(data):
    """-> dict, one decompressed protocol-0x80 message: version 4's header, shared with 0x7C."""
    return parse_message(data)


# `ReliableSlidingWindow::MessageHeader` (GetSize 0x0184e480, Deserialize 0x0184e390, Serialize
# 0x0184e230): byte 0x8 counts eight-byte station ids. Receive checks at 0x01859338 (docs/pia.md,
# Version 4).
MAX_PAYLOAD = 0x588                       # 0x0184e3cc refuses 0x589 and above
MAX_DESTINATIONS = 31                     # 0x0184e404: `cmp x8, #0x20; b.lo`
RECEIVE_BUDGET = 0x57F                    # 0x0185952c: size <= 0x57F - 8 * count

FLAG_APPLICATION_DATA = reliable5.FLAG_APPLICATION_DATA     # 0x01
FLAG_MESSAGE_START = reliable5.FLAG_MESSAGE_START           # 0x02
FLAG_MESSAGE_END = reliable5.FLAG_MESSAGE_END               # 0x04
FLAG_IS_INITIALIZED = reliable5.FLAG_IS_INITIALIZED         # 0x08

# The first message on a stream must carry FLAG_IS_INITIALIZED or `0x01859ca0` drops it in silence;
# its stream id and sequence id become the window's (docs/pia.md, Version 4).
FIRST_DATA_FLAGS = (FLAG_APPLICATION_DATA | FLAG_MESSAGE_START | FLAG_MESSAGE_END
                    | FLAG_IS_INITIALIZED)                 # 0x0F
DATA_FLAGS = FLAG_APPLICATION_DATA | FLAG_MESSAGE_START | FLAG_MESSAGE_END   # 0x07

# A console's broadcast ack asked for sequence 1 in all 256 captured; `0x01859d20` takes the
# window's start from the first message, so 1 is a choice.
FIRST_SEQUENCE = 1


def max_payload_for(destinations=()):
    """-> the largest payload this many destinations leaves room for, at the receiver's bound."""
    return min(MAX_PAYLOAD, RECEIVE_BUDGET - BROADCAST_ID_SIZE * len(tuple(destinations)))


def header_size(destinations=()):
    """9, plus eight per destination id (`GetSize` 0x0184e480)."""
    return BROADCAST_HEADER + BROADCAST_ID_SIZE * len(tuple(destinations))


def build_header(flags, sequence_id, payload_size, lowest_pending=0, stream_id=0,
                 destinations=()):
    """`destinations` are station constant ids; () is everyone and is never filtered, a non-empty
    list is one the receiver must find itself in."""
    destinations = tuple(destinations)
    if len(destinations) > MAX_DESTINATIONS:
        raise ValueError(f"{len(destinations)} destinations; the console refuses 0x20 and above")
    if payload_size > max_payload_for(destinations):
        raise ValueError(f"payload {payload_size} with {len(destinations)} destinations; "
                         f"0x0185952c refuses anything over {max_payload_for(destinations)}")
    out = (bytes([flags & 0xFF, stream_id & 0xFF]) + struct.pack(">H", payload_size)
           + struct.pack(">H", sequence_id & 0xFFFF) + struct.pack(">H", lowest_pending & 0xFFFF)
           + bytes([len(destinations)]))
    return out + b"".join(struct.pack(">Q", d & 0xFFFFFFFFFFFFFFFF) for d in destinations)


def parse_message(data):
    """-> dict. One version-4 reliable message, either protocol, header and payload split."""
    if len(data) < BROADCAST_HEADER:
        raise ValueError(f"a version-4 reliable message is at least {BROADCAST_HEADER} bytes")
    count = data[8]
    head = BROADCAST_HEADER + count * BROADCAST_ID_SIZE
    if len(data) < head:
        raise ValueError(f"{count} destination ids need {head} bytes of header, got {len(data)}")
    size = struct.unpack_from(">H", data, 2)[0]
    out = {
        "flags": data[0], "flag_names": reliable5.flag_names(data[0]), "stream_id": data[1],
        "payload_size": size,
        "sequence_id": struct.unpack_from(">H", data, 4)[0],
        "lowest_pending": struct.unpack_from(">H", data, 6)[0],
        "destination_count": count,
        "destinations": [struct.unpack_from(">Q", data, BROADCAST_HEADER + i * BROADCAST_ID_SIZE)[0]
                         for i in range(count)],
        "header_size": head,
    }
    out["payload"] = data[head:head + size]
    out["truncated"] = len(out["payload"]) < size
    out["is_ack"] = not (data[0] & FLAG_APPLICATION_DATA)
    return out


def build_message(payload, flags, sequence_id, lowest_pending=0, stream_id=0, destinations=()):
    """Header and payload; the caller chooses the protocol."""
    payload = bytes(payload)
    return build_header(flags, sequence_id, len(payload), lowest_pending=lowest_pending,
                        stream_id=stream_id, destinations=destinations) + payload


def build_data_message(payload, sequence_id=FIRST_SEQUENCE, destinations=(), stream_id=0,
                       lowest_pending=None, first=None):
    """`first` opens the stream and defaults to `sequence_id == 1`. `lowest_pending` defaults to
    `sequence_id`, as the console sends on every message of its own."""
    if first is None:
        first = sequence_id == FIRST_SEQUENCE
    return build_message(payload, FIRST_DATA_FLAGS if first else DATA_FLAGS, sequence_id,
                         lowest_pending=sequence_id if lowest_pending is None else lowest_pending,
                         stream_id=stream_id, destinations=destinations)
