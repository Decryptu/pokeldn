"""The 3456-byte trade snapshot a Sword sends on protocol 0x84.

The layout below comes from two published clients, `kwsch/PokePiaSWSH` (C#) and
`lincoln-lm/swsh-lan-client` (Python), both over LAN mode rather than local wireless. What verified
it here is our own capture, field for field.

    0x000  six PK8 records, party form, 0x158 each          -> 0x810
    0x810  u32   party count
    0x814  MyStatus, 272 bytes      TID/SID at 0xA0, trainer name at 0xB0
    0x924  TrainerCard, 456 bytes   trainer name at 0x00, start date at 0x170
    0xAEC  the player profile, 266 bytes, the record the LDN beacon carries too
    0xBF6  392 bytes another session kind fills; zero for Link Trade
    0xD7E  2 bytes of padding                                -> 0xD80 = 3456

The profile is read in `docs/swsh_protocol.md`, "The player profile"; `read_tail` decodes it.

The payload is 3456 bytes. The third fragment is compressed under Pia's message flag 0x10, the
version-4 zlib flag `docs/pia.md` documents for protocol 0x80. Concatenated raw the three give
1404 + 1404 + 157 = 2965, which looks like a whole payload because nothing states the length;
inflated, the third is 648 bytes and the total is 3456. `reassemble` refuses anything but 3456: a
reassembly that produces a plausible length is not a reassembly that is right.

What verifies the layout on our own bytes, none of it a checksum:

  - the party count reads 3, and slots 4-6 are the ones with a zero encryption constant;
  - MyStatus gives TID 56909 and SID 48474, and **those are the ids inside all three PK8s**;
  - the trainer name is at both named offsets, and matches the OT name in the party;
  - the start date at TrainerCard+0x170 is 2019-11-15, and 0x924 + 0x170 is 0xA94.
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
    """-> a 0x84 fragment body decompressed, or unchanged if it is not a zlib stream.

    The console sets Pia's message flag 0x10 on the compressed one; a receiver that reads the flag
    should not need this. It is here because our capture path did not, and because a payload
    already on disk can be repaired without another association.
    """
    try:
        return zlib.decompress(fragment)
    except zlib.error:
        return fragment


def reassemble(fragments):
    """-> the whole 3456-byte payload from its three fragment bodies, compressed ones inflated.

    Raises on any other total: a short concatenation is wrong and nothing in it says so.
    """
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
    """-> a whole payload from a short file, which is what earlier captures hold.

    A payload saved before the compressed fragment was understood is 2965 bytes with its third
    fragment still deflated. Nothing about those files is wrong except that they stop early, so
    they are repaired rather than thrown away - the party in them is a real console's.
    """
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


# The profile at TAIL_OFFSET, as 0x01125080 (Shield 1.3.2) writes it from the struct 0x01111970
# copies out of the profile singleton. Raw fields first; the three bit-packed groups are decoded
# by `read_tail`. docs/swsh_protocol.md, "The player profile".
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
    """-> the player profile at TAIL_OFFSET, field by field.

    `appearance` is the 17 ten-bit values 0x0111dd60 unpacks from MyStatus, the player's model.
    `samples` are the player's last three field positions, newest first: a 5-bit counter that
    steps once per push, the 3-bit movement state, the world position and the yaw in radians
    (docs/swsh_protocol.md, The player profile). `sample_generation` is the byte a listener tells
    a new run of samples by; `location` is the met-location id of the field the player stands on.
    `records` are the sixteen game records the profile carries, clamped to 0xFFFF, by their PKHeX
    names.
    """
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
    """-> the snapshot with a new trainer identity, and every other byte still the console's own.

    THE POINT OF THE PROJECT NEEDS ONE OF THESE AND IT MUST NOT BE THE CONSOLE'S OWN. 3456 bytes
    hold a trainer card, a status block, six party records and the player profile, and most of it
    is fields this project has never built. Building one from nothing would mean inventing every
    one of them, so ours is the console's snapshot with the identity moved - the same method
    `swsh.pokemon.build_from` and `bdsp.pokemon.build_from` use on a single Pokemon, for the same
    reason.

    The identity has to move in four places at once: MyStatus, the trainer card, every party
    record, and the profile's name field at TAIL_OFFSET + 0x28. The trade screen draws the partner
    from MyStatus, so a snapshot with the profile left alone reads correctly on screen while it
    still names the console's own player, and `party_matches_trainer` cannot see that because it
    only compares the party against MyStatus.

    The profile name field is 24 bytes and the console leaves whatever its buffer held after the
    terminator; the replacement is padded with zeros. `old_name` is accepted for the older call
    sites and ignored: the field is at a fixed offset.

    The three ids at the front of the profile are the console's own (its pseudo device id, the
    account's Uid and its network service account id) and are handed straight back unless
    replaced; the trade screen never draws them.
    """
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
    """-> True when every party member carries the trainer's own ids.

    The party records and MyStatus are different blocks of the payload and agree on the ids. A
    reassembly that had slipped would not.
    """
    ids = (fields["trainer_id"], fields["secret_id"])
    return all((p["trainer_id"], p["secret_id"]) == ids
               for p in fields["party"] if p is not None)


assert TAIL_OFFSET == 0xAEC and TAIL_LENGTH == 660, "the layout must close"
assert EXTRA_BLOCK_OFFSET + EXTRA_BLOCK_LENGTH + 2 == PAYLOAD_LENGTH, "profile, block, two bytes"
assert gen8.SIZE_PARTY * 6 == PARTY_COUNT_OFFSET, "the party block is six party-form records"
