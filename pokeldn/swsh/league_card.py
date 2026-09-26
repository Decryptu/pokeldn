"""The League Card: the 456-byte TrainerCard a Sword/Shield snapshot carries at 0x924.

A console that trades with us offers to keep it and files it unchanged (docs/swsh_trade.md, The
League Card). Field offsets are PKHeX's TrainerCard8 and TrainerCard8Poke.
"""
import struct

LENGTH = 456
NAME_LENGTH = 0x1A

# name -> (offset, struct format)
FIELDS = {
    "language": (0x1B, "B"),
    "trainer_id": (0x1C, "<I"),     # (SID << 16 | TID) mod 10**6; the key a console matches on
    "dex_owned": (0x20, "<H"),
    "shiny_found": (0x22, "<H"),
    "game": (0x24, "B"),            # 0 Sword, 1 Shield
    "starter": (0x25, "B"),         # 0 Grookey, 1 Scorbunny, 2 Sobble
    "curry_types": (0x26, "<H"),
    "roto_rally_score": (0x28, "<i"),
    "caught": (0x2C, "<i"),
    "dex_complete": (0x30, "B"),    # the Rotom-Dex icon top right of a received card
    "gender": (0x38, "B"),
    "started_year": (0x170, "<H"),
    "started_month": (0x172, "B"),
    "started_day": (0x173, "B"),
    "timestamp_printed": (0x1A8, "<I"),
    "armor_dex_complete": (0x1B4, "B"),
    "crown_dex_complete": (0x1B5, "B"),
}
POKE_OFFSET, POKE_SIZE, POKE_SLOTS = 0xC8, 0x1C, 6
POKE_FIELDS = {"species": (0x00, "<I"), "form": (0x04, "<I"), "gender": (0x08, "<I"),
               "shiny": (0x0C, "B"), "ec": (0x10, "<I"), "form_argument": (0x18, "<i")}


def field(name):
    """-> (offset, format) for a card field; `pokeN_FIELD` (N 1..6) names a showcase Pokemon's, and
    a hex offset (`0x31`) names that one byte."""
    if name.startswith("0x") and int(name, 16) < LENGTH:
        return int(name, 16), "B"
    if name in FIELDS:
        return FIELDS[name]
    if name.startswith("poke") and "_" in name:
        slot, sub = name[4:].split("_", 1)
        if slot.isdigit() and 1 <= int(slot) <= POKE_SLOTS and sub in POKE_FIELDS:
            at, fmt = POKE_FIELDS[sub]
            return POKE_OFFSET + (int(slot) - 1) * POKE_SIZE + at, fmt
    raise KeyError(f"no League Card field {name!r}")


def set_fields(card, **values):
    """-> the card with each named field replaced; `name` is the trainer name (UTF-16, 12 chars)."""
    if len(card) != LENGTH:
        raise ValueError(f"{len(card)} bytes, expected {LENGTH}")
    out = bytearray(card)
    for name, value in values.items():
        if name == "name":
            encoded = value.encode("utf-16-le")
            if len(encoded) + 2 > NAME_LENGTH:
                raise ValueError(f"{value!r} is too long for the card's name field")
            out[0:NAME_LENGTH] = encoded.ljust(NAME_LENGTH, b"\x00")
            continue
        at, fmt = field(name)
        struct.pack_into(fmt, out, at, value)
    return bytes(out)


def read(card):
    """-> {field: value} for every named field, the name and the six showcase Pokemon."""
    out = {"name": card[:NAME_LENGTH].decode("utf-16-le").split("\x00", 1)[0]}
    for name in FIELDS:
        at, fmt = FIELDS[name]
        out[name] = struct.unpack_from(fmt, card, at)[0]
    for slot in range(1, POKE_SLOTS + 1):
        for sub in POKE_FIELDS:
            at, fmt = field(f"poke{slot}_{sub}")
            out[f"poke{slot}_{sub}"] = struct.unpack_from(fmt, card, at)[0]
    return out
