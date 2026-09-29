"""The French Easy Chat vocabulary: slots rendered on the console's screen agree with
sEasyChatGroup_* read from ROM."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.text import easychat, easychat_french  # noqa: E402
from pokeldn.frlg.text.easychat import WORDS                        # noqa: E402


def test_the_rom_table_agrees_with_every_word_read_off_the_console_screen():
    """A render and a ROM read of the same slot must agree."""
    overlap = {slot: (word, easychat_french.ROM_WORDS[slot])
               for slot, word in easychat_french.CONFIRMED.items()
               if slot in easychat_french.ROM_WORDS}

    assert overlap, "no slot has been established both ways yet"
    assert [rendered for rendered, in_rom in overlap.values()] \
        == [in_rom for _rendered, in_rom in overlap.values()], overlap


def test_the_two_feelings_words_the_console_rendered_are_in_the_table_it_was_reading_from():
    """EC_WORD_ENJOY rendered STRESSE and EC_WORD_DONE rendered FURAX on the console."""
    assert easychat_french.french(WORDS["enjoy"]) == "STRESSE"
    assert easychat_french.french(WORDS["done"]) == "FURAX"
    assert easychat_french.ROM_WORDS[WORDS["enjoy"]] == "STRESSE"
    assert easychat_french.ROM_WORDS[WORDS["done"]] == "FURAX"


def test_a_group_read_off_the_console_is_read_whole():
    """A half-read group would let `check` pass a slot nobody has read."""
    from pokeldn.frlg.text import easychat_french_words as table
    for group, (_address, words) in table.GROUPS.items():
        indices = sorted(words)
        assert indices == list(range(len(indices))), \
            f"EC_GROUP {group} has a hole at {set(range(len(indices))) - set(indices)}"


def test_species_and_move_slots_need_no_table_at_all():
    """Species and move slots print gSpeciesNames / gMoveNames [decomp:src/easy_chat.c:155];
    AKWAKWAK stored POKEMON/55."""
    assert easychat.is_language_safe(easychat.species_word(55))
    assert easychat.is_language_safe(easychat.move_word(177))
    assert easychat_french.check([easychat.species_word(55), easychat.move_word(177)]) == ()


def test_render_prefers_what_the_console_prints_over_the_english_slot_name():
    line = easychat_french.render([WORDS["enjoy"], WORDS["done"], WORDS["sad"]])

    assert line.startswith("STRESSE FURAX ")
    assert "enjoy" not in line and "done" not in line
