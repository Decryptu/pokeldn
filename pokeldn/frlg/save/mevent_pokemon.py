"""The payload `MEScrCmd_givepokemon` reads: a whole `struct Pokemon` followed by its `struct Mail`
[decomp:src/mystery_event_script.c:234]. docs/frlg_rom.md, `givepokemon`.
"""

from pokeldn.frlg.save import basestats, mon as monmod, stats
from pokeldn.frlg.text import charmap, easychat

# [decomp:include/constants/items.h:125]; ItemIsMail accepts exactly these twelve.
ITEM_ORANGE_MAIL = 121
ITEM_HARBOR_MAIL = 122
ITEM_GLITTER_MAIL = 123
ITEM_MECH_MAIL = 124
ITEM_WOOD_MAIL = 125
ITEM_WAVE_MAIL = 126
ITEM_BEAD_MAIL = 127
ITEM_SHADOW_MAIL = 128
ITEM_TROPIC_MAIL = 129
ITEM_DREAM_MAIL = 130
ITEM_FAB_MAIL = 131
ITEM_RETRO_MAIL = 132
MAIL_ITEMS = frozenset(range(ITEM_ORANGE_MAIL, ITEM_RETRO_MAIL + 1))

MAIL_SIZE = 0x22                # sizeof(struct Mail) [decomp:include/global.h:524]
MAIL_WORDS_COUNT = 9
MAIL_NONE = 0xFF
PLAYER_NAME_LENGTH = 7
TRAINER_ID_LENGTH = 4

LANGUAGE_ENGLISH = 2            # [decomp:include/constants/global.h:21-22]
LANGUAGE_FRENCH = 3
VERSION_FIRE_RED = 4            # [decomp:include/constants/global.h:11]
VERSION_LEAF_GREEN = 5
POKE_BALL = 4                   # ITEM_POKE_BALL's ball index

# BoxPokemon bitfield at 0x13: isBadEgg:1, hasSpecies:1, isEgg:1, blockBoxRS:1
# [decomp:include/pokemon.h:111].
HAS_SPECIES = 1 << 1
IS_EGG = 1 << 2


class MysteryEventPokemonError(Exception):
    """A payload the console would not accept, or would accept and then misread."""


def build_mail(words=(), *, player_name="POKELDN", trainer_id=0, species=0,
               item_id=ITEM_ORANGE_MAIL):
    """A `struct Mail`; GiveMailToMon2 copies all of it over the player's defaults."""
    if item_id not in MAIL_ITEMS:
        raise MysteryEventPokemonError(
            f"item {item_id} is not mail; ItemIsMail accepts {min(MAIL_ITEMS)}..{max(MAIL_ITEMS)}")
    resolved = easychat.resolve_words(words, MAIL_WORDS_COUNT)
    out = bytearray(MAIL_SIZE)
    for index, value in enumerate(resolved):
        out[index * 2:index * 2 + 2] = int(value).to_bytes(2, "little")
    name = charmap.encode(player_name)
    if len(name) > PLAYER_NAME_LENGTH:
        raise MysteryEventPokemonError(
            f"a mail sender name is at most {PLAYER_NAME_LENGTH} characters")
    out[0x12:0x12 + len(name)] = name
    out[0x12 + len(name):0x1A] = b"\xFF" * (8 - len(name))
    out[0x1A:0x1E] = int(trainer_id).to_bytes(4, "little")
    out[0x1E:0x20] = int(species).to_bytes(2, "little")
    out[0x20:0x22] = int(item_id).to_bytes(2, "little")
    return bytes(out)


def exp_for_level(species, level):
    """The lowest experience that reads back as `level`; the party tail is derived from it."""
    low, high = 0, 1_640_000
    while low < high:
        middle = (low + high) // 2
        if stats.level_from_exp(species, middle) < level:
            low = middle + 1
        else:
            high = middle
    if stats.level_from_exp(species, low) != level:
        raise MysteryEventPokemonError(f"no experience value maps to level {level}")
    return low


