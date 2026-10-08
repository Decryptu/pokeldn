"""Seed-only Scarlet/Violet raid encounter, boss, and reward generation."""

from pokeldn.sv import raid_catalog, raid_generation


def test_growlithe_seed_reproduces_the_observed_guest_reward_order():
    raid = raid_catalog.resolve_raid(0xBD13FB43)
    assert raid["species_name"] == "Growlithe"
    assert raid["encounter"]["stars"] == 2
    # Subject 2 on a fixed reward is not shown to the captured guest; lottery entries are already
    # per-player rolls and retain subject 2 in the source table.
    visible = [reward for reward in raid["rewards"]
               if reward["source"] == "lottery" or reward["subject"] == 0]
    assert [(reward["name"], reward["amount"]) for reward in visible] == [
        ("Exp. Candy S", 3),
        ("Growlithe Fur", 2),
        ("Muscle Feather", 1),
        ("Pearl", 1),
        ("Growlithe Fur", 1),
        ("Oran Berry", 1),
        ("Muscle Feather", 1),
        ("Pearl", 1),
    ]


def test_known_seeds_select_the_captured_encounters():
    expected = {
        0xBD13FB43: (58, 2, 11),       # Growlithe
        0x000F34C3: (624, 2, 8),       # Pawniard
        0xEC24DFC4: (179, 2, 4),       # Mareep
        0x253B06C5: (957, 2, 0),       # Tinkatink
        0xA13A6DBA: (957, 2, 17),      # Tinkatink
        0xFDAE7B7D: (205, 4, 1),       # Forretress
    }
    for seed, (species, stars, tera) in expected.items():
        raid = raid_catalog.resolve_raid(seed)
        assert (raid["encounter"]["species"], raid["encounter"]["stars"],
                raid["tera_type"]) == (species, stars, tera)


def test_seed_finder_snorunt_seed_generates_without_the_old_pawniard_context():
    raid = raid_generation.generate_seed_raid(0x0010843C)
    assert raid["profile"]["nickname"] == "Snorunt"
    assert raid["metadata"] == {
        "species": 361,
        "stars": 2,
        "tera_type": 11,
        "encounter_identifier": 2024,
    }


def test_seed_only_profiles_match_fields_read_from_five_retail_bosses():
    expected = {
        0xBD13FB43: (58, 20, 0xDFB1659E, 19, (54, 39, 24, 33, 38, 25)),
        0xEC24DFC4: (179, 20, 0x0EC24A1F, 9, (55, 24, 29, 24, 31, 25)),
        0x253B06C5: (957, 20, 0x47D87120, 1, (56, 29, 26, 33, 24, 36)),
        0xA13A6DBA: (957, 20, 0xC3D7D815, 22, (50, 27, 26, 27, 25, 39)),
        0xFDAE7B7D: (205, 45, 0x204BE5D8, 8, (134, 99, 158, 53, 64, 66)),
    }
    for seed, (species, level, ec, nature, stats) in expected.items():
        profile = raid_generation.generate_seed_raid(seed)["profile"]
        assert (profile["species"], profile["level"], profile["encryption_constant"],
                profile["nature"], profile["stats"]) == (species, level, ec, nature, stats)
