"""The Pokemon record a Legends Z-A offer carries.

The record is the generation 8 and 9 entity: an encryption constant, a sanity halfword, a
checksum, then four 0x50-byte blocks shuffled by the constant, 0x148 bytes stored and 0x158 with
the party tail. `pokeldn.sv.pokemon` already codes that shell and Z-A's records validate under it
unchanged, so the crypto, the block shuffle and the checksum are imported rather than restated.

The layout is Scarlet's. Measured on nine records out of three reference sessions:

    0x008   species, national                714 Noibat, 716 Xerneas, 95 Onix
    0x058   nickname, UTF-16LE               the species name in the save's language
    0x0a8   handler's name                   "Player", only on a record whose handler is set
    0x0f8   original trainer's name          "XS" on all nine
    0x148   level, in the party tail         derived by the game from the experience

`docs/za.md`, The offered Pokemon.
"""
from pokeldn.sv import pokemon as _sv

SIZE_STORED = _sv.SIZE_STORED                 # 0x148
SIZE_PARTY = _sv.SIZE_PARTY                   # 0x158
HEADER_SIZE = _sv.HEADER_SIZE                 # 8

# The offer's own framing: a nine-byte header, the record, one trailing byte.
OFFER_HEADER_SIZE = 9
OFFER_TRAILER_SIZE = 1
OFFER_SIZE = OFFER_HEADER_SIZE + SIZE_PARTY + OFFER_TRAILER_SIZE       # 354

OFF_SPECIES = 0x08
OFF_NICKNAME = 0x58
OFF_HT_NAME = 0xA8
OFF_OT_NAME = 0xF8
OFF_LEVEL = SIZE_STORED
NAME_BYTES = 26                               # thirteen UTF-16 code units, NUL-terminated

decrypt = _sv.decrypt
encrypt = _sv.encrypt
checksum = _sv.checksum


def _string(plain, offset):
    raw = plain[offset:offset + NAME_BYTES]
    text = raw.decode("utf-16-le", "replace")
    return text.split("\x00")[0]


def read(plain):
    """-> what a DECRYPTED Z-A record says about itself, in the fields measured for this title."""
    if len(plain) not in (SIZE_STORED, SIZE_PARTY):
        raise ValueError(f"{len(plain)} bytes, expected {SIZE_STORED} or {SIZE_PARTY}")
    out = {
        "species": int.from_bytes(plain[OFF_SPECIES:OFF_SPECIES + 2], "little"),
        "nickname": _string(plain, OFF_NICKNAME),
        "ht_name": _string(plain, OFF_HT_NAME),
        "ot_name": _string(plain, OFF_OT_NAME),
    }
    if len(plain) == SIZE_PARTY:
        out["level"] = plain[OFF_LEVEL]
    return out


def parse_offer(payload):
    """-> (header, decrypted record, trailer) from the 354 bytes an offer message carries."""
    payload = bytes(payload)
    if len(payload) != OFFER_SIZE:
        raise ValueError(f"an offer is {OFFER_SIZE} bytes, not {len(payload)}")
    body = payload[OFFER_HEADER_SIZE:OFFER_HEADER_SIZE + SIZE_PARTY]
    return payload[:OFFER_HEADER_SIZE], decrypt(body), payload[OFFER_HEADER_SIZE + SIZE_PARTY:]


def build_offer(header, plain, trailer=b"\x00"):
    """-> the 354 bytes of an offer message, the record re-encrypted and its checksum refreshed."""
    if len(plain) != SIZE_PARTY:
        raise ValueError(f"a party record is {SIZE_PARTY} bytes, not {len(plain)}")
    return bytes(header) + encrypt(plain) + bytes(trailer)
