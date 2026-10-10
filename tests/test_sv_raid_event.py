"""Scarlet / Violet event Tera Raids (docs/sv_raid.md, Event raids): the boss and the encounter a
seed draws against PKHeX, the RaidPoint of an event raid, and, where Project Pokemon's EventsGallery
is cloned beside the code, every delivery's tables against their JSON and their Encounters.txt."""
import json
import os
import re
import struct
import subprocess
import sys

import pytest

from pokeldn import gen9
from pokeldn.sv import raid, raid_encounter, raid_event, raid_scan, raid_search

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# A clone of the whole gallery, its JSON and Encounters.txt included: POKELDN_EVENTS_GALLERY or EventsGallery/.
GALLERY = os.path.join(os.environ.get("POKELDN_EVENTS_GALLERY", os.path.join(ROOT, "EventsGallery")),
                       "Released", "Gen 9", "SV", "Raid Events")
needs_gallery = pytest.mark.skipif(not os.path.isdir(GALLERY),
                                   reason="needs projectpokemon/EventsGallery cloned as EventsGallery/")


def row(**fields):
    """-> an event row as `raid_event.encounter_row` makes one; the fields not given are a
    one-star encounter's that fixes nothing."""
    out = dict(species=25, form=0, ability=0, flawless_ivs=0, level=12, capture_level=12,
               moves=[33, 0, 0, 0], tera=1, stars=1, rate=1, identifier=1, fixed_rewards="1",
               lottery_rewards="1", boss_desc=[500] + [0] * 36, evs=[0] * 6, rom=0, group=1,
               capture_rate=1, ivs=None, gender=None, nature=None, shiny=0, scale_type=0, scale=0,
               held_item=0)
    out.update(fields)
    return out


SEVEN = [31] * 6
# Encounters of EventsGallery deliveries and seeds, and what PKHeX.Core 26.8.26's
# EncounterDist9/EncounterMight9.GenerateSeed32 gives for them (the trainer's ID set to the battle's
# fake one): EC, PID, IVs (HP Atk Def Spe SpA SpD), ability, gender, nature, (height, weight, scale),
# Tera type. Two seeds draw a shiny PID that a shiny lock turns away.
PKHEX = [
    ("002 7-star Charizard", row(species=6, ability=4, level=100, capture_level=100, ivs=SEVEN,
                                  tera=17, gender=0, nature=15, shiny=1, scale_type=6, scale=128,
                                  stars=7, capture_rate=2),
     0x52E6B438, (1971592851, 4052610882, (31,) * 6, 94, 0, 15, (92, 136, 128), 15)),
    ("082 shiny Rayquaza", row(species=384, ability=2, flawless_ivs=4, level=75, tera=17, nature=4,
                               shiny=2, scale_type=6, scale=128, stars=5),
     0x269E0D37, (1228634002, 2827916871, (31, 31, 31, 4, 29, 31), 76, 2, 4, (139, 203, 128), 15)),
    ("082 shiny Rayquaza", row(species=384, ability=2, flawless_ivs=4, level=75, tera=17, nature=4,
                               shiny=2, scale_type=6, scale=128, stars=5),
     0x6513270E, (2276495721, 2624503458, (25, 31, 24, 31, 31, 31), 76, 2, 4, (76, 57, 128), 15)),
    ("012 7-star Pikachu, XL", row(species=25, ability=4, level=100, capture_level=100, ivs=SEVEN,
                                    tera=12, gender=0, nature=17, shiny=1, scale_type=5,
                                    evs=[252, 6, 0, 0, 252, 0], held_item=236, stars=7),
     0xA6A3A450, (3376484011, 989234454, (31,) * 6, 31, 0, 17, (138, 152, 241), 10)),
    ("017 Ditto, 0 Attack", row(species=132, ability=4, level=75, moves=[144, 0, 0, 0],
                                ivs=[31, 0, 31, 31, 31, 31], stars=5),
     0x128B2F33, (891853198, 864721478, (31, 0, 31, 31, 31, 31), 150, 2, 19, (106, 164, 63), 14)),
    ("015 Blissey", row(species=242, ability=1, flawless_ivs=4, level=75, gender=1, stars=5),
     0x892F902B, (2882337414, 714208213, (31, 31, 6, 31, 31, 4), 131, 1, 22, (40, 122, 49), 6)),
    ("001 Eevee", row(species=133, ability=0, flawless_ivs=4, level=75, stars=5),
     0x9531985D, (3083797176, 1913557168, (31, 31, 31, 28, 31, 25), 91, 0, 23, (195, 121, 55), 16)),
    ("031 7-star Hisuian Decidueye", row(species=724, form=1, ability=4, level=100, ivs=SEVEN,
                                         tera=13, gender=0, nature=3, shiny=1, scale_type=6,
                                         scale=128, stars=7),
     0x0ED90475, (829845200, 2014631547, (31,) * 6, 113, 0, 3, (168, 76, 128), 11)),
    ("013 Walking Wake, shiny draw locked", row(species=1009, ability=2, flawless_ivs=4, level=75,
                                                tera=12, shiny=1, scale_type=6, scale=128, stars=5),
     0x00000EFF, (580745562, 45976688, (20, 31, 31, 6, 31, 31), 281, 2, 24, (73, 35, 128), 10)),
    ("013 Walking Wake, shiny draw locked", row(species=1009, ability=2, flawless_ivs=4, level=75,
                                                tera=12, shiny=1, scale_type=6, scale=128, stars=5),
     0x00001486, (580746977, 40210811, (30, 31, 31, 23, 31, 31), 281, 2, 19, (16, 124, 128), 10)),
]