def build_party_mon(species, level, *, moves=(), pp=(), nickname=None, ot_name="POKELDN",
                    ot_id=0x47ED8822, personality=None, held_item=0, friendship=70,
                    ivs=31, evs=(0,) * 6, language, met_location=0xFF,
                    met_level=None, poke_ball=POKE_BALL, met_game=VERSION_FIRE_RED):
    """A 100-byte encrypted party mon; `language` is the cartridge's gGameLanguage."""
    if species not in basestats.BASE_STATS:
        raise MysteryEventPokemonError(
            f"species {species} has no base-stat entry, so neither its growth rate nor its party "
            "tail can be derived")
    if not 1 <= level <= stats.MAX_LEVEL:
        raise MysteryEventPokemonError("level must be 1..100")
    if len(moves) > 4 or len(pp) > 4:
        raise MysteryEventPokemonError("a mon holds at most four moves")
    personality = ot_id if personality is None else personality
    if personality == (ot_id & 0xFFFFFFFF):
        # key == 0 leaves the secure region in the clear; Mon.from_pk3 cannot tell it from a .pk3.
        personality = (personality ^ 0x9E3779B9) & 0xFFFFFFFF

    canon = bytearray(monmod.PARTY_MON_SIZE)
    canon[0:4] = personality.to_bytes(4, "little")
    canon[4:8] = (ot_id & 0xFFFFFFFF).to_bytes(4, "little")
    if not nickname:
        raise MysteryEventPokemonError(
            "give the mon a nickname: the console never fills the field in, and a blank one shows "
            "as an empty name everywhere")
    name = charmap.encode(nickname)
    if len(name) > 10:
        raise MysteryEventPokemonError("a nickname is at most 10 characters")
    # nickname[POKEMON_NAME_LENGTH] has no terminator slot: a 10-character name fills it [pokemon.h].
    canon[8:18] = name.ljust(10, b"\xff")
    canon[18] = language
    canon[19] = HAS_SPECIES
    ot = charmap.encode(ot_name)
    if len(ot) > PLAYER_NAME_LENGTH:
        raise MysteryEventPokemonError(f"OT name is at most {PLAYER_NAME_LENGTH} characters")
    canon[20:20 + len(ot)] = ot
    canon[20 + len(ot):27] = b"\xFF" * (7 - len(ot))

    growth = bytearray(12)
    growth[0:2] = int(species).to_bytes(2, "little")
    growth[2:4] = int(held_item).to_bytes(2, "little")
    growth[4:8] = exp_for_level(species, level).to_bytes(4, "little")
    growth[9] = friendship

    attacks = bytearray(12)
    for index, move in enumerate(moves):
        attacks[index * 2:index * 2 + 2] = int(move).to_bytes(2, "little")
    for index, points in enumerate(pp):
        attacks[8 + index] = points

    effort = bytearray(12)
    effort[0:6] = bytes(evs)

    misc = bytearray(12)
    misc[1] = met_location
    # metLevel:7, metGame:4, pokeball:4, otGender:1 [decomp:include/pokemon.h:45].
    origins = (((met_level if met_level is not None else level) & 0x7F)
               | ((met_game & 0x0F) << 7)
               | ((poke_ball & 0x0F) << 11))
    misc[2:4] = origins.to_bytes(2, "little")
    iv_word = 0
    for index, value in enumerate((ivs,) * 6 if isinstance(ivs, int) else tuple(ivs)):
        iv_word |= (value & 0x1F) << (5 * index)    # HP, Atk, Def, Spe, SpA, SpD
    misc[4:8] = iv_word.to_bytes(4, "little")

    canon[32:44], canon[44:56] = growth, attacks
    canon[56:68], canon[68:80] = effort, misc
    # The u16 sum of the canonical secure region survives the substruct shuffle.
    checksum = sum(int.from_bytes(canon[32 + i * 2:34 + i * 2], "little")
                   for i in range(24)) & 0xFFFF
    canon[28:30] = checksum.to_bytes(2, "little")

    built = monmod.Mon.from_pk3(bytes(canon))
    if not built.checksum_ok:
        raise MysteryEventPokemonError("built mon does not checksum; refusing to ship it")
    if built.species != species:
        raise MysteryEventPokemonError(
            f"built mon reads back as species {built.species}, not {species}")
    if built.raw[84] != level:
        raise MysteryEventPokemonError(
            f"party tail reads back as level {built.raw[84]}, not {level}; the species may have no "
            "base-stat entry")
    return built


def build_givepokemon_payload(mon, mail=None):
    """The contiguous blob `givepokemon` points at: the mon, then the mail at +sizeof(Pokemon)."""
    raw = mon.party_bytes() if isinstance(mon, monmod.Mon) else bytes(mon)
    if len(raw) != monmod.PARTY_MON_SIZE:
        raise MysteryEventPokemonError(
            f"a party mon is {monmod.PARTY_MON_SIZE} bytes, got {len(raw)}")
    if raw[85] != MAIL_NONE:
        raise MysteryEventPokemonError(
            "the mon's mail byte must be MAIL_NONE (0xFF) going in; GiveMailToMon2 sets it")
    if mail is None:
        return raw + bytes(MAIL_SIZE)
    mail = bytes(mail)
    if len(mail) != MAIL_SIZE:
        raise MysteryEventPokemonError(f"struct Mail is {MAIL_SIZE} bytes, got {len(mail)}")
    held = monmod.decode_mon(raw)["heldItem"]
    mail_item = int.from_bytes(mail[0x20:0x22], "little")
    if held not in MAIL_ITEMS:
        raise MysteryEventPokemonError(
            f"the mon holds item {held}, which ItemIsMail rejects, so the mail would be ignored")
    if held != mail_item:
        raise MysteryEventPokemonError(
            f"the mon holds item {held} but the mail says {mail_item}; GiveMailToMon2 sets the "
            "held item from the mail, so they must agree")
    return raw + mail


def describe_payload(payload):
    mon = monmod.Mon(payload[:monmod.PARTY_MON_SIZE])
    text = mon.describe()
    if len(payload) > monmod.PARTY_MON_SIZE:
        mail = payload[monmod.PARTY_MON_SIZE:]
        item = int.from_bytes(mail[0x20:0x22], "little")
        text += (f"; mail item {item} from {charmap.decode(mail[0x12:0x1A])!r}"
                 if item in MAIL_ITEMS else "; no mail")
    return text


__all__ = [
    "ITEM_ORANGE_MAIL", "MAIL_ITEMS", "MAIL_NONE", "MAIL_SIZE", "MysteryEventPokemonError",
    "build_givepokemon_payload", "build_mail", "build_party_mon", "describe_payload",
    "exp_for_level",
]
