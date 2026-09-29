"""What a FRENCH console prints for an Easy Chat word id `(group << 9) | index`: every localized ROM
carries its own `gEasyChatGroup_*` tables (EC_WORD_ENJOY renders as STRESSE). docs/frlg_rom_map.md.
"""

from pokeldn.frlg.text.easychat import UNDEFINED, WORDS, describe_word, is_language_safe
from pokeldn.frlg.text.easychat_french_words import WORDS as ROM_WORDS

# ROM_WORDS is sEasyChatGroup_* read off the console (`--buffer-script string-gather`);
# tests/test_easychat_french.py requires it to agree with CONFIRMED where they overlap.

# Only slots seen on hardware.
CONFIRMED = {
    WORDS["hello"]: "SALUT",                # GREETINGS/15, matches
    WORDS["i_ve_arrived"]: "JE SUIS LA",    # GREETINGS/18, matches
    WORDS["thank_you"]: "MERCI",            # GREETINGS/17, matches
    WORDS["friend"]: "AMIS",                # PEOPLE/51,    matches
    WORDS["why"]: "POURQUOI",               # MISC/37,      matches
    WORDS["enjoy"]: "STRESSE",              # FEELINGS/42,  not "enjoy"
    WORDS["done"]: "FURAX",                 # FEELINGS/60,  not "done"
    # From the encode direction: the console sent these four slots for its default questionnaire
    # phrase, in order [mystery_gift.c:84].
    WORDS["link"]: "CONNEXION",             # TRAINER/9,    matches
    WORDS["with"]: "AVEC",                  # ENDINGS/48,   matches
    WORDS["case"]: "LES",                   # SPEECH/12,    not "case"
    # The ROM holds DRESSEUR, singular; no DRESSEURS exists in the vocabulary.
    WORDS["trainer"]: "DRESSEUR",           # TRAINER/11,   from the table, not from a render
}

# Slots whose French word is not a translation of the English name; verify each slot you use.
DIVERGENT = frozenset({WORDS["enjoy"], WORDS["done"], WORDS["case"]})


# The French FireRed's default Poke Mart questionnaire; `SVR_CHECK_QUESTIONNAIRE` compares all four
# ids in order. Every Mystery Gift session logs the console's current four.
CONSOLE_QUESTIONNAIRE = (0x0209, 0x1030, 0x0E0C, 0x020B)     # CONNEXION AVEC LES DRESSEUR
# A custom phrase the console has held.
CONSOLE_QUESTIONNAIRE_CUSTOM = (0x2A37, 0x123C, 0x24B1, 0x1E25)   # AKWAKWAK FURAX AEROBLAST POURQUOI


class UnverifiedFrenchWord(Exception):
    """A slot nobody has yet seen rendered on the French console."""


def french(value):
    """-> what the French console prints for this id, or None; the ROM table is asked first."""
    value = int(value) & 0xFFFF
    word = ROM_WORDS.get(value)
    return CONFIRMED.get(value) if word is None else word


def render(values):
    """-> the French line, with a '?' for every slot still unobserved."""
    out = []
    for value in values:
        value = int(value) & 0xFFFF
        if value == UNDEFINED:
            continue
        word = french(value)
        out.append(f"?{describe_word(value)}?" if word is None else word)
    return " ".join(out)


def check(values, *, strict=False):
    """-> the ids never seen on a French console; with `strict`, raise instead."""
    unknown = tuple(int(value) & 0xFFFF for value in values
                    if int(value) & 0xFFFF != UNDEFINED
                    and not is_language_safe(value)
                    and french(value) is None)
    if unknown and strict:
        raise UnverifiedFrenchWord(
            "these slots have never been seen rendered on the French console: "
            + ", ".join(describe_word(value) for value in unknown))
    return unknown


def observe(value, word, *, divergent=None):
    """Record what the console printed for a slot. Returns True when this is news."""
    value = int(value) & 0xFFFF
    known = CONFIRMED.get(value)
    if known == word:
        return False
    CONFIRMED[value] = word
    return known is None or known != word


__all__ = [
    "CONFIRMED", "DIVERGENT", "ROM_WORDS", "CONSOLE_QUESTIONNAIRE", "CONSOLE_QUESTIONNAIRE_CUSTOM", "UnverifiedFrenchWord", "check", "french", "observe", "render",
]
