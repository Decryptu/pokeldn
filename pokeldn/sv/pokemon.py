"""The Pokemon Scarlet and Violet trade on the wire: a four-byte prefix and a Gen-9 record.

The body of a `80 00 02 00` trade message is 348 bytes. The first four are the constant
`bc 81 58 01`, the same on a retail console's offer and on an emulated pair host's. The 344 behind
them are one PK9 party record, in the shape PKHeX's `PKM/PK9.cs` lays out, under the Gen-8 crypto
`pokeldn.gen8` already carries: `SIZE_8STORED` 0x148, `SIZE_8PARTY` 0x158, four 0x50-byte blocks
permuted by `(EC >> 13) & 31`, an LCG over the 16-bit words that restarts at the party tail, and a
checksum that is the 16-bit sum of the decrypted body up to 0x148.

    0x00  u32  encryption constant, in the clear
    0x04  u16  sanity, 0 on both samples
    0x06  u16  checksum, in the clear
    0x08       four 0x50-byte blocks, encrypted and permuted   -> 0x148
    0x148      level, then the six stats, encrypted and NOT permuted, the LCG re-seeded -> 0x158

SPECIES. The field at 0x08 is the game's internal index, which parts from the National Dex at 917
[`SpeciesConverter.cs:92`]. Under 917 the two agree, which is why both samples read straight.
`national` and `internal_index` convert; `read` reports both and `write` takes `species` as a
National Dex number.

WHAT READS OUT OF THE TWO SAMPLES. `scratchpad/sv74_console_offer.hex`, a retail Scarlet's own
offer: species 50 at level 3, nickname `Taupiqueur`, trainer `Gurvan`, handler `Pauline`, moves
10 and 28, experience 27, which is level 3 on the Medium Fast curve, and stats 14/9/5/10/7/8.
`scratchpad/sv_pair_host_offer.hex`, an emulated pair host's: species 906 at level 1, nickname
`Sprigatito`, trainer `Mattia`. A wrong block order survives the checksum, so what pins the order
is a record reading as a Pokemon: both do (`pokeldn/gen8.py`, the warning at the top).
"""

import struct

from pokeldn import gen8

HEADER_SIZE = gen8.HEADER_SIZE                             # 8
BLOCK_SIZE = gen8.BLOCK_SIZE                               # 0x50
BLOCK_COUNT = gen8.BLOCK_COUNT
SIZE_STORED = gen8.SIZE_STORED                             # 0x148, 328
SIZE_PARTY = gen8.SIZE_PARTY                               # 0x158, 344

# The four bytes in front of the record in a trade message, identical on both samples.
WIRE_PREFIX = bytes.fromhex("bc815801")
SIZE_WIRE = len(WIRE_PREFIX) + SIZE_PARTY                  # 348, the body of a 80 00 02 00 message

NAME_LENGTH = gen8.NAME_LENGTH

OFF_ENCRYPTION_CONSTANT = 0x00
OFF_SANITY = 0x04
OFF_CHECKSUM = 0x06

