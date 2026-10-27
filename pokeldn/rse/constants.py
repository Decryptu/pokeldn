"""Emerald's numbers where they differ from FireRed's, from pret/pokeemerald (docs/rse.md). Every
value is the GBA English build's; the Switch build is unreleased."""

from pokeldn.frlg.gift.gift_composer import GameRules

# Game codes, by their first three letters [docs/frlg_rom.md, The play report]. The fourth is the
# language: E English, F French, D German, I Italian, S Spanish, J Japanese.
GAMES = {"AXV": "ruby", "AXP": "sapphire", "BPE": "emerald"}
LANGUAGE_LETTERS = "EFDISJ"

# include/constants/flags.h
FLAG_CAUGHT_LUGIA = 0x91
FLAG_CAUGHT_HO_OH = 0x92
FLAG_RECEIVED_AURORA_TICKET = 0x13A        # sReceivedGiftFlags[0], card flagId 1000 [mystery_gift.c:229]
FLAG_RECEIVED_MYSTIC_TICKET = 0x13B
FLAG_RECEIVED_OLD_SEA_MAP = 0x13C
FLAG_BATTLED_DEOXYS = 0x1AD
FLAG_CAUGHT_MEW = 0x1CA
FLAG_MYSTERY_GIFT_DONE = 0x1E4
SYSTEM_FLAGS = 0x860
FLAG_SYS_POKEDEX_GET = SYSTEM_FLAGS + 0x1             # opens every Pokemon Center 2F attendant [cable_club.inc:803]
FLAG_SYS_NATIONAL_DEX = SYSTEM_FLAGS + 0x36
FLAG_ENABLE_SHIP_SOUTHERN_ISLAND = SYSTEM_FLAGS + 0x53
FLAG_ENABLE_SHIP_BIRTH_ISLAND = SYSTEM_FLAGS + 0x75
FLAG_ENABLE_SHIP_FARAWAY_ISLAND = SYSTEM_FLAGS + 0x76
FLAG_SYS_MYSTERY_GIFT_ENABLE = SYSTEM_FLAGS + 0x7B   # the title menu's MYSTERY GIFT [questionnaire.inc:37]
FLAG_ENABLE_SHIP_NAVEL_ROCK = SYSTEM_FLAGS + 0x80
MAX_FLAG = 0x095F                          # FLAG_UNUSED_0x95F, the last daily flag

# include/constants/vars.h
VAR_STARTER_MON = 0x4023
VAR_ALTERING_CAVE_WILD_SET = 0x403E
VAR_GIFT_UNUSED_1 = 0x40DE                 # written by gifts, read by nothing [vars.h:242]
VAR_GIFT_SLOT_VARS = tuple(range(0x40DF, 0x40E5))
NUM_ALTERING_CAVE_TABLES = 9               # src/data/wild_encounters.constants.json.txt:6

# include/constants/items.h, counted
ITEM_EON_TICKET = 275
ITEM_MYSTIC_TICKET = 370
ITEM_AURORA_TICKET = 371
ITEM_OLD_SEA_MAP = 376
MAX_ITEM = 376                             # ITEMS_COUNT - 1

# data/specials.inc, counted from 0; `special` does not bound the index [scrcmd.c:119]
NUM_SPECIALS = 527
SPECIAL_HAS_ALL_HOENN_MONS = 337
SPECIAL_START_LEGENDARY_BATTLE = 314
SPECIAL_GET_MYSTERY_GIFT_CARD_STAT = 392
SPECIAL_ENABLE_NATIONAL_POKEDEX = 499

NUM_OBJ_EVENT_GFX = 239                    # include/constants/event_objects.h

EMERALD_RULES = GameRules(
    "emerald", VAR_GIFT_UNUSED_1, VAR_GIFT_SLOT_VARS, FLAG_MYSTERY_GIFT_DONE,
    FLAG_RECEIVED_AURORA_TICKET, MAX_ITEM, MAX_FLAG, NUM_OBJ_EVENT_GFX - 1,
    SPECIAL_HAS_ALL_HOENN_MONS, SPECIAL_START_LEGENDARY_BATTLE, SPECIAL_GET_MYSTERY_GIFT_CARD_STAT,
    NUM_SPECIALS - 1)

