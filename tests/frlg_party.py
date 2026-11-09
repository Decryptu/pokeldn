"""A FireRed party Pokemon built from its struct: `Mon.from_pk3` derives the party tail."""
from pokeldn.frlg.save import mon
from pokeldn.frlg.text import charmap

TREECKO = 277                                                   # SPECIES_TREECKO, internal id
POUND, LEER = 1, 43
LEVEL_5_MEDIUM_SLOW = 135                                       # exp


def treecko():
    """A decrypted .pk3: header, then the Growth, Attacks, EVs and Misc substructs."""
    pk3 = bytearray(mon.BOX_SIZE)
    pk3[0:4] = (0x12345678).to_bytes(4, "little")               # personality
    pk3[4:8] = (0x0AE73039).to_bytes(4, "little")               # OT id
    pk3[8:18] = charmap.encode("TREECKO", width=10, language=3)
    pk3[18:20] = (0x0203).to_bytes(2, "little")                 # language, egg name flag
    pk3[20:27] = charmap.encode("POKELDN", width=7, language=3)
    growth, attacks, misc = 32, 44, 68
    pk3[growth:growth + 2] = TREECKO.to_bytes(2, "little")
    pk3[growth + 4:growth + 8] = LEVEL_5_MEDIUM_SLOW.to_bytes(4, "little")
    pk3[attacks:attacks + 2] = POUND.to_bytes(2, "little")
    pk3[attacks + 2:attacks + 4] = LEER.to_bytes(2, "little")
    pk3[attacks + 8:attacks + 10] = bytes((35, 30))             # PP
    pk3[misc + 4:misc + 8] = (20 * 0x02108421).to_bytes(4, "little")    # every IV 20
    pk3[28:30] = (sum(int.from_bytes(pk3[i:i + 2], "little")
                      for i in range(32, 80, 2)) & 0xFFFF).to_bytes(2, "little")
    return mon.Mon.from_pk3(bytes(pk3))
