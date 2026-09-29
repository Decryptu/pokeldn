"""The stats Legends Arceus computes for a record (PKHeX's `PA8.LoadStats`), and its nature table.

A trade rewrites the party tail's stats with these; verified against a console's own numbers
(docs/pla.md, The stats the game computes).
"""

import math
import struct

MULTIPLIER = (0, 2, 3, 4, 7, 8, 9, 14, 15, 16, 25)
MULTIPLIER_MAX = 10

# Per nature, in the game's order: attack, defence, special attack, special defence, speed; 1 raises
# by a tenth, -1 lowers.
NATURE_AMP = (
    (0, 0, 0, 0, 0),    # 0  Hardy
    (1, -1, 0, 0, 0),   # 1  Lonely
    (1, 0, 0, 0, -1),   # 2  Brave
    (1, 0, -1, 0, 0),   # 3  Adamant
    (1, 0, 0, -1, 0),   # 4  Naughty
    (-1, 1, 0, 0, 0),   # 5  Bold
    (0, 0, 0, 0, 0),    # 6  Docile
    (0, 1, 0, 0, -1),   # 7  Relaxed
    (0, 1, -1, 0, 0),   # 8  Impish
    (0, 1, 0, -1, 0),   # 9  Lax
    (-1, 0, 0, 0, 1),   # 10 Timid
    (0, -1, 0, 0, 1),   # 11 Hasty
    (0, 0, 0, 0, 0),    # 12 Serious
    (0, 0, -1, 0, 1),   # 13 Jolly
    (0, 0, 0, -1, 1),   # 14 Naive
    (-1, 0, 1, 0, 0),   # 15 Modest
    (0, -1, 1, 0, 0),   # 16 Mild
    (0, 0, 1, 0, -1),   # 17 Quiet
    (0, 0, 0, 0, 0),    # 18 Bashful
    (0, 0, 1, -1, 0),   # 19 Rash
    (-1, 0, 0, 1, 0),   # 20 Calm
    (0, -1, 0, 1, 0),   # 21 Gentle
    (0, 0, 0, 1, -1),   # 22 Sassy
    (0, 0, -1, 1, 0),   # 23 Careful
    (0, 0, 0, 0, 0),    # 24 Quirky
)

NATURE_NAMES = (
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
)

# The stat order of a record's own fields, and the amplifier index each one reads.
AMP_INDEX = (None, 0, 1, 4, 2, 3)       # hp, atk, def, spe, spa, spd


def bias(iv):
    """-> what an individual value adds to the growth value before the multiplier is looked up."""
    return 3 if iv >= 31 else 2 if iv >= 26 else 1 if iv >= 20 else 0


def ganbaru(base, iv, gv, level):
    """-> the growth term, which is the part of a stat the grit items raise."""
    step = math.sqrt(base) * MULTIPLIER[min(gv + bias(iv), MULTIPLIER_MAX)]
    return math.floor((step + level) / 2.5 + 0.5)        # rounded away from zero, as the game does


def base_hp(base, level):
    return int(((level / 100.0) + 1.0) * base) + level


def base_stat(base, level, nature, amp_index):
    initial = int((((level / 50.0) + 1.0) * base) / 1.5)
    amp = NATURE_AMP[nature % len(NATURE_AMP)][amp_index]
    if amp > 0:
        return 110 * initial // 100
    if amp < 0:
        return 90 * initial // 100
    return initial


def stats(base, level, ivs, gvs, nature):
    """-> the six stats a console computes, in the record's own order.

    `base` is the species entry's own six, `nature` the byte at 0x21.
    """
    out = []
    for i, amp_index in enumerate(AMP_INDEX):
        term = (base_hp(base[i], level) if amp_index is None
                else base_stat(base[i], level, nature, amp_index))
        out.append(ganbaru(base[i], ivs[i], gvs[i], level) + term)
    return tuple(out)


def nature_name(nature):
    return NATURE_NAMES[nature] if nature < len(NATURE_NAMES) else f"nature {nature}"


# The game's 32-bit float constants; rounding through a double moves the height.
SCALAR_STEP = struct.unpack("<f", struct.pack("<I", 0x3ECCCCCE))[0]      # +/- 20% per scalar step
SCALAR_BASE = struct.unpack("<f", struct.pack("<I", 0x3F4CCCCD))[0]      # 0.8 at scalar 0


def _f32(value):
    """-> `value` as the 32-bit float the record stores, which is what the game computes in."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def scalar_percent(scalar):
    """-> the factor a size scalar stands for, 0.8 at 0 and 1.2 at 255."""
    percent = _f32(scalar / 255.0)
    return _f32(_f32(percent * SCALAR_STEP) + SCALAR_BASE)


def absolute_size(base_height, base_weight, height_scalar, weight_scalar):
    """-> (height, weight) for the floats at 0xac and 0xb0, in centimetres and hectograms."""
    height = scalar_percent(height_scalar)
    return (_f32(base_height * height),
            _f32(base_weight * _f32(height * scalar_percent(weight_scalar))))
