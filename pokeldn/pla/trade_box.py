"""The trade box: the Pokemon a station shows and the Pokemon it offers, on the game's channel.

Once both stations have opened the game's own channel (`pokeldn.pla.game_channel`) the trade screen
is up and the game's own messages cross on port 0 behind the eight-zero-byte handler key. The
receive handler is `main_111.bin` 0x26da310: it reads a selector and a counter, switches on the
selector through the table at 0x397e388, and drops anything above 7.

    1   the station is ready                 sets [net+0x78], which is what step 0x20 waits on
    2   the Pokemon it is SHOWING            stored at [net+0x98] and nothing else happens
    3   -> 0x26d93c8
    4   the Pokemon it is OFFERING           stored at [net+0xb0], sets the phase [net+0xbc] to 3
    5   -> 0x26da2c0, behind a counter check
    6   the offer is made                    sets the phase to 2 and bumps the counter at [net+0xf8]
    7   behind the same counter check        sets the phase to 5

Selectors 2 and 4 carry a record and are the same shape; the difference is which slot it lands in
and whether the phase moves. A station entering the box sends 2 on its own, and sends 4 when the
player offers the Pokemon up, so an answer has to carry the selector it is answering: a station that
answers an offer with a showing leaves the offer slot empty and the screen waiting.

The body is the game's own tagged encoding, read by 0x26dac6c for the selector, 0x26662fc for the
counter and 0x26dacbc for the record. A byte under 0x80 is itself; 0x81 introduces a halfword; 0xbc
introduces the record.

    0x00  1   the selector
    0x01  1   the counter, 0 on both record-carrying selectors
    0x02  1   0xbc, which 0x26da3b0 and 0x26da3f0 test for by hand before deserialising
    0x03  1   0x81, a halfword length follows
    0x04  2   the record's length, 0x178
    0x06  376 the record, encrypted as `pokeldn.pla.pokemon` encrypts it

The message is flags 0x07 - application data, message start, message end, no initialized bit, no
zlib - at sequence 2 with the window's lowest pending id at 2 and no destination bitmap, which is
the plain `reliable5` shape the channel opens use.

THE RECORD-CARRYING MESSAGE IS NOT SESSION STATE. A console sent the same one byte for byte in two
sessions on two machines, minutes apart, against two different hosts and two different session keys,
so nothing in it is derived from the session, the peer or the clock: it is a function of the save.

`docs/pla.md`, The trade box.
"""

import struct

from pokeldn.ldn import reliable5
from pokeldn.pla import game_channel, pokemon

PROTOCOL = game_channel.PROTOCOL           # 0x7c, the game's own reliable channel
PORT = game_channel.HOST_PORT              # 0, the channel the zero key routes on
SEQUENCE_ID = 2                            # the channel's opens are sequence 1

SELECTOR_READY = 1
SELECTOR_SHOWING = 2
SELECTOR_OFFERING = 4
SELECTOR_CONFIRMING = 5
SELECTOR_OFFER_MADE = 6
RECORD_SELECTORS = (SELECTOR_SHOWING, SELECTOR_OFFERING)
# The selectors a station answers with the same two bytes it was sent. 1 is the channel open, which
# `game_channel` answers on its own; the rest are the steps past the offer.
MIRRORED_SELECTORS = (3, SELECTOR_CONFIRMING, SELECTOR_OFFER_MADE, 7)

HEADER_SIZE = 6
BLOB_TAG = 0xBC                            # what 0x26da3b0 compares the byte against
HALFWORD_TAG = 0x81                        # 0x2666338: 0x80 introduces a byte, 0x81 a halfword

