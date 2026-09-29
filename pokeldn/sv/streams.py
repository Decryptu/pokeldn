"""The reliable streams a Scarlet / Violet station runs (0x80 ports 0-2, 0x81 ports 0-7) and the
zlib records they carry; a station sends records on the 0x81 port of its own index (docs/sv.md,
The eleven streams).
"""

from pokeldn.ldn import reliable5

# Both retail stations' flags. At this band 0x01 skips the station lookup and sets no wake bit: such
# a message is parsed and never wakes the session.
MESSAGE_FLAGS_RTT = 0x00
MESSAGE_FLAGS_DATA = 0x00
MESSAGE_FLAGS_ACK = 0xA0

PROTOCOL_BROADCAST = 0x80
PROTOCOL_STREAM = 0x81
BROADCAST_PORTS = (0, 1, 2)
STREAM_PORTS = (0, 1, 2, 3, 4, 5, 6, 7)
ACK_ENTRIES = 4                   # four, whatever the station count
HOST_INDEX = 0
JOINER_INDEX = 1
# The second open payload states its port in its first two bytes; the first does not.
OPEN_PORTS = {HOST_INDEX: (1, 5), JOINER_INDEX: (0, 4)}
OPEN_PAYLOAD_LOW = bytes.fromhex("0000000000f38800000000")
ZLIB_HEADER = bytes.fromhex("484b")


def open_payload(port):
    """-> the eleven bytes the INITIALIZED open on this port carries."""
    if port in (0, 1):
        return OPEN_PAYLOAD_LOW
    return bytes([0, port]) + bytes.fromhex("00000ff00800000000")


def every_stream():
    """-> (protocol, port) for all eleven streams, in the order a station sends them."""
    return ([(PROTOCOL_BROADCAST, p) for p in BROADCAST_PORTS]
            + [(PROTOCOL_STREAM, p) for p in STREAM_PORTS])


def bitmap_for(station_index):
    """The destination bitmap a station writes: the bit of the station it is talking to."""
    return 1 << (1 - station_index)


def ack_position(received, peer_lowest_pending=1):
    """-> (through, mask): what a retail station acknowledges of one peer's stream; ids below the
    peer's lowest pending count as held (docs/sv.md, The retail acknowledgement)."""
    have = set(received) | set(range(1, peer_lowest_pending))
    through = reliable5.contiguous_through(have)
    mask = bytearray(16)
    for seq in have:
        bit = seq - through - 2
        if 0 <= bit < 128:
            mask[bit // 8] |= 1 << (bit % 8)
    return through, bytes(mask)


def build_ack(highest, our_next_seq, station_index, *, unknown0=0, stream_id=0,
              entry_count=ACK_ENTRIES, destination_bits=3, masks=None):
    """The bulk ack in the retail shape: entry k acknowledges station k with one past `highest[k]`.
    `entry_count` and `destination_bits` are sweep handles; retail sends 4 entries, 3 bits."""
    masks = masks or {}
    entries = [dict(stream_id=0, ack_id=highest.get(k, 0) + 1, field_0x50=highest.get(k, 0) + 1,
                    mask=masks.get(k, b"")) for k in range(entry_count)]
    payload = reliable5.build_ack_payload(entries, unknown0=unknown0)
    header = reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                    lowest_pending=our_next_seq, stream_id=stream_id,
                                    destination_bits=destination_bits,
                                    bitmap=[bitmap_for(station_index)] if destination_bits else ())
    return header + payload


def build_open(port, station_index, *, sequence_id=1):
    """The INITIALIZED data message that opens one of a station's two streams."""
    payload = open_payload(port)
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END | reliable5.FLAG_IS_INITIALIZED)
    header = reliable5.build_header(flags, sequence_id, len(payload), lowest_pending=1,
                                    stream_id=0, destination_bits=3,
                                    bitmap=[bitmap_for(station_index)])
    return header + payload


def build_record_message(record, sequence_id, station_index, *, lowest_pending=1, stream_id=0,
                         initialized=False):
    """A compressed record as one reliable message (START, END, ZLIB); a station's first record on a
    stream carries INITIALIZED too, flags 0x1F then 0x17."""
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END | reliable5.FLAG_ZLIB
             | (reliable5.FLAG_IS_INITIALIZED if initialized else 0))
    header = reliable5.build_header(flags, sequence_id, len(record), lowest_pending=lowest_pending,
                                    stream_id=stream_id, destination_bits=3,
                                    bitmap=[bitmap_for(station_index)])
    return header + bytes(record)


def compress(record, level=5, window_bits=12):
    """-> the record as the game frames one: zlib, 4 KB window, sync-flushed then finished."""
    import zlib

    deflate = zlib.compressobj(level, zlib.DEFLATED, window_bits)
    return deflate.compress(bytes(record)) + deflate.flush(zlib.Z_SYNC_FLUSH) + deflate.flush()


def decompress(payload):
    """-> the record behind a ZLIB-flagged message's payload."""
    import zlib

    return zlib.decompressobj().decompress(bytes(payload))


def build_rtt_request(timestamp8):
    """An 11-byte RTT request: kind 0, eight bytes of clock, target 0."""
    return bytes([0]) + bytes(timestamp8)[:8].rjust(8, b"\0") + b"\0\0"


def build_rtt_response(payload, peer_var):
    """The answer a retail station sends: kind 1, the requester's clock, target its variable id."""
    return bytes([1]) + bytes(payload)[1:9] + (peer_var & 0xFFFF).to_bytes(2, "big")


def parse_send_spec(hx):
    """-> (data, flags) of a HEX[:z][:start|:end] send spec: `:z` marks a payload already zlib,
    `:start`/`:end` a fragment opening or closing a message."""
    flags = 0
    parts = hx.split(":")
    hx = parts[0]
    for suffix in parts[1:]:
        if suffix == "z":
            flags |= reliable5.FLAG_ZLIB
        elif suffix == "start":
            flags |= reliable5.FLAG_MESSAGE_START
        elif suffix == "end":
            flags |= reliable5.FLAG_MESSAGE_END
        else:
            raise ValueError(f"unknown send suffix :{suffix}")
    if not flags & (reliable5.FLAG_MESSAGE_START | reliable5.FLAG_MESSAGE_END):
        flags |= reliable5.FLAG_MESSAGE_START | reliable5.FLAG_MESSAGE_END
    return bytes.fromhex(hx), flags | reliable5.FLAG_APPLICATION_DATA
