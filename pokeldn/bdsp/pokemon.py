"""A BDSP Pokemon on the wire: the 328-byte stored-form PB8 a `NetTradePokeData` carries.

The format is `pokeldn.gen8`; Sword sends the party form, BDSP the stored one (docs/bdsp_trade.md).
"""
from pokeldn import gen8
from pokeldn.gen8 import (                                             # noqa: F401 - the PB8 view
    BLOCK_ORDER, BLOCK_SIZE, HEADER_SIZE, IV32_EGG, IV32_NICKNAMED, NAME_LENGTH, OFF_ABILITY,
    OFF_BALL, OFF_CURRENT_HANDLER, OFF_EGG_DATE, OFF_EGG_LOCATION, OFF_EVS, OFF_EXPERIENCE,
    OFF_FORM, OFF_GENDER, OFF_HELD_ITEM, OFF_HT_FRIENDSHIP, OFF_HT_ID, OFF_HT_LANGUAGE,
    OFF_HT_NAME, OFF_IVS, OFF_LANGUAGE, OFF_MET_DATE, OFF_MET_LEVEL, OFF_MET_LOCATION,
    OFF_MOVES, OFF_MOVE_PP, OFF_MOVE_PP_UPS, OFF_NATURE, OFF_NICKNAME, OFF_OT_FRIENDSHIP,
    OFF_OT_NAME, OFF_PID, OFF_RELEARN, OFF_SID, OFF_SPECIES, OFF_TID, OFF_VERSION,
    checksum, invert, permute,
)

SIZE_STORED = gen8.SIZE_STORED                # 328 = 0x148, the stored form and what BDSP trades


def decrypt(raw):
    """-> the plain, unshuffled 328 bytes; raises if the checksum does not agree.

    BLOCK_ORDER[sv] is the read order, applied directly; the checksum cannot catch an inversion.
    """
    if len(raw) != SIZE_STORED:
        raise ValueError(f"{len(raw)} bytes, expected {SIZE_STORED}")
    return gen8.decrypt(raw)


def encrypt(plain):
    if len(plain) != SIZE_STORED:
        raise ValueError(f"{len(plain)} bytes, expected {SIZE_STORED}")
    return gen8.encrypt(plain)


def read(raw):
    """-> what a received Pokemon says about itself: twelve measured fields and PKHeX's rest."""
    return gen8.read(decrypt(raw))


def build_from(template_raw, **fields):
    """-> an encrypted PB8 made by editing a real one; fields as `gen8.write`, without the party
    `level` and `stats`. Any `gen8.load` shape works as a template; the party tail is dropped."""
    return encrypt(gen8.write(gen8.load(template_raw)[:SIZE_STORED], **fields))


def fresh(raw):
    """-> the encrypted PB8 under a new PID and encryption constant, shiny state kept, for a save
    that already holds this one (`gen8.fresh_identity`)."""
    return encrypt(gen8.fresh_identity(gen8.load(raw)[:SIZE_STORED]))
