"""The Pokemon entity Legends Arceus puts on the wire, and its crypto.

It is the Gen-8 entity with wider blocks. The header, the LCG, the block permutation and the
checksum are `pokeldn.gen8`'s field for field; a block is 0x58 bytes rather than 0x50, so a stored
record is 0x168 and a party record 0x178. Everything here is pinned against one record a console
sent over local wireless, decrypted and read back as a level-70 Azelf whose trainer id is the same
four bytes the data exchange carries as the player id.

    0x00  u32  encryption constant, in the clear
    0x04  u16  sanity, 0 on a record a console sends
    0x06  u16  checksum, in the clear, over the decrypted body to SIZE_STORED
    0x08       four 0x58-byte blocks, encrypted and permuted
    0x168      the party tail, encrypted with the stream RESTARTED and not permuted

BLOCK ORDER. `gen8.BLOCK_ORDER[(ec >> 13) & 31]` is applied as it stands when decrypting and
inverted when encrypting, which is `pokeldn.gen8`'s own rule. The checksum cannot tell the two
apart, because permuting whole blocks leaves a sum of 16-bit words alone. What tells them apart is
where the names land: read directly, the nickname sits at the start of the second block and the
trainer name at the start of the fourth, which is the Gen-8 layout with the wider block. Read
inverted, both strings still decode, one block earlier, and nothing about them looks wrong. The
record decoded here was read the inverted way first and the layout is what caught it.

THE BLOCK STARTS ARE GEN-8'S, WIDENED. A field at the head of a block sits where `pokeldn.gen8`
puts it plus 8 bytes per block before it: the nickname at 0x60 where Gen 8 has 0x58, the handling
trainer's name at 0xb8 where it has 0xa8, the trainer's name at 0x110 where it has 0xf8, and the
party tail at 0x168 where it has 0x148. The three handler fields inside the third block keep their
Gen-8 positions plus 0x10, which is how they were found: a record sent to a console and shown back by
it afterwards differs in the checksum, the current HP, the six party stats, and exactly those three
fields plus the handler name. Inside a block the offsets follow their block: the first block is Gen 8's
field for field apart from the moves, the second is Gen 8's plus 8, the third plus 0x10, the fourth
plus 0x18 with the ball moved to just after the met date.

THE MOVES ARE NOT WHERE GEN 8 KEEPS THEM. They are four halfwords at 0x54 with four bytes of
remaining PP at 0x5c, both inside the first block, where Gen 8 puts them in the second at 0x72 and
0x7a. Pinned against 46 records off a console's own box: every pair of records of one species carries
the same four move ids and the same PP, across different levels, encryption constants and personality
values, and a lower-level Chimchar differs from a higher one in the fourth move alone. The Gen-8
offsets read zero in all 46.

THE REST OF THE MAP IS PKHeX'S PA8, CHECKED AGAINST 47 CAPTURED RECORDS. `SCALARS`, `VECTORS`,
`BITFIELDS` and `NAMES` hold it. Three things in it are confirmed by the records themselves rather
than by the source it came from: the alpha bit at 0x16 and the alpha move at 0x3e are set on the
same three records and on no others; the height and weight scalars at 0x50 and 0x51 with the scale
at 0x52 explain the three bytes that vary per individual, the first and third equal in all 47
because the scale mirrors the height, and 0xff on each of the three alphas; and the packed
individual values at 0x94 carry the egg and nickname bits clear in every record, six values in
range. The effort values sit at Gen 8's own 0x26, trained on 18 of the 47, and this game's
own growth values are the six bytes at 0xa4.

THE SHINY RULE IS GEN 6'S. The trainer id, the secret id and the two halves of the personality
value exclusive-ored together under 16 sparkle, and 0 is the square. A record built with that value
0 was traded in and the console drew the sparkle on the summary, on the box panel and on the model.
The panel's ID No. is the whole 32-bit id at 0x0c modulo a million, which is how the secret id at
0x0e was confirmed to be the high half of one value rather than a field of its own.

WHAT A TRADE REWRITES. The receiving game fills in the handling trainer's name, language, handler
flag and friendship, and recomputes the current HP and the six party stats from the level and the
experience. It does not trust the tail it was sent: a record sent at level 50 with a level-70 tail
comes back with the level-50 stats. Everything else is stored as it arrived.

FIELDS. Species, trainer id, secret id, experience, the nickname and the trainer name are pinned by
that record: the species is the nickname, the trainer name is the name the data exchange carries,
the trainer id is the player id it carries, and the experience is 428750, which is level 70 on the
slow curve and the level the party tail holds. The held item is at the Gen-8 offset and read 0.
The ability, the personality value and the nature are at theirs and read Levitate, a personality
value and a nature in range. The effort values at Gen 8's own 0x26 read zero on that one record,
which is the record and not the game: 18 of the 47 captured records carry trained effort values
there. The six halfwords after the level byte are stats, and a trade rewrites them.

`docs/pla.md`, The trade box.
"""