@pytest.mark.parametrize("case", PKHEX, ids=[f"{c[0]}-{c[2]:08X}" for c in PKHEX])
def test_an_event_boss_is_pkhex_s(case):
    _, encounter, seed, expected = case
    b = raid_encounter.boss_fields(seed, encounter)
    assert (b["encryption_constant"], b["pid"], b["ivs"], b["ability"], b["gender"], b["nature"],
            (b["height_scalar"], b["weight_scalar"], b["scale"]),
            raid_encounter.tera_type(seed, encounter)) == expected
    assert b["held_item"] == encounter["held_item"] and b["evs"] == tuple(encounter["evs"])


# Delivery 20221209, Tyranitar in Scarlet and Salamence in Violet: a four-star rate 2 and two
# five-star rate 1 records each, one with a fixed Tera type.
TYRANITAR = raid_event.Event(20221209, "", tuple(
    row(identifier=no, species=species, stars=stars, rate=rate, rom=rom, group=1)
    for no, species, stars, rate, rom in (
        (2022120901, 248, 4, 2, 1), (2022120902, 248, 5, 1, 1), (2022120903, 248, 5, 1, 1),
        (2022120904, 373, 4, 2, 2), (2022120905, 373, 5, 1, 2), (2022120906, 373, 5, 1, 2))),
    {"1": []}, {"1": []}, (5,) + (0,) * 9)


@pytest.mark.parametrize("seed, version, progress, number", [
    (0x00000001, "scarlet", "6star", 2022120902), (0x9ABCDEF0, "scarlet", "6star", 2022120902),
    (0x12345678, "scarlet", "6star", 2022120901), (0x00000001, "violet", "4star", 2022120904),
    (0xDEADBEEF, "violet", "6star", 2022120906)])
def test_a_seed_draws_the_encounter_pkhex_allows(seed, version, progress, number):
    """PKHeX.Core 26.8.26's GetIsPossibleSlot holds for this record at the progress's stage, and
    for no other record the den could draw."""
    assert raid_event.select(TYRANITAR, seed, version, progress, 1)["identifier"] == number


# A spotlight's two dens, one per version, each boss caught once (delivery 20230228).
SPOTLIGHT = raid_event.Event(20230228, "_3_0_0", (
    row(identifier=2023022801, species=1009, stars=5, rate=1, rom=1, group=1, capture_rate=2),
    row(identifier=2023022802, species=1010, stars=5, rate=1, rom=2, group=2, capture_rate=2),
    row(identifier=2023022803, species=1010, stars=5, rate=1, rom=0, group=3)),
    {"1": []}, {"1": []}, (1, 1) + (0,) * 8)


