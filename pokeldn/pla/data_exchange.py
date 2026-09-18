"""The data exchange Legends Arceus runs on Stream Broadcast Reliable, and the record it carries.

The trade scene is the success branch of the game's matching sequence, and the sequence completes
when this exchange completes. Each station opens the 0x81 stream, sends one record of its own, and
acknowledges its peer's. A station sends its record only after it has received the peer's, so a host
that never sends one leaves the joiner's sequence outstanding until its ten-second deadline. The
frame is `pokeldn.ldn.reliable5`, the same sliding window this band uses on 0x7c.

    port          the SENDER's station index: the host sends on 0, the first joiner on 1
    bitmap        the destination station mask, with one declared destination bit: 0x02 to the
                  joiner, 0x01 to the host
    sequence id   1, with the message-start, message-end and initialized flags and FLAG_ZLIB

The record is zlib with a 4 KB window, level 5, sync-flushed and then finished, which reproduces a
reference host's 61 compressed bytes byte for byte. It decompresses to 139 bytes that are identical
in both directions of a pair and across separate sessions, so nothing in it is session-derived: it
is the player the game shows as the trade partner. What each field means beyond the two below is
unread, so a record is built from the reference and those two are written into it.

    +0x1b  4   player id, as stored
    +0x2b  26  player name, UTF-16 little-endian, NUL-padded

The name's extent is the run of bytes to the next non-zero field at +0x47 and is not measured
against a second name. `docs/pla.md`, The data exchange.
"""

import zlib

from pokeldn.ldn import reliable5

PROTOCOL = 0x81                   # StreamBroadcastReliable
HOST_PORT = 0                     # the sender's station index
JOINER_PORT = 1
SEQUENCE_ID = 1                   # both stations send their record as their stream's seq 1

ZLIB_LEVEL = 5                    # with WINDOW_BITS, reproduces the reference record exactly
ZLIB_WINDOW_BITS = 12

RECORD_SIZE = 139
PLAYER_ID_OFFSET = 0x1B
PLAYER_ID_SIZE = 4
NAME_OFFSET = 0x2B
NAME_SIZE = 26                    # to the next non-zero field; not measured against a second name

STREAM_OPEN_PAYLOAD = bytes.fromhex("0000000000008000000000")

# The record a reference host sent, decompressed. Identical in both directions of a pair and across
# two sessions, so it carries no session state. `docs/pla.md`, The data exchange.
REFERENCE_RECORD = bytes.fromhex(
    "010064000000000000008000000000000000000000000000000000879df3062f0000"
    "0200000000000000004600720065006500530068006b00720065006c006900000000"
    "00000005000000000000000000000000000000000000000100000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000"
    "000000")


def compress(record):
    """-> the record as the game frames it: zlib, 4 KB window, level 5, sync-flushed then finished.

    A plain `zlib.compress` differs in the header and the trailer; this is byte for byte what a
    reference host sent.
    """
    c = zlib.compressobj(ZLIB_LEVEL, zlib.DEFLATED, ZLIB_WINDOW_BITS)
    return c.compress(bytes(record)) + c.flush(zlib.Z_SYNC_FLUSH) + c.flush(zlib.Z_FINISH)


def decompress(payload):
    """-> the record behind a 0x81 content message's payload."""
    return zlib.decompress(bytes(payload))


def build_record(player_id=None, name=None, template=REFERENCE_RECORD):
    """-> the 139-byte record, the reference with the player id and name written into it.

    `player_id` is four bytes or an int stored as they are; `name` is written UTF-16 little-endian
    and NUL-padded. A name longer than the field raises rather than truncating into the next field.
    """
    record = bytearray(template)
    if len(record) != RECORD_SIZE:
        raise ValueError(f"a record is {RECORD_SIZE} bytes, not {len(record)}")
    if player_id is not None:
        if isinstance(player_id, int):
            player_id = player_id.to_bytes(PLAYER_ID_SIZE, "little")
        if len(player_id) != PLAYER_ID_SIZE:
            raise ValueError(f"a player id is {PLAYER_ID_SIZE} bytes, not {len(player_id)}")
        record[PLAYER_ID_OFFSET:PLAYER_ID_OFFSET + PLAYER_ID_SIZE] = player_id
    if name is not None:
        encoded = str(name).encode("utf-16-le")
        if len(encoded) > NAME_SIZE:
            raise ValueError(f"{name!r} is {len(encoded)} bytes, past the {NAME_SIZE}-byte field")
        record[NAME_OFFSET:NAME_OFFSET + NAME_SIZE] = encoded.ljust(NAME_SIZE, b"\0")
    return bytes(record)


def read_record(record):
    """-> {player_id, name} from a decompressed record."""
    record = bytes(record)
    name = record[NAME_OFFSET:NAME_OFFSET + NAME_SIZE].decode("utf-16-le", "replace")
    return dict(player_id=record[PLAYER_ID_OFFSET:PLAYER_ID_OFFSET + PLAYER_ID_SIZE],
                name=name.split("\0")[0])


def build_stream_open(destination_bitmap, sequence_id=SEQUENCE_ID):
    """-> the message a station opens its 0x81 stream with, before any record crosses."""
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END | reliable5.FLAG_IS_INITIALIZED)
    return (reliable5.build_header(flags, sequence_id, len(STREAM_OPEN_PAYLOAD),
                                   lowest_pending=sequence_id, stream_id=0, destination_bits=1,
                                   bitmap=[destination_bitmap]) + STREAM_OPEN_PAYLOAD)


def build_content_message(record, destination_bitmap, sequence_id=SEQUENCE_ID):
    """-> the 0x81 message carrying a record: the compressed record under the ZLIB flag."""
    payload = compress(record)
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END | reliable5.FLAG_IS_INITIALIZED | reliable5.FLAG_ZLIB)
    return (reliable5.build_header(flags, sequence_id, len(payload), lowest_pending=sequence_id,
                                   stream_id=0, destination_bits=1,
                                   bitmap=[destination_bitmap]) + payload)


def build_ack_message(ack_ids, destination_bitmap, lowest_pending=1, station_index=0):
    """-> the 0x81 acknowledgement: one entry per id, as the reference host sends two.

    The reference acknowledges ids 1 and 2 with the window's own field at 1 and an empty mask, under
    a thirteen-byte header carrying the destination bitmap the content messages carry.
    """
    entries = [dict(stream_id=station_index, ack_id=i, field_0x50=lowest_pending) for i in ack_ids]
    payload = reliable5.build_ack_payload(entries)
    return (reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                   lowest_pending=lowest_pending, stream_id=0, destination_bits=1,
                                   bitmap=[destination_bitmap]) + payload)