import struct

from pokeldn import gen8

HEADER_SIZE = 8
BLOCK_SIZE = 0x58
BLOCK_COUNT = 4
SIZE_STORED = HEADER_SIZE + BLOCK_COUNT * BLOCK_SIZE       # 0x168, 360
SIZE_PARTY = SIZE_STORED + 0x10                            # 0x178, 376

NAME_LENGTH = gen8.NAME_LENGTH

OFF_ENCRYPTION_CONSTANT = 0x00
OFF_SANITY = 0x04
OFF_CHECKSUM = 0x06

OFF_SPECIES = 0x08
OFF_HELD_ITEM = 0x0A
OFF_TID = 0x0C
OFF_SID = 0x0E
OFF_EXPERIENCE = 0x10
OFF_ABILITY = 0x14
OFF_ABILITY_FLAGS = 0x16                                   # bits 0-2 the ability number, bit 5 alpha
OFF_MARKINGS = 0x18
OFF_PID = 0x1C
OFF_NATURE = 0x20
OFF_STAT_NATURE = 0x21                                     # the nature the stats are read from
OFF_GENDER_FLAGS = 0x22                                    # bit 0 fateful, bits 2-3 the gender
OFF_FORM = 0x24
OFF_EVS = 0x26                                             # six bytes, hp atk def spe spa spd
OFF_CONTEST = 0x2C
OFF_POKERUS = 0x32
OFF_RIBBONS = 0x34
OFF_ALPHA_MOVE = 0x3E
OFF_SOCIABILITY = 0x48
OFF_HEIGHT_SCALAR = 0x50
OFF_WEIGHT_SCALAR = 0x51
OFF_SCALE = 0x52
OFF_MOVES = 0x54                                           # 4 x u16
OFF_MOVE_PP = 0x5C                                         # 4 x u8
OFF_NICKNAME = HEADER_SIZE + BLOCK_SIZE                    # 0x60, the second block's first field
OFF_MOVE_PP_UPS = 0x86
OFF_RELEARN_MOVES = 0x8A                                   # 4 x u16
OFF_CURRENT_HP = 0x92                                      # rewritten with the stats on a trade
OFF_IVS = 0x94                                             # six 5-bit values, then two flag bits
OFF_STATUS = 0x9C
OFF_GVS = 0xA4                                             # six bytes, this game's effort values
OFF_HEIGHT_ABSOLUTE = 0xAC                                 # f32
OFF_WEIGHT_ABSOLUTE = 0xB0                                 # f32
OFF_HT_NAME = HEADER_SIZE + 2 * BLOCK_SIZE                 # 0xb8, the third block's
OFF_HT_GENDER = 0xD2
OFF_HT_LANGUAGE = 0xD3
OFF_CURRENT_HANDLER = 0xD4                                 # 0 = the original trainer still holds it
OFF_HT_FRIENDSHIP = 0xD8
OFF_FULLNESS = 0xEC
OFF_ENJOYMENT = 0xED
OFF_VERSION = 0xEE                                         # 47 on every record this game wrote
OFF_BATTLE_VERSION = 0xEF
OFF_LANGUAGE = 0xF2
OFF_FORM_ARGUMENT = 0xF4
OFF_AFFIXED_RIBBON = 0xF8                                  # 0xff, none
OFF_OT_NAME = HEADER_SIZE + 3 * BLOCK_SIZE                 # 0x110, the fourth block's
OFF_OT_FRIENDSHIP = 0x12A
OFF_EGG_DATE = 0x131                                       # year, month, day
OFF_MET_DATE = 0x134                                       # year, month, day
OFF_BALL = 0x137
OFF_EGG_LOCATION = 0x138
OFF_MET_LOCATION = 0x13A
OFF_MET_FLAGS = 0x13D                                      # bits 0-6 the met level, bit 7 OT gender
OFF_HYPER_TRAIN = 0x13E
OFF_LEVEL = SIZE_STORED                                    # in the party tail, a byte
OFF_STATS = SIZE_STORED + 2                                # six halfwords, as Gen-8's are