# The save [include/global.h, src/save.c]: the flash layout, sector signature 0x08012025 and
# checksum are FireRed's; the blocks are larger and fields move.
SAVEBLOCK1_SIZE = 0x3D88
SAVEBLOCK2_SIZE = 0xF2C
SAVEBLOCK2_SPECIAL_SAVE_WARP_FLAGS = 0x09
CONTINUE_GAME_WARP = 1 << 0                # CONTINUE warps to continueGameWarp [overworld.c:1739]
SAVEBLOCK2_ENCRYPTION_KEY = 0xAC
SAVEBLOCK1_CONTINUE_GAME_WARP = 0x0C       # struct WarpData: s8 group, s8 num, s8 warpId, pad, s16 x, s16 y
SAVEBLOCK1_PARTY_COUNT = 0x234
SAVEBLOCK1_PARTY = 0x238
SAVEBLOCK1_MONEY = 0x490
SAVEBLOCK1_FLAGS = 0x1270
SAVEBLOCK1_VARS = 0x139C
SAVEBLOCK1_GAME_STATS = 0x159C
SAVEBLOCK1_MYSTERY_GIFT = 0x322C
SAVEBLOCK1_RAM_SCRIPT = 0x3728             # checksum; magic at +4, the 995-byte body at +8
# Bytes each sector id checksums: SaveBlock2, SaveBlock1 in four, PokemonStorage in nine [save.c]
CHUNK_SIZES = (SAVEBLOCK2_SIZE, 3968, 3968, 3968, SAVEBLOCK1_SIZE - 3 * 3968, *(3968,) * 8, 2000)
MAP_OLDALE_TOWN_POKEMON_CENTER_2F = (2, 3)  # data/maps/map_groups.json


# The Hoenn Pokedex as National Dex numbers, in its order [include/constants/pokedex.h, enum HOENN_DEX
# up to HOENN_DEX_DEOXYS]. Without the National Dex an Emerald console refuses a partner's egg or a
# species outside it [trade.c:1585, pokemon.c:6411].
HOENN_DEX = (
    252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266,
    267, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279, 280, 281,
    282, 283, 284, 285, 286, 287, 288, 289, 63, 64, 65, 290, 291, 292, 293,
    294, 295, 296, 297, 118, 119, 129, 130, 298, 183, 184, 74, 75, 76, 299,
    300, 301, 41, 42, 169, 72, 73, 302, 303, 304, 305, 306, 66, 67, 68,
    307, 308, 309, 310, 311, 312, 81, 82, 100, 101, 313, 314, 43, 44, 45,
    182, 84, 85, 315, 316, 317, 318, 319, 320, 321, 322, 323, 218, 219, 324,
    88, 89, 109, 110, 325, 326, 27, 28, 327, 227, 328, 329, 330, 331, 332,
    333, 334, 335, 336, 337, 338, 339, 340, 341, 342, 343, 344, 345, 346, 347,
    348, 174, 39, 40, 349, 350, 351, 120, 121, 352, 353, 354, 355, 356, 357,
    358, 359, 37, 38, 172, 25, 26, 54, 55, 360, 202, 177, 178, 203, 231,
    232, 127, 214, 111, 112, 361, 362, 363, 364, 365, 366, 367, 368, 369, 222,
    170, 171, 370, 116, 117, 230, 371, 372, 373, 374, 375, 376, 377, 378, 379,
    380, 381, 382, 383, 384, 385, 386,
)


def refuses_offer(console_progress_flags, species, is_egg):
    """Whether an Emerald console with these LinkPlayer progress flags refuses the partner's offer
    of `species` (an internal GBA id)."""
    from pokeldn.frlg.gift.builder import national_species
    if console_progress_flags & 0xF:
        return False
    return is_egg or national_species(species) not in HOENN_DEX


def game_of(code):
    """-> "ruby", "sapphire" or "emerald" for a game code (str or bytes), or None."""
    if isinstance(code, (bytes, bytearray)):
        code = bytes(code).decode("ascii", "replace")
    return GAMES.get(str(code)[:3].upper())