def test_an_event_offers_each_version_its_own_dens():
    """Group 3 has no dens in the priority table, so its record never spawns."""
    assert raid_event.versions(SPOTLIGHT) == ["scarlet", "violet"]
    assert [(d.group, d.content, d.stars, d.species, d.label) for d in raid_event.dens(SPOTLIGHT, "scarlet")] == [
        (1, "event", (5,), (1009,), "5 stars: Walking Wake")]
    assert [d.label for d in raid_event.dens(SPOTLIGHT, "violet")] == ["5 stars: Iron Leaves"]
    assert [d.group for d in raid_event.dens(SPOTLIGHT)] == [1, 2]
    assert [(d.content, d.label) for d in raid_event.dens(TYRANITAR, "scarlet")] == [("event", "4-5 stars: Tyranitar")]
    assert [(d.content, d.label) for d in raid_event.dens(MIGHTY, "violet")] == [("might", "7 stars: Charizard")]
    assert raid_event.progresses(SPOTLIGHT, "violet", 2) == ["5star", "6star"]
    assert raid_event.progresses(TYRANITAR, "scarlet", 1) == ["4star", "5star", "6star"]
    assert raid_event.catch_once(SPOTLIGHT) == ["Walking Wake", "Iron Leaves"]


@pytest.mark.parametrize("asked, nearest", [
    ({"version": "violet", "group": "1", "progress": "tera"}, ("violet", "6star", "event", 2)),
    ({"version": "scarlet", "group": 1, "progress": "5star"}, ("scarlet", "5star", "event", 1)),
    ({"version": "", "progress": "4star"}, ("scarlet", "6star", "event", 1))])
def test_a_raid_context_moves_to_the_nearest_one_the_event_spawns(asked, nearest):
    context = raid_event.constrain(SPOTLIGHT, {"map_name": "kitakami", **asked})
    assert (context["version"], context["progress"], context["content"], context["group"]) == nearest
    assert context["map_name"] == "paldea"


def test_the_finder_searches_an_events_dens_once_per_stage():
    scope = raid_search.contexts(event=TYRANITAR)
    assert [(c["version"], c["progress"], c["group"], c["den"]) for c in scope] == [
        ("scarlet", "4star", 1, "4-5 stars: Tyranitar"), ("scarlet", "5star", 1, "4-5 stars: Tyranitar"),
        ("violet", "4star", 1, "4-5 stars: Salamence"), ("violet", "5star", 1, "4-5 stars: Salamence")]
    assert raid_search.contexts("violet", progress="6star", event=SPOTLIGHT, group="1") == []
    found = raid_search.search(0, 300, scope[1:2], "overall", limit=5)
    assert found
    for f in found:
        drawn = raid_event.generate(TYRANITAR, f.seed, "scarlet", "5star", 1)
        assert (f.boss, f.stars) == (drawn.boss, drawn.stars)
    assert raid_search.species(TYRANITAR) == [(373, "Salamence"), (248, "Tyranitar")]


def test_the_finder_lists_the_standard_and_black_bosses_only():
    bosses = {row["species"] for rows in raid_encounter.tables()["encounters"].values() for row in rows}
    names = dict(raid_search.species())
    assert set(names) == bosses and 1025 not in names         # species.json names every species


def test_an_event_den_draws_nothing_below_its_star_levels():
    with pytest.raises(ValueError):
        raid_event.select(TYRANITAR, 1, "violet", "tera", 1)
    assert TYRANITAR.groups("violet", "tera") == [] and TYRANITAR.groups("scarlet", "6star") == [1]


# Delivery 20221202's seven-star Charizard: its record, rewards and the RaidPoint words they give.
CHARIZARD_DESC = [2500, 65, 55, 9999, 40, 0, 0, 20, 70, 30, 3, 1, 99, 315, 1, 1, 98, 0, 2, 2, 70, 0,
                  3, 2, 50, 851, 3, 2, 40, 241, 3, 2, 20, 517, 40, 40, 50]
CHARIZARD = row(species=6, ability=4, level=100, capture_level=100, moves=[406, 126, 542, 411],
                ivs=SEVEN, tera=17, gender=0, nature=15, shiny=1, scale_type=6, scale=128, stars=7,
                capture_rate=2, identifier=2022120201, boss_desc=CHARIZARD_DESC,
                fixed_rewards="16547307249463849196", lottery_rewards="16547307249463849196")