IV_NAMES = ("hp", "atk", "def", "spe", "spa", "spd")
ALPHA_BIT = 0x20
VERSION_LEGENDS_ARCEUS = 47

# name -> (offset, struct format). Every scalar field this module reads and writes.
SCALARS = {
    "encryption_constant": (OFF_ENCRYPTION_CONSTANT, "<I"),
    "sanity": (OFF_SANITY, "<H"),
    "species": (OFF_SPECIES, "<H"),
    "held_item": (OFF_HELD_ITEM, "<H"),
    "trainer_id": (OFF_TID, "<H"),
    "secret_id": (OFF_SID, "<H"),
    "experience": (OFF_EXPERIENCE, "<I"),
    "ability": (OFF_ABILITY, "<H"),
    "markings": (OFF_MARKINGS, "<H"),
    "pid": (OFF_PID, "<I"),
    "nature": (OFF_NATURE, "<B"),
    "stat_nature": (OFF_STAT_NATURE, "<B"),
    "form": (OFF_FORM, "<H"),
    "pokerus": (OFF_POKERUS, "<B"),
    "alpha_move": (OFF_ALPHA_MOVE, "<H"),
    "sociability": (OFF_SOCIABILITY, "<I"),
    "height_scalar": (OFF_HEIGHT_SCALAR, "<B"),
    "weight_scalar": (OFF_WEIGHT_SCALAR, "<B"),
    "scale": (OFF_SCALE, "<B"),
    "current_hp": (OFF_CURRENT_HP, "<H"),
    "status": (OFF_STATUS, "<i"),
    "height_absolute": (OFF_HEIGHT_ABSOLUTE, "<f"),
    "weight_absolute": (OFF_WEIGHT_ABSOLUTE, "<f"),
    "ht_gender": (OFF_HT_GENDER, "<B"),
    "ht_language": (OFF_HT_LANGUAGE, "<B"),
    "current_handler": (OFF_CURRENT_HANDLER, "<B"),
    "ht_friendship": (OFF_HT_FRIENDSHIP, "<B"),
    "fullness": (OFF_FULLNESS, "<B"),
    "enjoyment": (OFF_ENJOYMENT, "<B"),
    "version": (OFF_VERSION, "<B"),
    "battle_version": (OFF_BATTLE_VERSION, "<B"),
    "language": (OFF_LANGUAGE, "<B"),
    "form_argument": (OFF_FORM_ARGUMENT, "<I"),
    "affixed_ribbon": (OFF_AFFIXED_RIBBON, "<b"),
    "ot_friendship": (OFF_OT_FRIENDSHIP, "<B"),
    "ball": (OFF_BALL, "<B"),
    "egg_location": (OFF_EGG_LOCATION, "<H"),
    "met_location": (OFF_MET_LOCATION, "<H"),
    "hyper_train": (OFF_HYPER_TRAIN, "<B"),
}

# name -> (offset, count, struct format for one element)
VECTORS = {
    "moves": (OFF_MOVES, 4, "<H"),
    "move_pp": (OFF_MOVE_PP, 4, "<B"),
    "move_pp_ups": (OFF_MOVE_PP_UPS, 4, "<B"),
    "relearn_moves": (OFF_RELEARN_MOVES, 4, "<H"),
    "evs": (OFF_EVS, 6, "<B"),
    "gvs": (OFF_GVS, 6, "<B"),
    "contest": (OFF_CONTEST, 6, "<B"),
    "met_date": (OFF_MET_DATE, 3, "<B"),
    "egg_date": (OFF_EGG_DATE, 3, "<B"),
}

# name -> (offset, shift, mask)
BITFIELDS = {
    "ability_number": (OFF_ABILITY_FLAGS, 0, 0x07),
    "is_alpha": (OFF_ABILITY_FLAGS, 5, 0x01),
    "is_noble": (OFF_ABILITY_FLAGS, 6, 0x01),
    "fateful": (OFF_GENDER_FLAGS, 0, 0x01),
    "gender": (OFF_GENDER_FLAGS, 2, 0x03),
    "is_egg": (OFF_IVS + 3, 6, 0x01),
    "is_nicknamed": (OFF_IVS + 3, 7, 0x01),
    "met_level": (OFF_MET_FLAGS, 0, 0x7F),
    "ot_gender": (OFF_MET_FLAGS, 7, 0x01),
}