OFF_SPECIES = 0x08                                         # the internal index, not the dex number
OFF_HELD_ITEM = 0x0A
OFF_TID = 0x0C
OFF_SID = 0x0E
OFF_EXPERIENCE = 0x10
OFF_ABILITY = 0x14
OFF_ABILITY_FLAGS = 0x16                                   # bits 0-2 the ability number, bit 3 favourite
OFF_MARKINGS = 0x18
OFF_PID = 0x1C
OFF_NATURE = 0x20
OFF_STAT_NATURE = 0x21                                     # the nature the stats are read from
OFF_GENDER_FLAGS = 0x22                                    # bit 0 fateful, bits 1-2 the gender
OFF_FORM = 0x24
OFF_EVS = 0x26                                             # six bytes, hp atk def spe spa spd
OFF_CONTEST = 0x2C
OFF_POKERUS = 0x32
OFF_RIBBONS = 0x34
OFF_HEIGHT_SCALAR = 0x48
OFF_WEIGHT_SCALAR = 0x49
OFF_SCALE = 0x4A
OFF_RECORD_FLAGS_DLC = 0x4B                                # the DLC move-record flags
OFF_NICKNAME = 0x58
OFF_MOVES = 0x72                                           # 4 x u16
OFF_MOVE_PP = 0x7A                                         # 4 x u8
OFF_MOVE_PP_UPS = 0x7E                                     # 4 x u8
OFF_RELEARN_MOVES = 0x82                                   # 4 x u16
OFF_CURRENT_HP = 0x8A                                      # rewritten with the stats on a trade
OFF_IVS = 0x8C                                             # six 5-bit values, then two flag bits
OFF_STATUS = 0x90
OFF_TERA_TYPE_ORIGINAL = 0x94
OFF_TERA_TYPE_OVERRIDE = 0x95
OFF_HT_NAME = 0xA8
OFF_HT_GENDER = 0xC2
OFF_HT_LANGUAGE = 0xC3
OFF_CURRENT_HANDLER = 0xC4                                 # 0 = the original trainer still holds it
OFF_HT_ID = 0xC6
OFF_HT_FRIENDSHIP = 0xC8
OFF_HT_MEMORY_INTENSITY = 0xC9
OFF_HT_MEMORY = 0xCA
OFF_HT_MEMORY_FEELING = 0xCB
OFF_HT_MEMORY_VARIABLE = 0xCC
OFF_VERSION = 0xCE
OFF_BATTLE_VERSION = 0xCF
OFF_FORM_ARGUMENT = 0xD0
OFF_AFFIXED_RIBBON = 0xD4                                  # -1, none
OFF_LANGUAGE = 0xD5
OFF_OT_NAME = 0xF8
OFF_OT_FRIENDSHIP = 0x112
OFF_OT_MEMORY_INTENSITY = 0x113
OFF_OT_MEMORY = 0x114
OFF_OT_MEMORY_VARIABLE = 0x116
OFF_OT_MEMORY_FEELING = 0x118
OFF_EGG_DATE = 0x119                                       # year, month, day
OFF_MET_DATE = 0x11C                                       # year, month, day
OFF_OBEDIENCE_LEVEL = 0x11F
OFF_EGG_LOCATION = 0x120
OFF_MET_LOCATION = 0x122
OFF_BALL = 0x124
OFF_MET_FLAGS = 0x125                                      # bits 0-6 the met level, bit 7 OT gender
OFF_HYPER_TRAIN = 0x126
OFF_TRACKER = 0x127                                        # the HOME tracker, u64
OFF_RECORD_FLAGS_BASE = 0x12F                              # the base-game move-record flags
OFF_LEVEL = SIZE_STORED                                    # in the party tail, a byte
OFF_STATS = SIZE_STORED + 2                                # six halfwords, as Gen-8's are

IV_NAMES = ("hp", "atk", "def", "spe", "spa", "spd")
VERSION_SCARLET = 50
VERSION_VIOLET = 51

# name -> (offset, struct format). Every scalar field this module reads and writes.
SCALARS = {
    "encryption_constant": (OFF_ENCRYPTION_CONSTANT, "<I"),
    "sanity": (OFF_SANITY, "<H"),
    "species_internal": (OFF_SPECIES, "<H"),
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
    "height_scalar": (OFF_HEIGHT_SCALAR, "<B"),
    "weight_scalar": (OFF_WEIGHT_SCALAR, "<B"),
    "scale": (OFF_SCALE, "<B"),
    "current_hp": (OFF_CURRENT_HP, "<H"),
    "status": (OFF_STATUS, "<i"),
    "tera_type_original": (OFF_TERA_TYPE_ORIGINAL, "<B"),
    "tera_type_override": (OFF_TERA_TYPE_OVERRIDE, "<B"),
    "ht_gender": (OFF_HT_GENDER, "<B"),
    "ht_language": (OFF_HT_LANGUAGE, "<B"),
    "current_handler": (OFF_CURRENT_HANDLER, "<B"),
    "ht_id": (OFF_HT_ID, "<H"),
    "ht_friendship": (OFF_HT_FRIENDSHIP, "<B"),
    "ht_memory_intensity": (OFF_HT_MEMORY_INTENSITY, "<B"),
    "ht_memory": (OFF_HT_MEMORY, "<B"),
    "ht_memory_feeling": (OFF_HT_MEMORY_FEELING, "<B"),
    "ht_memory_variable": (OFF_HT_MEMORY_VARIABLE, "<H"),
    "version": (OFF_VERSION, "<B"),
    "battle_version": (OFF_BATTLE_VERSION, "<B"),
    "form_argument": (OFF_FORM_ARGUMENT, "<I"),
    "affixed_ribbon": (OFF_AFFIXED_RIBBON, "<b"),
    "language": (OFF_LANGUAGE, "<B"),
    "ot_friendship": (OFF_OT_FRIENDSHIP, "<B"),
    "ot_memory_intensity": (OFF_OT_MEMORY_INTENSITY, "<B"),
    "ot_memory": (OFF_OT_MEMORY, "<B"),
    "ot_memory_variable": (OFF_OT_MEMORY_VARIABLE, "<H"),
    "ot_memory_feeling": (OFF_OT_MEMORY_FEELING, "<B"),
    "obedience_level": (OFF_OBEDIENCE_LEVEL, "<B"),
    "egg_location": (OFF_EGG_LOCATION, "<H"),
    "met_location": (OFF_MET_LOCATION, "<H"),
    "ball": (OFF_BALL, "<B"),
    "hyper_train": (OFF_HYPER_TRAIN, "<B"),
    "tracker": (OFF_TRACKER, "<Q"),
}

