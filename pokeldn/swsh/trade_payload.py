"""The 3456-byte trade snapshot a Sword sends on protocol 0x84: party, MyStatus, TrainerCard and the
player profile (docs/swsh_protocol.md). The third fragment is zlib under Pia's flag 0x10; a raw
concatenation of 2965 bytes looks whole and is not.
"""
import struct
import zlib

from pokeldn import gen8
from pokeldn.swsh import pokemon

PAYLOAD_LENGTH = 3456
FRAGMENT_COUNT = 3

PARTY_OFFSET = 0
PARTY_COUNT_OFFSET = PARTY_OFFSET + pokemon.PARTY_BLOCK          # 0x810
MY_STATUS_OFFSET = PARTY_COUNT_OFFSET + 4                        # 0x814
MY_STATUS_LENGTH = 272
TRAINER_CARD_OFFSET = MY_STATUS_OFFSET + MY_STATUS_LENGTH        # 0x924
TRAINER_CARD_LENGTH = 456
TAIL_OFFSET = TRAINER_CARD_OFFSET + TRAINER_CARD_LENGTH          # 0xAEC, 660 bytes
TAIL_LENGTH = PAYLOAD_LENGTH - TAIL_OFFSET
PROFILE_LENGTH = 0x10A                                           # 0x01125080 writes this many
EXTRA_BLOCK_OFFSET = TAIL_OFFSET + PROFILE_LENGTH                # 0xBF6
EXTRA_BLOCK_LENGTH = 0x188                                       # zero for Link Trade

# into MyStatus, from PKHeX `Saves/Substructures/Gen8/SWSH/MyStatus8.cs`
MY_STATUS_TID = 0xA0
MY_STATUS_SID = 0xA2
MY_STATUS_GAME = 0xA4
MY_STATUS_GENDER = 0xA5
MY_STATUS_NAME = 0xB0
# into TrainerCard, from `TrainerCard8.cs`
TRAINER_CARD_NAME = 0x00
TRAINER_CARD_LANGUAGE = 0x1B
TRAINER_CARD_ID = 0x1C                                           # u32, (SID << 16 | TID) mod 10**6
TRAINER_CARD_STARTED = 0x170                                     # u16 year, then month, day
NAME_LENGTH = 0x1A


def inflate(fragment):
    """-> a 0x84 fragment body decompressed, or unchanged if it is not a zlib stream."""
    try:
        return zlib.decompress(fragment)
    except zlib.error:
        return fragment


def reassemble(fragments):
    """-> the whole 3456-byte payload from its three fragment bodies; raises on any other total."""
    if len(fragments) != FRAGMENT_COUNT:
        raise ValueError(f"{len(fragments)} fragments, expected {FRAGMENT_COUNT}")
    payload = b"".join(inflate(f) for f in fragments)
    if len(payload) != PAYLOAD_LENGTH:
        raise ValueError(f"reassembled {len(payload)} bytes, expected {PAYLOAD_LENGTH} - a fragment "
                         f"is missing, or a compressed one was concatenated raw")
    return payload


SHORT_LENGTH = 2965                   # a raw concatenation: 1404 + 1404 + 157 still compressed
FRAGMENT_2_END = 2808                 # where its third fragment begins


def inflate_short(payload):
    """-> a whole payload from a 2965-byte file whose third fragment is still deflated."""
    payload = bytes(payload)
    if len(payload) == PAYLOAD_LENGTH:
        return payload
    if len(payload) != SHORT_LENGTH:
        raise ValueError(f"{len(payload)} bytes: neither whole ({PAYLOAD_LENGTH}) nor one of "
                         f"a short file ({SHORT_LENGTH})")
    whole = payload[:FRAGMENT_2_END] + zlib.decompress(payload[FRAGMENT_2_END:])
    if len(whole) != PAYLOAD_LENGTH:
        raise ValueError(f"repaired to {len(whole)} bytes, expected {PAYLOAD_LENGTH}")
    return whole


def _text(data, offset):
    return data[offset:offset + NAME_LENGTH].decode("utf-16-le", "replace").split("\x00")[0]


def read(payload):
    """-> the party and the trainer behind it. `party` is `swsh.pokemon.party`'s six slots."""
    if len(payload) != PAYLOAD_LENGTH:
        raise ValueError(f"{len(payload)} bytes, expected {PAYLOAD_LENGTH}")
    status = payload[MY_STATUS_OFFSET:MY_STATUS_OFFSET + MY_STATUS_LENGTH]
    card = payload[TRAINER_CARD_OFFSET:TRAINER_CARD_OFFSET + TRAINER_CARD_LENGTH]
    year, month, day = struct.unpack_from("<HBB", card, TRAINER_CARD_STARTED)
    return {
        "party": pokemon.party(payload[PARTY_OFFSET:PARTY_OFFSET + pokemon.PARTY_BLOCK]),
        "party_count": struct.unpack_from("<I", payload, PARTY_COUNT_OFFSET)[0],
        "trainer_name": _text(status, MY_STATUS_NAME),
        "trainer_id": struct.unpack_from("<H", status, MY_STATUS_TID)[0],
        "secret_id": struct.unpack_from("<H", status, MY_STATUS_SID)[0],
        "game": status[MY_STATUS_GAME],
        "gender": status[MY_STATUS_GENDER],
        "card_name": _text(card, TRAINER_CARD_NAME),
        "card_language": card[TRAINER_CARD_LANGUAGE],
        "started": (year, month, day),
        "tail": payload[TAIL_OFFSET:],                    # `read_tail` decodes it
    }