NAMES = {"nickname": OFF_NICKNAME, "ht_name": OFF_HT_NAME, "ot_name": OFF_OT_NAME}


def checksum(plain):
    """The 16-bit sum of the decrypted body, bounded at SIZE_STORED as Gen-8's is."""
    n = (SIZE_STORED - HEADER_SIZE) // 2
    return sum(struct.unpack_from(f"<{n}H", plain, HEADER_SIZE)) & 0xFFFF


def permute(data, order):
    """-> data with its four blocks reordered, `order[i]` naming the block that becomes block i."""
    out = bytearray(data[:HEADER_SIZE])
    for src in order:
        out += data[HEADER_SIZE + src * BLOCK_SIZE:HEADER_SIZE + (src + 1) * BLOCK_SIZE]
    return bytes(out) + data[SIZE_STORED:]


def decrypt(raw):
    """-> the plain, unshuffled record. Raises if the checksum disagrees."""
    if len(raw) not in (SIZE_STORED, SIZE_PARTY):
        raise ValueError(f"{len(raw)} bytes, expected {SIZE_STORED} or {SIZE_PARTY}")
    ec = struct.unpack_from("<I", raw, 0)[0]
    out = bytearray(raw)
    out[HEADER_SIZE:SIZE_STORED] = gen8.crypt(raw[HEADER_SIZE:SIZE_STORED], ec)
    out[SIZE_STORED:] = gen8.crypt(raw[SIZE_STORED:], ec)
    plain = permute(bytes(out), gen8.BLOCK_ORDER[(ec >> 13) & 31])
    want = struct.unpack_from("<H", raw, 6)[0]
    got = checksum(plain)
    if got != want:
        raise ValueError(f"checksum {got:#06x}, header says {want:#06x} - not a valid record")
    return plain


def encrypt(plain):
    """-> the bytes to put on the wire, with the checksum written from the body itself."""
    if len(plain) not in (SIZE_STORED, SIZE_PARTY):
        raise ValueError(f"{len(plain)} bytes, expected {SIZE_STORED} or {SIZE_PARTY}")
    body = bytearray(plain)
    struct.pack_into("<H", body, 6, checksum(body))
    ec = struct.unpack_from("<I", body, 0)[0]
    order = gen8.invert(gen8.BLOCK_ORDER[(ec >> 13) & 31])
    shuffled = bytearray(permute(bytes(body), order))
    out = bytearray(shuffled)
    out[HEADER_SIZE:SIZE_STORED] = gen8.crypt(shuffled[HEADER_SIZE:SIZE_STORED], ec)
    out[SIZE_STORED:] = gen8.crypt(shuffled[SIZE_STORED:], ec)
    return bytes(out)


def is_plain(raw):
    """-> whether a record is already decrypted: its own body sums to the checksum it carries."""
    if len(raw) not in (SIZE_STORED, SIZE_PARTY):
        return False
    return checksum(raw) == struct.unpack_from("<H", raw, 6)[0]


def load(raw):
    """-> a plain PARTY record from a record in any of the four shapes, stored or party."""
    plain = bytes(raw) if is_plain(raw) else decrypt(raw)
    if len(plain) == SIZE_STORED:
        plain += bytes(SIZE_PARTY - SIZE_STORED)
    return plain


def text(plain, offset):
    return plain[offset:offset + NAME_LENGTH].decode("utf-16-le", "replace").split("\x00")[0]


def ivs(plain):
    """-> the six individual values, unpacked from the word they share with two flag bits."""
    packed = struct.unpack_from("<I", plain, OFF_IVS)[0]
    return tuple((packed >> (5 * i)) & 31 for i in range(6))


def read(plain):
    """-> what a DECRYPTED record says about itself. The party tail only if it is the party form."""
    fields = {key: struct.unpack_from(fmt, plain, off)[0] for key, (off, fmt) in SCALARS.items()}
    for key, (off, count, fmt) in VECTORS.items():
        size = struct.calcsize(fmt)
        fields[key] = tuple(
            struct.unpack_from(fmt, plain, off + i * size)[0] for i in range(count))
    for key, (off, shift, mask) in BITFIELDS.items():
        fields[key] = (plain[off] >> shift) & mask
    for key, off in NAMES.items():
        fields[key] = text(plain, off)
    fields["ivs"] = ivs(plain)
    fields["is_shiny"] = shiny_xor(fields) < 16
    if len(plain) == SIZE_PARTY:
        fields["level"] = plain[OFF_LEVEL]
        fields["stats"] = struct.unpack_from("<6H", plain, OFF_STATS)
    return fields


