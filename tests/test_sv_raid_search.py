import pytest

from pokeldn.sv.raid_search import candidate, context_combinations, raid_species, search


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


def test_search_uses_the_selected_five_and_six_star_contexts():
    five = {"version": "scarlet", "map_name": "kitakami",
            "progress": "5star", "content": "standard"}
    found = search(0, 250, stars=5, context=five, limit=3)
    assert found and all(row.stars == 5 for row in found)

    black = {"version": "violet", "map_name": "blueberry",
             "progress": "6star", "content": "black"}
    found = search(0, 25, stars=6, context=black, limit=3)
    assert len(found) == 3 and all(row.stars == 6 for row in found)


def test_context_search_expands_any_values_without_duplicate_black_progress():
    contexts = context_combinations(version="any", map_name="paldea",
                                    progress="any", content="any")
    assert len(contexts) == 14  # 2 games × (6 standard progress stages + one black table)
    assert sum(row["content"] == "black" for row in contexts) == 2
    assert all(row["progress"] == "6star" for row in contexts if row["content"] == "black")


def test_raid_species_is_a_named_unique_search_list():
    choices = raid_species()
    assert len({row["id"] for row in choices}) == len(choices)
    assert {row["name"] for row in choices} >= {"Pikachu", "Garchomp"}


def test_search_filters_species_tera_nature_gender_ability_and_exact_ivs():
    expected = candidate(0x000F34C3)
    ranges = tuple((iv, iv) for iv in expected.ivs)
    found = search(0x000F34C3, 1, species=expected.name.lower(), tera_type=expected.tera_type,
                   nature=expected.nature, gender=expected.gender, ability=expected.ability,
                   iv_ranges=ranges)
    assert found == [expected]
    assert found[0].context == {
        "version": "violet", "map_name": "paldea", "progress": "4star",
        "content": "standard",
    }
    assert not search(0x000F34C3, 1, species="definitely not a species")


def test_unset_species_picker_sentinel_means_any_species():
    expected = candidate(0x000F34C3)
    assert search(expected.seed, 1, species="-") == [expected]


def test_unset_species_search_can_return_one_best_result_per_species():
    found = search(0, 2_000, unique_species=True, limit=100)
    assert len(found) > 1
    assert len({row.species for row in found}) == len(found)


def test_result_limit_is_configurable():
    assert len(search(0, 1_000, limit=3)) == 3


def test_search_can_be_cancelled_and_bounds_cross_context_work():
    contexts = context_combinations(version="any", map_name="any",
                                    progress="any", content="any")
    assert search(0, 100, contexts=contexts, cancelled=lambda: True) == []
    with pytest.raises(ValueError, match="seed/context combinations"):
        search(0, 1_000_000, contexts=contexts)
