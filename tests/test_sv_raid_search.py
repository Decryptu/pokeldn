from pokeldn.sv.raid_search import candidate, search


def test_candidate_exposes_the_generated_encounter_stats_and_ivs():
    found = candidate(0x000F34C3)
    assert (found.name, found.stars, found.level, found.tera_type) == ("Pawniard", 2, 20, 8)
    assert found.ivs == (31, 31, 31, 31, 31, 31)
    assert found.stats == (54, 40, 39, 35, 27, 29)
    assert not found.shiny


def test_candidate_reports_shininess_from_the_generated_pk9_identity():
    found = candidate(0x00000EFF)
    assert found.name == "Eiscue" and found.shiny


def test_search_ranks_and_filters_deterministically():
    easiest = search(0, 250, "overall", stars=2, limit=5)
    assert len(easiest) == 5
    assert all(row.stars == 2 for row in easiest)
    assert [row.score for row in easiest] == sorted(row.score for row in easiest)
    assert easiest == search(0, 250, "overall", stars=2, limit=5)


def test_hardest_search_reverses_the_ranking():
    hardest = search(0, 250, "hardest", limit=5)
    assert [row.score for row in hardest] == sorted(
        (row.score for row in hardest), reverse=True)


def test_search_can_find_only_shiny_encounters():
    found = search(0, 10_000, "overall", shiny=True, limit=3)
    assert len(found) == 3 and all(row.shiny for row in found)