def shiny_xor(fields):
    """-> the Gen-6 shiny value of a record `read` returned: under 16 sparkles, 0 is the square."""
    return (fields["trainer_id"] ^ fields["secret_id"]
            ^ (fields["pid"] >> 16) ^ (fields["pid"] & 0xFFFF))


def write(plain, **fields):
    """-> the record with the named fields written into it. The checksum is `encrypt`'s to write."""
    out = bytearray(plain)

    def name(offset, value):
        encoded = str(value).encode("utf-16-le")
        if len(encoded) + 2 > NAME_LENGTH:
            raise ValueError(f"{value!r} is too long for a {NAME_LENGTH}-byte name field")
        out[offset:offset + NAME_LENGTH] = encoded.ljust(NAME_LENGTH, b"\x00")

    for key, value in fields.items():
        if key in SCALARS:
            off, fmt = SCALARS[key]
            struct.pack_into(fmt, out, off, value)
        elif key in VECTORS:
            off, count, fmt = VECTORS[key]
            size = struct.calcsize(fmt)
            if len(value) != count:
                raise ValueError(f"{key} takes {count} values, given {len(value)}")
            for i, item in enumerate(value):
                struct.pack_into(fmt, out, off + i * size, item)
        elif key in BITFIELDS:
            off, shift, mask = BITFIELDS[key]
            out[off] = (out[off] & ~(mask << shift) & 0xFF) | ((int(value) & mask) << shift)
        elif key in NAMES:
            name(NAMES[key], value)
        elif key == "ivs":
            if len(value) != 6:
                raise ValueError(f"the individual values are six, given {len(value)}")
            packed = struct.unpack_from("<I", out, OFF_IVS)[0] & ~0x3FFFFFFF
            for i, item in enumerate(value):
                packed |= (item & 31) << (5 * i)
            struct.pack_into("<I", out, OFF_IVS, packed)
        elif key == "level":
            if len(out) != SIZE_PARTY:
                raise ValueError(f"the level is a party-record field and this is {len(out)} bytes")
            out[OFF_LEVEL] = value
        elif key == "stats":
            if len(out) != SIZE_PARTY:
                raise ValueError(f"the stats are party-record fields and this is {len(out)} bytes")
            struct.pack_into("<6H", out, OFF_STATS, *value)
        else:
            raise ValueError(f"{key} is not a field this module writes")
    return bytes(out)


# What `build` puts in a record the caller does not name. Every value is one the 47 captured
# records carry: this game's version byte, the save's language, no sanity flag, no affixed ribbon,
# and the original trainer still holding it.
BUILD_DEFAULTS = {
    "sanity": 0,
    "version": VERSION_LEGENDS_ARCEUS,
    "battle_version": 0,
    "language": 2,
    "affixed_ribbon": -1,
    "current_handler": 0,
    "ht_language": 0,
    "ht_friendship": 0,
    "ot_friendship": 250,
    "met_date": (22, 1, 21),
    "ivs": (31, 31, 31, 31, 31, 31),
    "gvs": (10, 10, 10, 10, 10, 10),
}


def build(**fields):
    """-> a plain PARTY record assembled from zero bytes, with BUILD_DEFAULTS under the caller's.

    Nothing is copied from a record a console wrote. A field this module does not know stays zero,
    so what the game reads out of one is what the field map here covers and nothing else.
    """
    merged = dict(BUILD_DEFAULTS)
    merged.update(fields)
    out = bytearray(write(bytes(SIZE_PARTY), **merged))
    struct.pack_into("<H", out, OFF_CHECKSUM, checksum(out))     # so `is_plain` knows it as one
    return bytes(out)


def shiny_pid(trainer_id, secret_id, high=0x0000):
    """-> a personality value whose shiny xor against those ids is 0, the square sparkle."""
    return (high << 16) | (trainer_id ^ secret_id ^ high)


def describe(plain):
    """-> one line naming what a decrypted record is, for a log."""
    f = read(plain)
    shiny = " shiny" if f["is_shiny"] else ""
    level = f"level {f['level']}" if len(plain) == SIZE_PARTY else "stored"
    return (f"species {f['species']}{shiny} {level} of {f['ot_name']!r} "
            f"(id {f['trainer_id']}) moves {f['moves']} ivs {f['ivs']} gvs {f['gvs']}")
