"""The reliable streams a Scarlet / Violet station runs, and the records they carry.

Measured on a retail pair from the moment the second console associated (sv11). There is no
Session protocol, no Clone protocol and no Reliable 0x7C: the host announces both stations in a
broadcast Net 0x11 and the mesh is those two protocols alone.

    0x80  BroadcastReliable         ports 0, 1, 2
    0x81  StreamBroadcastReliable   ports 0 to 7

Every station acknowledges all eleven about once a second, whether or not anything came on them.
A station opens two of them with an INITIALIZED data message and then sends its records on the port
that is its own station index: the host on 0, the first joiner on 1, which is the convention
`pokeldn.pla.data_exchange` reads for Legends Arceus.

    station          opens                  sends records on
    host (index 0)   0x81 port 1 and 5      0x81 port 0
    joiner (index 1) 0x81 port 0 and 4      0x81 port 1

A record is zlib with a 4 KB window, so its first two bytes are `484b`, and the reliable message
carries FLAG_ZLIB with it.
"""

from pokeldn.ldn import reliable5

# The Pia MESSAGE flags both retail stations put on each kind of message (sv11). They are not the
# establishing flag 0x01 the Arceus host uses: at this band 0x01 skips the station lookup and sets
# no wake bit, so a message carrying it is parsed and never wakes the session.
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
# The two ports each station opens, and the eleven-byte payload each open carries. The second
# payload states the port it opens in its first two bytes; the first does not.
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


def build_ack(highest, our_next_seq, station_index, *, unknown0=0, stream_id=0,
              entry_count=ACK_ENTRIES, destination_bits=3):
    """The bulk ack, in the shape both retail stations send.

    `highest` maps a station index to the highest sequence received from it on this stream; entry k
    acknowledges station k with one past that, and every entry's station byte is zero.

    `entry_count` and `destination_bits` are sweep handles: a retail station sends four entries and
    a three-bit destination bitmap, and the only message a Scarlet guest has been seen to accept on
    this path carried one entry and no bitmap (`docs/sv.md`).
    """
    entries = [dict(stream_id=0, ack_id=highest.get(k, 0) + 1, field_0x50=highest.get(k, 0) + 1)
               for k in range(entry_count)]
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


def build_record_message(record, sequence_id, station_index, *, lowest_pending=1, stream_id=0):
    """A compressed record as one reliable message: the retail flags are START, END and ZLIB."""
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END | reliable5.FLAG_ZLIB)
    header = reliable5.build_header(flags, sequence_id, len(record), lowest_pending=lowest_pending,
                                    stream_id=stream_id, destination_bits=3,
                                    bitmap=[bitmap_for(station_index)])
    return header + bytes(record)


def compress(record, level=5, window_bits=12):
    """-> the record framed as the game frames one: zlib, 4 KB window, sync-flushed then finished.

    The same framing `pokeldn.pla.data_exchange` measured for Legends Arceus; a retail record's
    first two bytes are `484b`, which is that window size in the zlib header.
    """
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