# name -> (offset, count, struct format for one element)
VECTORS = {
    "moves": (OFF_MOVES, 4, "<H"),
    "move_pp": (OFF_MOVE_PP, 4, "<B"),
    "move_pp_ups": (OFF_MOVE_PP_UPS, 4, "<B"),
    "relearn_moves": (OFF_RELEARN_MOVES, 4, "<H"),
    "evs": (OFF_EVS, 6, "<B"),
    "contest": (OFF_CONTEST, 6, "<B"),
    "met_date": (OFF_MET_DATE, 3, "<B"),
    "egg_date": (OFF_EGG_DATE, 3, "<B"),
}

# name -> (offset, shift, mask)
BITFIELDS = {
    "ability_number": (OFF_ABILITY_FLAGS, 0, 0x07),
    "is_favourite": (OFF_ABILITY_FLAGS, 3, 0x01),
    "fateful": (OFF_GENDER_FLAGS, 0, 0x01),
    "gender": (OFF_GENDER_FLAGS, 1, 0x03),
    "is_egg": (OFF_IVS + 3, 6, 0x01),
    "is_nicknamed": (OFF_IVS + 3, 7, 0x01),
    "met_level": (OFF_MET_FLAGS, 0, 0x7F),
    "ot_gender": (OFF_MET_FLAGS, 7, 0x01),
}

NAMES = {"nickname": OFF_NICKNAME, "ht_name": OFF_HT_NAME, "ot_name": OFF_OT_NAME}

# The internal index and the National Dex number part at 917. Each table is the signed difference
# to add, indexed from that species [`PKHeX.Core/PKM/Util/Conversion/SpeciesConverter.cs:141`].
FIRST_UNALIGNED = 917
NATIONAL_TO_INTERNAL = (
    1, 1, 1,
    1, 33, 33, 33, 21, 21, 44, 44, 7, 7,
    7, 29, 31, 31, 31, 68, 68, 68, 2, 2,
    17, 17, 30, 30, 24, 24, 28, 28, 58, 58,
    12, -13, -13, -31, -31, -29, -29, 43, 43, 43,
    -31, -31, -3, -30, -30, -23, -23, -14, -24, -3,
    -3, -47, -47, -12, -27, -27, -44, -46, -26, 31,
    29, -53, -65, 25, -6, -3, -7, -4, -4, -8,
    -4, 1, -3, -3, -6, -4, -47, -47, -47, -23,
    -23, -5, -7, -9, -7, -20, -13, -9, -9, -29,
    -23, 1, 12, 12, 0, 0, 0, -6, 5, -6,
    -3, -3, -2, -4, -3, -3,
)
INTERNAL_TO_NATIONAL = (
    65, -1, -1,
    -1, -1, 31, 31, 47, 47, 29, 29, 53, 31,
    31, 46, 44, 30, 30, -7, -7, -7, 13, 13,
    -2, -2, 23, 23, 24, -21, -21, 27, 27, 47,
    47, 47, 26, 14, -33, -33, -33, -17, -17, 3,
    -29, 12, -12, -31, -31, -31, 3, 3, -24, -24,
    -44, -44, -30, -30, -28, -28, 23, 23, 6, 7,
    29, 8, 3, 4, 4, 20, 4, 23, 6, 3,
    3, 4, -1, 13, 9, 7, 5, 7, 9, 9,
    -43, -43, -43, -68, -68, -68, -58, -58, -25, -29,
    -31, 6, -1, 6, 0, 0, 0, 3, 3, 4,
    2, 3, 3, -5, -12, -12,
)