# The record a console offered, off the wire: a level-70 Azelf whose trainer is the trainer the
# data exchange names. Encrypted, exactly as it was sent.
REFERENCE_RECORD = bytes.fromhex(
    "e8828cbb0000f46cc4d3af03b395951ab88552c6e7794a95912cd0ce7d151ef57a50d213457dee2d"
    "75bf3099a41e1c25099396dbf74f2f7c699a1ef951b923f3b8f9aa19ee23e11659f4afdbab819dc5"
    "ffbc44c936f74a944343781a9fea890b3d81834072f9cd80d29cbd19562d4eeb325a179febb79cd2"
    "b3776989028805afd5a80948b227d51bd8a8e51e8fc289f94bead06edc7025bf00bd306a8ca45420"
    "23fd89b5bc99f1ea8d9ffdc016a251da5aaff3d78af0fb90f9901b2d5b8a0e88679d4c68c252361b"
    "0c6c907488a7b20dbf5edc9b923e3f38e93e002b6d3c61384e086b275db5d34b022f05d825fa1286"
    "faf6c52b39ee536fdfb0d82eadbdc1af25f03d32a017a943b2bc3e0a3ef59fbbc58f2739026ed7ca"
    "283df108d45f34ace4065dd022d653a64705f26f2c7591b51f2abb45b557adc99077931df613ab39"
    "28d0a3e1d61bd59130b42bcf58ecd820bb807a3354c0f5e4250149f56aba56c2ce70296e32ba7c21"
    "60d24403c208ec1c970fa2c659794895")

# The identity written into a record of the host's own. Both values are arbitrary: their only job is
# that the record offered is not the record the console itself is holding.
OUR_ENCRYPTION_CONSTANT = 0x504B4C44
OUR_PID = 0x4E444C4B


def build_our_record(player_id, name, template=REFERENCE_RECORD):
    """-> a record of the host's own: the template under a new trainer and a new identity.

    `player_id` is the four bytes the data exchange carries as the player id, which is the record's
    trainer id and secret id in that order, so the two messages describe one player the way a
    console's own two do. The species, the level and everything else stay the template's.
    """
    plain = pokemon.decrypt(bytes(template))
    trainer_id, secret_id = struct.unpack("<HH", bytes(player_id))
    return pokemon.encrypt(pokemon.write(
        plain, trainer_id=trainer_id, secret_id=secret_id, ot_name=name,
        encryption_constant=OUR_ENCRYPTION_CONSTANT, pid=OUR_PID))


def build_payload(record=REFERENCE_RECORD, selector=SELECTOR_OFFERING, counter=0):
    """-> the channel message's payload: the zero key, the six-byte header and the record."""
    record = bytes(record)
    if len(record) != pokemon.SIZE_PARTY:
        raise ValueError(f"a trade box record is {pokemon.SIZE_PARTY} bytes, not {len(record)}")
    if selector not in RECORD_SELECTORS:
        raise ValueError(f"selector {selector} does not carry a record")
    if not 0 <= counter < 0x80:
        raise ValueError(f"counter {counter} is past what a single byte encodes")
    return (bytes(game_channel.KEY_SIZE)
            + bytes([selector, counter, BLOB_TAG, HALFWORD_TAG])
            + struct.pack("<H", len(record)) + record)


def build_message(record=REFERENCE_RECORD, sequence_id=SEQUENCE_ID, **header):
    """-> the whole 0x7c message that shows or offers `record`."""
    payload = build_payload(record, **header)
    flags = (reliable5.FLAG_APPLICATION_DATA | reliable5.FLAG_MESSAGE_START
             | reliable5.FLAG_MESSAGE_END)
    return (reliable5.build_header(flags, sequence_id, len(payload), lowest_pending=sequence_id,
                                   stream_id=0) + payload)


def read_payload(payload):
    """-> {selector, counter, record} of a channel message, or None if it carries no record."""
    payload = bytes(payload)
    key, body = game_channel.split_message(payload)
    if key != bytes(game_channel.KEY_SIZE) or len(body) < HEADER_SIZE:
        return None
    selector, counter, tag, length_tag = body[:4]
    if selector not in RECORD_SELECTORS or tag != BLOB_TAG or length_tag != HALFWORD_TAG:
        return None
    size = struct.unpack_from("<H", body, 4)[0]
    record = body[HEADER_SIZE:HEADER_SIZE + size]
    if len(record) != size or size not in (pokemon.SIZE_STORED, pokemon.SIZE_PARTY):
        return None
    return dict(selector=selector, counter=counter, record=record)


