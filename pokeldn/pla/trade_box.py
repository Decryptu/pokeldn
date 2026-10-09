"""The trade box: the Pokemon a station shows (selector 2) and offers (selector 4) on port 0 of the
game's channel, behind the zero key. An answer carries the selector it answers; the message depends
on the save alone (docs/pla.md, The trade box).
"""

import struct

from pokeldn.ldn import reliable5
from pokeldn.pla import game_channel, pokemon

PROTOCOL = game_channel.PROTOCOL           # 0x7c
PORT = game_channel.HOST_PORT              # the zero key routes on port 0
SEQUENCE_ID = 2                            # the channel's opens are sequence 1

SELECTOR_READY = 1
SELECTOR_SHOWING = 2
SELECTOR_OFFERING = 4
SELECTOR_CONFIRMING = 5
SELECTOR_OFFER_MADE = 6
RECORD_SELECTORS = (SELECTOR_SHOWING, SELECTOR_OFFERING)
# Answered with the same two bytes; selector 1 is the channel open `game_channel` answers.
MIRRORED_SELECTORS = (3, SELECTOR_CONFIRMING, SELECTOR_OFFER_MADE, 7)

HEADER_SIZE = 6
BLOB_TAG = 0xBC                            # what 0x26da3b0 compares the byte against
HALFWORD_TAG = 0x81                        # 0x2666338: 0x80 introduces a byte, 0x81 a halfword

# A console's offer as sent: a level-70 Azelf of the trainer the data exchange names.
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

# Arbitrary, so the offered record differs from the one the console holds.
OUR_ENCRYPTION_CONSTANT = 0x504B4C44
OUR_PID = 0x4E444C4B


def build_our_record(player_id, name, template=REFERENCE_RECORD):
    """-> the template under a new identity; `player_id` becomes its trainer id and secret id, as a
    console's data exchange and record agree."""
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
    """-> (selector, body) of a game-channel message behind the zero key, or None."""
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


# The phase protocol on its own key. The job leaves state 2 only on the peer's selector 2, which
# only the host sends (`0x26d7e84` behind `[obj+0x78]`, set by `0x26d7aa0`) (docs/pla.md, The phase
# protocol).
PHASE_KEY = bytes.fromhex("0100000000000000")
PHASE_SELECTOR_MINE = 1            # 0x26d7d8c: the phase a station announces for itself
PHASE_SELECTOR_HOST = 2            # 0x26d7e84: the same, from the host only


def read_phase(payload):
    """-> (selector, phase) of a phase message, or None if it is not one."""
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


class OnlineBox:
    """The trade box with a partner far away (pokeldn.online, docs/online.md): the partner's
    console's record answers this console's showings and offer, and the mirror of its selector 5,
    which is our confirmation, waits for the partner's console to confirm."""

    def __init__(self, partner):
        self.partner = partner
        self._start()

    def _start(self):
        self.counter = None          # the console's offer counter, which our answer repeats
        self.sent = None             # the partner record our selector 4 carried
        self.confirm = None          # the console's selector-5 body, held
        self.mirrored = False

    def on_box(self, offered):
        """A showing or an offer from the console -> [(selector, counter, record)] to answer now."""
        remote = self.partner.theirs().offer
        if offered["selector"] == SELECTOR_SHOWING:
            return [(SELECTOR_SHOWING, offered["counter"], remote)] if remote else []
        self.partner.offer(offered["record"])
        self.counter, self.confirm, self.sent = offered["counter"], None, None
        if remote is None:
            return []
        self.sent = remote
        return [(SELECTOR_OFFERING, offered["counter"], remote)]

    def on_selector(self, selector, body):
        """A mirrored selector from the console -> the bodies to mirror now."""
        if selector == SELECTOR_CONFIRMING and self.counter is not None and not self.mirrored:
            self.confirm = body
            self.partner.accept()
            return self._release()
        if selector == SELECTOR_OFFER_MADE and not self.mirrored:
            # 6 takes back a confirmation (state 4) or the offer (state 3) (docs/pla.md).
            if self.confirm is not None:
                self.confirm = None
                self.partner.unaccept()
            else:
                self.partner.withdraw()
                self.counter = self.sent = None
        return [body]

    def _release(self):
        theirs = self.partner.theirs()
        if self.confirm is not None and theirs.accepted and self.sent is not None \
                and theirs.offer == self.sent:
            self.mirrored, body, self.confirm = True, self.confirm, None
            return [body]
        return []

    def tick(self):
        """-> ([(selector, counter, record)], [mirror bodies]) the partner's progress releases."""
        if self.mirrored:
            return [], []
        remote = self.partner.theirs().offer
        offers = []
        if self.counter is not None and remote is not None and remote != self.sent:
            # A second offer over one the console holds is unmeasured (docs/online.md).
            self.sent = remote
            offers.append((SELECTOR_OFFERING, self.counter, remote))
        return offers, self._release()

    def done(self):
        self.partner.done()
        self._start()
