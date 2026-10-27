"""The data exchange Legends Arceus runs on Stream Broadcast Reliable (0x81), and its record.

A station sends its record only after receiving the peer's; the frame is `pokeldn.ldn.reliable5`.
The record is zlib (4 KB window, level 5) of 139 bytes; the reference one here is the same in both
directions and across sessions, a retail save's carries its own trainer. It holds the save's MyStatus block from +0x0b (PKHeX MyStatus8a): the player id at +0x1b,
version +0x1f, gender +0x20, language +0x22, the UTF-16 name at +0x2b and the look at +0x47. A host
writes the player id, the name and the gender, and the look follows the gender (docs/pla.md).
"""

import zlib

from pokeldn.ldn import reliable5
from pokeldn import trainer_language

PROTOCOL = 0x81                   # StreamBroadcastReliable
HOST_PORT = 0                     # the sender's station index
JOINER_PORT = 1
SEQUENCE_ID = 1

ZLIB_LEVEL = 5                    # with WINDOW_BITS, reproduces a reference host's 61 bytes
ZLIB_WINDOW_BITS = 12

RECORD_SIZE = 139
PLAYER_ID_OFFSET = 0x1B
PLAYER_ID_SIZE = 4
NAME_OFFSET = 0x2B
NAME_SIZE = 26                    # to the next non-zero field; one name measured
VERSION_OFFSET, GENDER_OFFSET, LANGUAGE_OFFSET = 0x1F, 0x20, 0x22
LOOK_OFFSET = 0x47                # u32, the intro's grid_player cell: column + 4 * row
LOOK_SIZE = 4
FEMALE_COLUMNS = 0b10             # columns 2 and 3 are the female player's, 0 and 1 the male's

STREAM_OPEN_PAYLOAD = bytes.fromhex("0000000000008000000000")

# A reference host's record, decompressed.
REFERENCE_RECORD = bytes.fromhex(
    "010064000000000000008000000000000000000000000000000000879df3062f0000"
    "0200000000000000004600720065006500530068006b00720065006c006900000000"
    "00000005000000000000000000000000000000000000000100000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000000000"
    "000000")


def compress(record):
    """-> the record as the game frames it: zlib, 4 KB window, level 5, sync-flushed then finished;
    a plain `zlib.compress` differs in the header and trailer."""
    c = zlib.compressobj(ZLIB_LEVEL, zlib.DEFLATED, ZLIB_WINDOW_BITS)
    return c.compress(bytes(record)) + c.flush(zlib.Z_SYNC_FLUSH) + c.flush(zlib.Z_FINISH)


def decompress(payload):
    """-> the record behind a 0x81 content message's payload."""
    return zlib.decompress(bytes(payload))


def look_for(look, gender):
    """-> the look of the same skin for the gender (0 male, 1 female): the female player's cell is
    two columns past the male's."""
    return (look & ~FEMALE_COLUMNS) | (FEMALE_COLUMNS if gender else 0)


def build_record(player_id=None, name=None, gender=None, template=REFERENCE_RECORD):
    """-> the 139-byte reference record with the player id, name and gender written, and the look
    moved to the gender's player with the same skin; a name longer than the field raises."""
    record = bytearray(template)
    if len(record) != RECORD_SIZE:
        raise ValueError(f"a record is {RECORD_SIZE} bytes, not {len(record)}")
    if gender is not None:
        if gender not in (0, 1):
            raise ValueError(f"a gender is 0 or 1, not {gender!r}")
        look = look_for(int.from_bytes(record[LOOK_OFFSET:LOOK_OFFSET + LOOK_SIZE], "little"), gender)
        record[GENDER_OFFSET] = gender
        record[LOOK_OFFSET:LOOK_OFFSET + LOOK_SIZE] = look.to_bytes(LOOK_SIZE, "little")
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
        record[LANGUAGE_OFFSET] = trainer_language.for_name(str(name), record[LANGUAGE_OFFSET])
    return bytes(record)


def read_record(record):
    """-> {player_id, name} from a decompressed record."""
    record = bytes(record)
    name = record[NAME_OFFSET:NAME_OFFSET + NAME_SIZE].decode("utf-16-le", "replace")
    return dict(player_id=record[PLAYER_ID_OFFSET:PLAYER_ID_OFFSET + PLAYER_ID_SIZE],
                name=name.split("\0")[0])


def read_trainer(record):
    """-> the trainer a decompressed record names, as pokeldn.receiver_gift takes it: id pair, version,
    gender, language and name."""
    record = bytes(record)
    if len(record) != RECORD_SIZE:
        raise ValueError(f"a record is {RECORD_SIZE} bytes, not {len(record)}")
    player = read_record(record)
    tid = int.from_bytes(player["player_id"][:2], "little")
    sid = int.from_bytes(player["player_id"][2:], "little")
    return {"ot": player["name"], "tid": tid, "sid": sid, "version": record[VERSION_OFFSET],
            "gender": record[GENDER_OFFSET], "language": record[LANGUAGE_OFFSET]}


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
    """-> the 0x81 acknowledgement, one entry per id, as the reference acks ids 1 and 2."""
    entries = [dict(stream_id=station_index, ack_id=i, field_0x50=lowest_pending) for i in ack_ids]
    payload = reliable5.build_ack_payload(entries)
    return (reliable5.build_header(0, reliable5.ACK_SEQUENCE, len(payload),
                                   lowest_pending=lowest_pending, stream_id=0, destination_bits=1,
                                   bitmap=[destination_bitmap]) + payload)
