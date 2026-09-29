"""A Sword/Shield Pokemon on the wire: the 0x158-byte party-form PK8 (`pokeldn.gen8`), and the
fixed six-slot party protocol 0x84 carries in its first 0x810 bytes (docs/swsh_protocol.md).
"""
import struct

from pokeldn import gen8
from pokeldn.gen8 import OFF_DYNAMAX_TYPE, SIZE_PARTY, SIZE_STORED   # noqa: F401 - the PK8 view

PARTY_SLOTS = 6
PARTY_BLOCK = PARTY_SLOTS * SIZE_PARTY        # 0x810, and the payload's first 0x810 is exactly this


def decrypt(raw):
    """-> the plain, unshuffled record. Party or stored form; raises on a bad checksum."""
    return gen8.decrypt(raw)


def encrypt(plain):
    """-> the bytes to put on the wire, with the checksum written from the body itself."""
    return gen8.encrypt(plain)


def read(raw):
    """-> what one PK8 says about itself, party stats included when it is the party form."""
    return gen8.read(gen8.decrypt(raw))


def build_from(template_raw, **fields):
    """-> an encrypted PK8 made by editing a real one; fields as `gen8.write`."""
    return encrypt(gen8.write(decrypt(template_raw), **fields))


def party(blob, slots=PARTY_SLOTS):
    """-> one entry per party slot of a 0x84 payload: the read fields, or None for an empty slot.
    An empty slot is an encryption constant of zero; a species of 0 is no evidence of one."""
    if len(blob) < slots * SIZE_PARTY:
        raise ValueError(f"{len(blob)} bytes, need {slots * SIZE_PARTY} for {slots} slots")
    out = []
    for slot in range(slots):
        raw = blob[slot * SIZE_PARTY:(slot + 1) * SIZE_PARTY]
        if struct.unpack_from("<I", raw, 0)[0] == 0:
            out.append(None)
            continue
        fields = read(raw)
        fields["slot"] = slot + 1
        out.append(fields)
    return out