# The profile as 0x01125080 (Shield 1.3.2) writes it; `read_tail` decodes the bit-packed groups
# (docs/swsh_protocol.md, The player profile).
TAIL_DEVICE_ID = 0x00                 # 16 bytes, nn::oe::GetPseudoDeviceId
TAIL_ACCOUNT_UID = 0x10               # 16 bytes, nn::account::GetUserId
TAIL_NSA_ID = 0x20                    # 8 bytes, nn::account::GetNetworkServiceAccountId, or zero
TAIL_NAME_OFFSET = 0x28               # 24 bytes, UTF-16, 12 units, MyStatus+0xB0; slack after the NUL
TAIL_NAME_LENGTH = 24
TAIL_APPEARANCE = 0x40                # 25 bytes, bit-packed, MyStatus fields
TAIL_SAMPLES = 0x59                   # 55 bytes, bit-packed, three 17-byte samples at 0x5C
TAIL_ACTIVITY = 0x90                  # 37 bytes, bit-packed
TAIL_RECORDS = 0xDA                   # 16 u16, the game's records, PKHeX Record8 indexes below
TAIL_OPTIONAL_U64 = 0xFA              # 8 bytes, zero in every capture
DEVICE_ID_LENGTH = ACCOUNT_UID_LENGTH = 16
NSA_ID_LENGTH = 8
RECORD_INDEXES = (6, 32, 0, 33, 17, 27, 34, 24, 12, 3, 10, 35, 38, 7, 36, 37)
RECORD_NAMES = ("total_capture", "evolution", "egg_hatching", "net_battle", "trade",
                "license_trade", "cooking", "campin", "pretty", "capture_raid", "rotomu_circuit",
                "poke_job_return", "bike_dash", "dress_up", "get_rare_item", "whistle")


def _bits(data, pos, n):
    """-> n bits of data starting at bit pos, least significant first, as the packer wrote them."""
    v = 0
    for i in range(n):
        b = pos + i
        v |= ((data[b >> 3] >> (b & 7)) & 1) << i
    return v


def read_tail(payload):
    """-> the player profile at TAIL_OFFSET, field by field (docs/swsh_protocol.md, The player
    profile); `records` are clamped to 0xFFFF and named by PKHeX."""
    if len(payload) != PAYLOAD_LENGTH:
        raise ValueError(f"{len(payload)} bytes, expected {PAYLOAD_LENGTH}")
    t = bytes(payload[TAIL_OFFSET:TAIL_OFFSET + PROFILE_LENGTH])
    name = t[TAIL_NAME_OFFSET:TAIL_NAME_OFFSET + TAIL_NAME_LENGTH]
    p = TAIL_APPEARANCE * 8
    gender, one, language, _pad, unknown_cc = (_bits(t, p, 1), _bits(t, p + 1, 1),
                                               _bits(t, p + 2, 4), _bits(t, p + 6, 2),
                                               _bits(t, p + 8, 8))
    p += 16
    appearance = [_bits(t, p + 10 * i, 10) for i in range(17)]
    p += 170
    tail_bits = (_bits(t, p, 2), _bits(t, p + 2, 2), _bits(t, p + 4, 10))
    p += 14
    assert p == TAIL_SAMPLES * 8
    samples = []
    for at in (0x5C, 0x6D, 0x7E):
        x, y, z, yaw = struct.unpack_from("<ffff", t, at + 1)
        samples.append({"counter": t[at] & 0x1F, "state": t[at] >> 5, "position": (x, y, z),
                        "yaw": yaw})
    records = struct.unpack_from("<16H", t, TAIL_RECORDS)
    return {
        "device_id": t[TAIL_DEVICE_ID:TAIL_DEVICE_ID + DEVICE_ID_LENGTH],
        "account_uid": t[TAIL_ACCOUNT_UID:TAIL_ACCOUNT_UID + ACCOUNT_UID_LENGTH],
        "nsa_id": t[TAIL_NSA_ID:TAIL_NSA_ID + NSA_ID_LENGTH],
        "name": name.decode("utf-16-le", "replace").split("\x00")[0],
        "gender": gender, "language": language, "unknown_bit": one, "my_status_cc": unknown_cc,
        "appearance": appearance, "appearance_tail": tail_bits,
        "sample_flags": (t[TAIL_SAMPLES] & 3, (t[TAIL_SAMPLES] >> 2) & 3),
        "sample_generation": t[TAIL_SAMPLES + 1],
        "sample_player_byte": t[TAIL_SAMPLES + 2],
        "samples": samples,
        "sample_end": t[0x8F],
        "activity": t[TAIL_ACTIVITY],
        "location": struct.unpack_from("<H", t, 0xB2)[0],
        "records": dict(zip(RECORD_NAMES, records)),
        "optional_u64": struct.unpack_from("<Q", t, TAIL_OPTIONAL_U64)[0],
        "extra_block": bytes(payload[EXTRA_BLOCK_OFFSET:EXTRA_BLOCK_OFFSET + EXTRA_BLOCK_LENGTH]),
    }