def read_selector(payload):
    """-> (selector, body) of a game-channel message behind the zero key, or None.

    Every message on this channel that the trade handler reads is the zero key, a selector byte and
    the rest. The record-carrying selectors go through `read_payload`; the others are two bytes and
    are answered as they stand.
    """
    payload = bytes(payload)
    key, body = game_channel.split_message(payload)
    if key != bytes(game_channel.KEY_SIZE) or not body:
        return None
    return body[0], body


def selector_name(selector):
    return {SELECTOR_READY: "ready", SELECTOR_SHOWING: "showing",
            SELECTOR_OFFERING: "offering", SELECTOR_CONFIRMING: "confirming",
            SELECTOR_OFFER_MADE: "offer made"}.get(selector, f"selector {selector}")


def describe(record):
    """-> a one-line account of what a record offers, for a log a person reads."""
    try:
        fields = pokemon.read(pokemon.decrypt(record))
    except ValueError as exc:
        return f"unreadable record ({exc})"
    level = fields.get("level")
    return (f"species {fields['species']} {fields['nickname']!r}"
            + (f" level {level}" if level else "")
            + f" of {fields['ot_name']!r} (id {fields['trainer_id']})")


# THE PHASE PROTOCOL, on its own handler key.
#
# The job that carries the trade out is created at the trade object's sub-state 7, and the game
# registers this key on the fly at the same moment. The job's state machine advances on phases the
# two stations announce here, and the object it announces through keeps three pairs of fields:
#
#     [obj+0x94] / [obj+0x96]   the phase this station has announced, written by 0x26d7d8c
#     [obj+0x98] / [obj+0x9a]   the phase the peer has announced, written on receiving selector 1
#     [obj+0x90] / [obj+0x92]   written by 0x26d7e84, and on receiving selector 2
#
# The two senders are the same eight instructions apart from the selector they write, and the
# receive handler at 0x26d7f90 is the mirror image: selector 1 fills the peer pair, selector 2 fills
# the third pair. The job's state 2 arm asks `0x26d7e5c(obj, 3)`, which is the third pair holding 3,
# so a station gets past state 2 only once its peer has announced selector 2.
#
# SELECTOR 2 IS THE HOST'S TO SEND. `0x26d7e84` is reached only behind `[obj+0x78]`, a flag written
# once at job creation by `0x26d7aa0` from a predicate that ignores its argument and compares the
# station against the session's host station. On a joiner it is zero and stays zero, so a joiner
# never sends selector 2 and its own job cannot leave state 2. The host owes it.
PHASE_KEY = bytes.fromhex("0100000000000000")
PHASE_SELECTOR_MINE = 1            # 0x26d7d8c: the phase a station announces for itself
PHASE_SELECTOR_HOST = 2            # 0x26d7e84: the same, from the host only


def read_phase(payload):
    """-> (selector, phase) of a phase message, or None if it is not one.

    The body is the selector and the phase, each a byte while it is under 0x80, which is the
    encoding `pokeldn.pla.trade_box`'s record messages use for their own first two fields.
    """
    key, body = game_channel.split_message(bytes(payload))
    if key != PHASE_KEY or len(body) != 2:
        return None
    if body[0] not in (PHASE_SELECTOR_MINE, PHASE_SELECTOR_HOST):
        return None
    return body[0], body[1]


def build_phase(selector, phase, sequence_id, flags=0x07):
    """-> the phase message a station announces, on the phase key."""
    if not 0 <= phase < 0x80:
        raise ValueError(f"phase {phase} is past what a single byte encodes")
    return game_channel.build_message(PHASE_KEY, bytes([selector, phase]), sequence_id,
                                      flags=flags)