def internal_index(species):
    """-> the index the record carries for a National Dex number."""
    shift = species - FIRST_UNALIGNED
    if 0 <= shift < len(NATIONAL_TO_INTERNAL):
        return species + NATIONAL_TO_INTERNAL[shift]
    return species


def national(index):
    """-> the National Dex number of an index the record carries."""
    shift = index - FIRST_UNALIGNED
    if 0 <= shift < len(INTERNAL_TO_NATIONAL):
        return index + INTERNAL_TO_NATIONAL[shift]
    return index


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
    want = struct.unpack_from("<H", raw, OFF_CHECKSUM)[0]
    got = checksum(plain)
    if got != want:
        raise ValueError(f"checksum {got:#06x}, header says {want:#06x} - not a valid record")
    return plain


def encrypt(plain):
    """-> the bytes to put on the wire, with the checksum written from the body itself."""
    if len(plain) not in (SIZE_STORED, SIZE_PARTY):
        raise ValueError(f"{len(plain)} bytes, expected {SIZE_STORED} or {SIZE_PARTY}")
    body = bytearray(plain)
    struct.pack_into("<H", body, OFF_CHECKSUM, checksum(body))
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
    return checksum(raw) == struct.unpack_from("<H", raw, OFF_CHECKSUM)[0]


def load(raw):
    """-> a plain PARTY record from a record in any of the four shapes, stored or party."""
    plain = bytes(raw) if is_plain(raw) else decrypt(raw)
    if len(plain) == SIZE_STORED:
        plain += bytes(SIZE_PARTY - SIZE_STORED)
    return plain


def from_wire(body):
    """-> the plain party record inside a 348-byte trade body, prefix checked and dropped."""
    body = bytes(body)
    if len(body) != SIZE_WIRE:
        raise ValueError(f"a trade body is {SIZE_WIRE} bytes, not {len(body)}")
    if body[:len(WIRE_PREFIX)] != WIRE_PREFIX:
        raise ValueError(f"prefix {body[:len(WIRE_PREFIX)].hex()}, expected {WIRE_PREFIX.hex()}")
    return load(body[len(WIRE_PREFIX):])


def to_wire(plain):
    """-> the 348-byte body of a trade message carrying a plain party record."""
    if len(plain) != SIZE_PARTY:
        raise ValueError(f"a party record is {SIZE_PARTY} bytes, not {len(plain)}")
    return WIRE_PREFIX + encrypt(plain)


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
    fields["species"] = national(fields["species_internal"])
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
        if key == "species":
            struct.pack_into("<H", out, OFF_SPECIES, internal_index(value))
        elif key in SCALARS:
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


# What `build` puts in a record the caller does not name. Every value is one a retail console's own
# record carries: this game's version byte, the console's language, a Poke Ball, the friendship a
# caught Pokemon starts at, and no handler, which is what an untraded record reads as. `level`,
# `met_level` and `obedience_level` agree at 1, the level a record with no experience is.
BUILD_DEFAULTS = {
    "sanity": 0,
    "version": VERSION_SCARLET,
    "battle_version": 0,
    "language": 3,
    "affixed_ribbon": -1,
    "current_handler": 0,
    "ht_language": 0,
    "ht_friendship": 0,
    "ot_friendship": 50,
    "met_date": (25, 9, 22),
    "met_location": 64,
    "met_level": 1,
    "obedience_level": 1,
    "level": 1,
    "experience": 0,
    "ball": 4,
    "ivs": (31, 31, 31, 31, 31, 31),
    "height_scalar": 128,
    "weight_scalar": 128,
    "scale": 128,
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
            f"(id {f['trainer_id']}) moves {f['moves']} ivs {f['ivs']}")
