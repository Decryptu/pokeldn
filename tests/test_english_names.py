"""The English rev10 build's reading of the French addresses (tools/frlg/english_build.py,
docs/frlg_leafgreen.md)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import english_names, rom_map, worker_names  # noqa: E402

ROM_START, ROM_END = 0x08000000, 0x0A000000


def test_it_agrees_with_every_name_the_console_itself_proved():
    """The English build agrees with every name worker_names read off the console."""
    agreed = 0
    for address, ours in worker_names.WORKERS.items():
        theirs = english_names.name(address)
        if theirs is None:
            continue
        agreed += 1
        assert theirs == ours or theirs.lstrip("_") == ours.lstrip("_"), \
            f"0x{address:08X}: we measured {ours}, the English build reads {theirs}"
    assert agreed > 200, "the control is only worth something if it covers most of the table"


def test_the_offsets_are_measured_spans_and_do_not_overlap():
    """Offset runs are sorted and never overlap, so `offset()` answers with the run that covers the
    address."""
    previous = None
    for low, high, _offset, points in english_names.OFFSETS:
        assert ROM_START <= low <= high < ROM_END
        assert points >= 2, "one point is a coincidence, not a run"
        if previous is not None:
            assert low > previous, f"0x{low:08X} overlaps the run that ends at 0x{previous:08X}"
        previous = high


def test_a_bracketed_name_is_marked_as_the_weaker_reading_it_is():
    """BRACKETED names are kept apart from measured ones and never answer for the same address."""
    assert not set(english_names.NAMES) & set(english_names.BRACKETED)
    for address, (name, offset) in english_names.BRACKETED.items():
        assert ROM_START <= address < ROM_END
        assert english_names.offset(address) is None, \
            f"0x{address:08X} is inside a measured run and does not need bracketing"
        assert isinstance(name, str) and isinstance(offset, int)


def test_the_three_division_helpers_have_independent_names():
    helpers = {english_names.bracketed_name(a) for a in (0x081E2694, 0x081E2770, 0x081E2D00)}
    assert helpers == {"__divsi3", "__modsi3", "__umodsi3"}


def test_it_does_not_shadow_what_the_project_measured():
    """A name here agrees with `rom_map.CALLABLE` wherever both hold an address."""
    for name, address in rom_map.CALLABLE.items():
        theirs = english_names.name(address)
        if theirs is None:
            continue
        assert theirs == name or theirs.lstrip("_") == name.lstrip("_"), \
            f"0x{address:08X}: called on hardware as {name}, English build reads {theirs}"