FIXED = [(0, 1127, 6, 0), (0, 1128, 4, 0), (0, 49, 5, 0), (2, 0, 10, 0), (2, 0, 5, 1), (0, 2217, 1, 3),
         (0, 1606, 1, 3)]
LOTTERY = [(0, 1127, 3, 15), (0, 1127, 5, 23), (0, 50, 2, 10), (0, 49, 5, 10), (0, 1128, 2, 5),
           (0, 91, 2, 10), (0, 583, 1, 2), (0, 92, 2, 5), (0, 1239, 1, 3), (0, 51, 1, 5), (0, 795, 1, 4),
           (2, 0, 5, 5), (0, 645, 1, 2), (0, 1606, 1, 1)]
MIGHTY = raid_event.Event(
    20221202, "", (CHARIZARD,),
    {CHARIZARD["fixed_rewards"]: [dict(category=c, item=i, amount=n, probability=100, subject=s)
                                  for c, i, n, s in FIXED]},
    {CHARIZARD["lottery_rewards"]: [dict(category=c, item=i, amount=n, probability=p)
                                    for c, i, n, p in LOTTERY]},
    (1,) + (0,) * 9)
DRAGON_SHARD = 1876


def test_a_seven_star_raidpoint_carries_its_crystal_catch_and_rewards():
    found = raid_event.generate(MIGHTY, 0x52E6B438, "scarlet", "6star")
    assert (found.content, found.stars, found.species) == (raid_event.CONTENT_MIGHTY, 7, 6)
    point = raid.raid_point(found)
    # Seven stars, the crystal word 3 (a seven-star event), caught once (2), at level 100.
    assert struct.unpack_from("<4I", point, 0x20) == (7, 3, 2, 100)
    assert list(struct.unpack_from("<37I", point, 0x4C)) == CHARIZARD_DESC
    rows = [struct.unpack_from("<IIII", point, raid.POINT_REWARDS + 16 * i) for i in range(raid.REWARD_ROWS)]
    rows = [r for r in rows if r[0]]
    # The fixed rows in order, a shard as the boss's Dragon one, then 7 to 11 lottery draws.
    assert rows[:7] == [(1127, 6, 0, 0), (1128, 4, 0, 0), (49, 5, 0, 0), (DRAGON_SHARD, 10, 0, 0),
                        (DRAGON_SHARD, 5, 0, 0), (2217, 1, 0, 0), (1606, 1, 0, 0)]
    drawn = {(i or DRAGON_SHARD, n) for _, i, n, _ in LOTTERY}
    assert 7 <= len(rows) - 7 <= 11 and all((i, n) in drawn for i, n, _, _ in rows[7:])
    assert struct.unpack_from("<7I", point, raid.POINT_SUMMARY) == (7, 6, 0, 0, 100, 0, 15)
    assert struct.unpack_from("<11I", raid.descriptor(0x105, found), 18) == (
        0, 6, 0, 0, 7, 15, 0, 2022120201, 0, 0x33, 0)
    boss = gen9.read(gen9.load(raid.boss_record(found)))
    assert (boss["species"], boss["level"], boss["nature"], boss["gender"], boss["scale"]) == (6, 100, 15, 0, 128)


def test_a_catch_once_boss_can_be_served_as_a_normal_catch():
    found = raid_event.generate(MIGHTY, 0x52E6B438, "scarlet", "6star")
    assert raid_event.catch_rule(found) == "caught once per save"
    normal = raid_event.caught_normally(found)
    assert raid_event.catch_rule(normal) == "caught as any raid boss"
    assert struct.unpack_from("<I", raid.raid_point(normal), 0x28) == (raid_event.CAPTURE_NORMAL,)
    assert (normal.boss, normal.rewards) == (found.boss, found.rewards)
    # The lobby shows a record number no save caught: a console that caught 2022120201 refused the
    # catch in the lobby, before any RaidPoint.
    assert struct.unpack_from("<I", raid.descriptor(0x105, normal), 18 + 7 * 4) == (2022120299,)
    assert MIGHTY.rows[0]["capture_rate"] == raid_event.CAPTURE_ONCE        # the event's row stays
    assert MIGHTY.rows[0]["identifier"] == 2022120201
    never = raid_event.Event(1, "", (row(capture_rate=0),), {"1": []}, {"1": []}, (1,) + (0,) * 9)
    uncatchable = raid_event.generate(never, 1, "violet", "tera")
    assert raid_event.caught_normally(uncatchable) is uncatchable
    assert raid_event.catch_rule(uncatchable) == "cannot be caught"


