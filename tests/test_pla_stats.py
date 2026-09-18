"""The stats a console computes for a record it is given, against its own arithmetic.

Both cases are measured: a record built with perfect individual values and every growth value 10
came back out of a console's box with the first set, and the console's own level-68 Gengar the
record was modelled on carries the second. `docs/pla.md`, Choosing what to offer.
"""

from pokeldn.pla import stats

GENGAR_BASE = (60, 65, 60, 110, 130, 75)        # species 94 in the game's own table
NAIVE = 14


def test_the_stats_a_console_computed_for_a_built_record():
    assert stats.stats(GENGAR_BASE, 68, (31,) * 6, (10,) * 6, NAIVE) \
        == (273, 210, 199, 322, 345, 220)


def test_the_stats_a_console_carries_on_its_own_record():
    assert stats.stats(GENGAR_BASE, 68, (30, 21, 14, 22, 26, 9), (5, 0, 0, 9, 7, 0), NAIVE) \
        == (239, 136, 121, 322, 304, 133)


def test_the_growth_multiplier_saturates_and_that_is_why_the_speed_matched():
    """Two records one of which has perfect values compute the same speed, because the individual
    value's bias and the growth value both reach the top of the table."""
    assert stats.bias(31) == 3 and stats.bias(22) == 1
    assert stats.MULTIPLIER[min(10 + stats.bias(31), 10)] == stats.MULTIPLIER[min(9 + stats.bias(22), 10)]
    perfect = stats.stats(GENGAR_BASE, 68, (31,) * 6, (10,) * 6, NAIVE)
    donor = stats.stats(GENGAR_BASE, 68, (30, 21, 14, 22, 26, 9), (5, 0, 0, 9, 7, 0), NAIVE)
    assert perfect[3] == donor[3]
    assert all(perfect[i] > donor[i] for i in (0, 1, 2, 4, 5))


def test_the_nature_table_is_the_one_two_panels_read():
    """Byte 9 drew Lax and byte 14 drew Naive on a console's summary."""
    assert stats.nature_name(9) == "Lax" and stats.nature_name(14) == "Naive"
    assert stats.NATURE_AMP[NAIVE] == (0, 0, 0, -1, 1)       # speed up, special defence down
    assert len(stats.NATURE_AMP) == 25 and len(stats.NATURE_NAMES) == 25


def test_a_nature_out_of_range_is_neutral_rather_than_an_error():
    assert stats.base_stat(100, 50, 200, 0) == stats.base_stat(100, 50, 0, 0)


def test_the_absolute_size_is_the_scalars_against_the_species_average():
    """A console's own level-68 Gengar: scalars 111 and 221, species average 150 and 405."""
    height, weight = stats.absolute_size(150, 405, 111, 221)
    assert height == 146.11766052246094, "the float the record carries, to the bit"
    assert weight == 452.38031005859375
    assert round(stats.scalar_percent(0), 6) == 0.8        # a 32-bit float, not the decimal
    assert round(stats.scalar_percent(255), 6) == 1.2


def test_an_alpha_carries_the_top_scalar():
    """All three alphas in the captured records carry 0xff in all of 0x50, 0x51 and 0x52."""
    height, weight = stats.absolute_size(190, 950, 255, 255)
    assert round(height, 2) == 228.0
    assert round(weight, 2) == 1368.0