def rewrite(payload, *, trainer_name=None, trainer_id=None, secret_id=None, old_name=None,
            account_uid=None, device_id=None, nsa_id=None):
    """-> the snapshot with a new trainer identity in all four places the name lives (MyStatus, the
    trainer card, every party record, the profile at TAIL_OFFSET + 0x28); every other byte stays the
    console's own. `old_name` is ignored."""
    if len(payload) != PAYLOAD_LENGTH:
        raise ValueError(f"{len(payload)} bytes, expected {PAYLOAD_LENGTH}")
    out = bytearray(payload)

    if trainer_name is not None:
        encoded = trainer_name.encode("utf-16-le")
        if len(encoded) + 2 > NAME_LENGTH:
            raise ValueError(f"{trainer_name!r} is too long for a {NAME_LENGTH}-byte name field")
        encoded = encoded.ljust(NAME_LENGTH, b"\x00")
        ms = MY_STATUS_OFFSET + MY_STATUS_NAME
        out[ms:ms + NAME_LENGTH] = encoded
        tc = TRAINER_CARD_OFFSET + TRAINER_CARD_NAME
        out[tc:tc + NAME_LENGTH] = encoded
        at = TAIL_OFFSET + TAIL_NAME_OFFSET
        out[at:at + TAIL_NAME_LENGTH] = encoded[:TAIL_NAME_LENGTH]

    for value, at, length, what in ((device_id, TAIL_DEVICE_ID, DEVICE_ID_LENGTH, "device id"),
                                    (account_uid, TAIL_ACCOUNT_UID, ACCOUNT_UID_LENGTH, "account uid"),
                                    (nsa_id, TAIL_NSA_ID, NSA_ID_LENGTH, "network service account id")):
        if value is None:
            continue
        value = bytes(value)
        if len(value) != length:
            raise ValueError(f"a {what} is {length} bytes")
        out[TAIL_OFFSET + at:TAIL_OFFSET + at + length] = value

    if trainer_id is not None:
        struct.pack_into("<H", out, MY_STATUS_OFFSET + MY_STATUS_TID, trainer_id)
    if secret_id is not None:
        struct.pack_into("<H", out, MY_STATUS_OFFSET + MY_STATUS_SID, secret_id)
    if trainer_id is not None or secret_id is not None:
        # The League Card's id: a console keeps a partner's card unless it holds one with this id.
        tid, sid = struct.unpack_from("<HH", out, MY_STATUS_OFFSET + MY_STATUS_TID)
        struct.pack_into("<I", out, TRAINER_CARD_OFFSET + TRAINER_CARD_ID, ((sid << 16) | tid) % 10**6)

    edits = {k: v for k, v in (("ot_name", trainer_name), ("trainer_id", trainer_id),
                               ("secret_id", secret_id)) if v is not None}
    if edits:
        for slot in range(pokemon.PARTY_SLOTS):
            at = slot * gen8.SIZE_PARTY
            raw = bytes(out[at:at + gen8.SIZE_PARTY])
            if struct.unpack_from("<I", raw, 0)[0] == 0:        # an empty slot stays empty
                continue
            out[at:at + gen8.SIZE_PARTY] = pokemon.build_from(raw, **edits)
    return bytes(out)


def party_matches_trainer(fields):
    """-> True when every party member carries MyStatus's ids; a slipped reassembly would not."""
    ids = (fields["trainer_id"], fields["secret_id"])
    return all((p["trainer_id"], p["secret_id"]) == ids
               for p in fields["party"] if p is not None)


assert TAIL_OFFSET == 0xAEC and TAIL_LENGTH == 660, "the layout must close"
assert EXTRA_BLOCK_OFFSET + EXTRA_BLOCK_LENGTH + 2 == PAYLOAD_LENGTH, "profile, block, two bytes"
assert gen8.SIZE_PARTY * 6 == PARTY_COUNT_OFFSET, "the party block is six party-form records"