def test_an_event_boss_holds_its_item_and_fights_with_its_effort_values():
    pikachu = row(species=25, ability=4, level=100, capture_level=100, ivs=SEVEN, tera=12, gender=0,
                  nature=17, shiny=1, scale_type=5, evs=[252, 6, 0, 0, 252, 0], held_item=236, stars=7)
    event = raid_event.Event(1, "", (pikachu,), {"1": []}, {"1": []}, (1,) + (0,) * 9)
    found = raid_event.generate(event, 0xA6A3A450, "violet", "5star")
    boss = gen9.read(gen9.load(raid.boss_record(found)))
    assert boss["held_item"] == 236 and boss["evs"][:3] == (252, 6, 0)
    assert found.rewards == ()                  # its tables are empty


def test_a_lottery_without_weight_draws_nothing():
    """A draw under a lottery total of 0 would never end."""
    event = raid_event.Event(1, "", (row(),), {"1": [dict(category=0, item=1124, amount=1, probability=100,
                                                          subject=0)]},
                             {"1": [dict(category=0, item=0, amount=0, probability=0)]}, (1,) + (0,) * 9)
    assert raid_event.generate(event, 7, "violet", "tera").rewards == ((1124, 1),)


def test_species_data_covers_every_standard_boss():
    """species.json is built from the PKHeX revision of raid_base.json and holds every standard and
    black-crystal boss's personal entry, moves' PP and name."""
    with open(raid_encounter.DATA, encoding="utf-8") as fh:
        base = json.load(fh)
    with open(raid_encounter.SPECIES, encoding="utf-8") as fh:
        every = json.load(fh)
    assert every["source"]["pkhex"] == base["source"]["pkhex"]
    rows = [r for table in base["encounters"].values() for r in table]
    assert all(f"{r['species']}/{r['form']}" in every["personal"] and str(r["species"]) in every["species_names"]
               and all(str(m) in every["move_pp"] for m in r["moves"]) for r in rows)


@needs_gallery
def test_every_delivery_reads_as_its_json():
    """EventsGallery's JSON leaves out a raid_enemy record with no species, and names a priority
    table's ten group counts under `Groups`."""
    checked = 0
    for folder in raid_event.deliveries(GALLERY):
        for name in os.listdir(os.path.join(folder, "Files")):
            table = re.sub(r"_\d_\d_\d$", "", name)
            path = os.path.join(folder, "Json", name + ".json")
            if table not in raid_event.SCHEMAS or not os.path.isfile(path):
                continue
            with open(os.path.join(folder, "Files", name), "rb") as fh:
                ours = raid_event.decode(fh.read(), table)
            with open(path, encoding="utf-8") as fh:
                theirs = json.load(fh)
            if table == raid_event.ENEMY:
                ours["Table"] = [t for t in ours["Table"] if t["Info"]["BossPokePara"]["DevId"]]
                theirs["Table"] = [t for t in theirs["Table"] if t["Info"]["BossPokePara"]["DevId"]]
            elif table == raid_event.PRIORITY:
                for t in theirs["Table"]:
                    t["GroupID"] = {f"GroupID{i:02}": t["GroupID"]["Groups"].get(f"GroupID{i:02}", 0)
                                    for i in range(1, raid_event.GROUPS + 1)}
            else:                       # a short table's missing slots: absent, or null in the JSON
                for t in ours["Table"] + theirs["Table"]:
                    for key in [k for k, v in t.items() if v is None]:
                        del t[key]
            assert ours == theirs, path
            checked += 1
    assert checked > 500


@needs_gallery
def test_a_delivery_loads_its_newest_patch():
    charizard = raid_event.load(os.path.join(GALLERY, "002 Charizard the Unrivaled"))
    assert (charizard.identifier, charizard.patch, charizard.dens[:3]) == (20221202, "", (1, 5, 0))
    first = charizard.rows[0]
    assert {k: first[k] for k in CHARIZARD} == CHARIZARD
    assert [(e["category"], e["item"], e["amount"], e["subject"])
            for e in charizard.fixed[first["fixed_rewards"]]] == FIXED
    kingambit = raid_event.load(os.path.join(GALLERY, "147 Kingambit the Unrivaled Round 2"))
    assert kingambit.patch == "_3_0_0"


@needs_gallery
def test_every_delivery_agrees_with_its_encounters_text():
    """scripts/check_sv_raid_events.py over the whole gallery: only Gimmighoul's first 2023 round
    differs, whose lottery tables are malformed (pkNX's text lists them as `0% × Null`)."""
    run = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "check_sv_raid_events.py"), GALLERY,
                          "--seeds", "1"], capture_output=True, text=True, encoding="utf-8",
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if "PKHeX is missing" in run.stderr:
        pytest.skip("needs the PKHeX helper")
    differing = [line.rsplit(": ", 1)[0] for line in run.stdout.splitlines() if line.endswith(" differences")]
    glitched = os.path.join("024 Gimmighoul Spotlight", "Scarlet Event Round 1 (Glitched Rewards)")
    assert differing == [glitched], run.stdout + run.stderr
    assert "537 encounters" in run.stdout


@pytest.mark.parametrize("event, filters", [
    (TYRANITAR, {}), (TYRANITAR, {"one_per_species": True}), (SPOTLIGHT, {"shiny": False}),
    (MIGHTY, {"rewards": {1606: 2, 1127: 10}, "objective": "hardest"})])
def test_the_helper_s_scan_finds_an_event_s_raids_as_python_does(monkeypatch, event, filters):
    if not raid_scan.available():
        pytest.skip("needs the PKHeX helper")
    scope = raid_search.contexts(event=event)
    out = []
    for fast in (True, False):
        monkeypatch.setattr(raid_search, "FAST", fast)
        out.append([(f.seed, f.context["version"], f.context["group"], f.score, f.rewards)
                    for f in raid_search.search(0xFFFFFE00, 1200, scope, **filters)])
    assert out[0] == out[1] and out[0]


def test_the_rewards_listed_are_what_an_event_s_raids_can_give():
    """A fixed Ability Patch and three Tera shards of the boss's Fire type, and a lottery of Bottle
    Caps by twos beside an empty slot: any number of caps up to the ten draws of a five-star raid."""
    fixed = {"1": [dict(category=0, item=1606, amount=1, probability=100, subject=0),
                   dict(category=2, item=0, amount=3, probability=100, subject=0)]}
    caps = dict(category=0, item=795, amount=2, probability=50, subject=0)
    lottery = {"1": [caps, dict(category=0, item=0, amount=0, probability=50, subject=0)]}
    event = raid_event.Event(1, "", (row(stars=5, tera=11),), fixed, lottery, (1,) + (0,) * 9)
    scope = raid_search.contexts(event=event)
    fire = raid_encounter.TERA_SHARDS[9]
    assert raid_search.reward_choices(scope) == {1606: (1,), fire: (3,), 795: tuple(range(2, 21, 2))}
    assert raid_search.reward_choices(scope, tera_type=0) == {}
    # A lottery of caps alone gives one per draw, as many as a raid draws.
    only = raid_event.Event(1, "", (row(stars=5, tera=11),), fixed, {"1": [caps]}, (1,) + (0,) * 9)
    assert raid_search.reward_choices(raid_search.contexts(event=only))[795] == (12, 14, 16, 18, 20)
    violet = raid_search.contexts("violet", event=event)
    found = raid_search.search(0, 150, violet, rewards={795: 8, fire: 3}, limit=100)
    assert found and all(raid_search.gives(f.rewards, {795: 8, fire: 3}) for f in found)
    assert len(found) == sum(1 for s in range(150) if raid_search.gives(
        raid_search.generate(s, violet[0]).rewards, {795: 8}))
