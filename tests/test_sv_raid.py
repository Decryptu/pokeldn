"""Scarlet / Violet Tera Raids (docs/sv_raid.md): the seed against PKHeX and the game's own tables,
the bootstrap against retail bytes, and both launchers against a scripted console."""
import hashlib
import os
import struct
import sys
import zlib

import pytest
import trio

import sv_host
import sv_join
from pokeldn import gen9, sv
from pokeldn.app.catalog import GAMES
from pokeldn.app.command import build
from pokeldn.app.settings import Settings
from pokeldn.ldn import channel_table, game_channel, pia6, pia_connect, reliable5
from pokeldn.sv import (lz4, port2, raid, raid_battle, raid_encounter, raid_event, raid_partners, raid_scan, raid_search,
                        streams)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "switch"))

# PKHeX.Core 26.8.26's `Encounter9RNG.GenerateData` and `Tera9RNG.GetTeraType` on these seeds: seed,
# context, species, form, stars, EC, PID, IVs (HP Atk Def Spe SpA SpD), ability, gender, nature,
# (height, weight, scale), Tera type. Two are Toxtricity, whose nature its form's list gives.
PKHEX = [
    (0xBD13FB43, "violet", "paldea", "4star", "standard", 58, 0, 2, 0xDFB1659E, 0x155C9799,
     (10, 31, 9, 20, 13, 15), 18, 0, 19, (213, 129, 128), 11),
    (0xFDAE7B7D, "violet", "paldea", "4star", "standard", 205, 0, 4, 0x204BE5D8, 0xA809B319,
     (27, 31, 31, 28, 31, 17), 5, 0, 8, (166, 224, 164), 1),
    (0x000F34C3, "violet", "paldea", "4star", "standard", 624, 0, 2, 0x22AC9F1E, 0x36DDA01D,
     (31, 31, 31, 31, 31, 31), 128, 0, 20, (222, 64, 125), 8),
    (0xE7F524F3, "scarlet", "paldea", "5star", "standard", 849, 0, 5, 0x0A928F4E, 0xABDFD5B6,
     (31, 31, 31, 31, 11, 16), 57, 0, 14, (186, 109, 66), 14),
    (0xDA8A6C88, "violet", "paldea", "5star", "standard", 849, 1, 5, 0xFD27D6E3, 0x17705573,
     (31, 31, 16, 31, 3, 31), 58, 0, 15, (43, 181, 161), 3),
    (0x12345678, "scarlet", "kitakami", "6star", "black", 62, 0, 6, 0x34D1C0D3, 0xEDB11674,
     (31, 31, 31, 31, 31, 25), 33, 1, 5, (161, 116, 151), 9),
    (0x9ABCDEF0, "violet", "blueberry", "6star", "black", 89, 1, 6, 0xBD5A494B, 0x8957F6FE,
     (31, 31, 31, 31, 3, 31), 223, 1, 19, (99, 75, 130), 11),
    (0x0BADF00D, "scarlet", "blueberry", "3star", "standard", 170, 0, 1, 0x2E4B5A68, 0xC2E05583,
     (17, 19, 18, 12, 4, 31), 35, 0, 19, (186, 209, 198), 8),
    (0xCAFEBABE, "violet", "kitakami", "beginning", "standard", 173, 0, 1, 0xED9C2519, 0xB6B34799,
     (5, 28, 15, 10, 11, 31), 56, 0, 14, (171, 69, 89), 2),
    (0xDEADBEEF, "scarlet", "paldea", "6star", "black", 691, 0, 6, 0x014B294A, 0x8059C15D,
     (31, 31, 31, 11, 31, 31), 91, 1, 15, (155, 179, 118), 10),
]


@pytest.mark.parametrize("case", PKHEX, ids=[f"{c[0]:08X}-{c[2]}-{c[4]}" for c in PKHEX])
def test_the_boss_a_seed_gives_is_pkhex_s(case):
    seed, version, region, progress, content, species, form, stars, ec, pid, ivs, ability, gender, \
        nature, sizes, tera = case
    found = raid_encounter.generate(seed, version, region, progress, content)
    b = found.boss
    assert (b["species"], b["form"], found.stars, b["encryption_constant"], b["pid"], b["ivs"],
            b["ability"], b["gender"], b["nature"], (b["height_scalar"], b["weight_scalar"], b["scale"]),
            found.tera_type) == (species, form, stars, ec, pid, ivs, ability, gender, nature, sizes, tera)



# Indeedee, five stars, whose retail table gives Tera rule 0: PKHeX.Core 26.8.26's
# `Tera9RNG.GetTeraType` on its own encounter (gem Random), and the game's draw at 0xe27414.
@pytest.mark.parametrize("seed, version, tera", [(0x1D002, "scarlet", 8), (0x6677C, "violet", 11)])
def test_a_default_tera_rule_draws_any_type(seed, version, tera):
    found = raid_encounter.generate(seed, version, "paldea", "5star")
    assert (found.boss["species"], found.tera_type) == (876, tera)

def test_the_bootstrap_matches_retail_records():
    """A retail Violet's bootstrap for seed BD13FB43: its boss record, and the record it puts in an
    empty participant slot (both empty slots of a retail event bootstrap hold the same bytes). A
    French retail Scarlet's bosses for seed 7B741233 (Larvitar, five-star progress) and for the black
    crystal 09F3E337 (Kingambit, battle level 90 with effort values) differ from ours only in their
    host's language and that language's species name."""
    found = raid_encounter.generate(0xBD13FB43)
    assert hashlib.sha256(raid.boss_record(found)).hexdigest() == \
        "fa48396b91413a0e54b86a074b3b10dcf077d8633e9d5a45c7466830325f66c3"
    for seed, content, name, digest in (
            (0x7B741233, "standard", "Embrylex",
             "0350e3a0df16d86164742fb6c7308144fc3d4c7b6752bf91fb335c2d6622a6a4"),
            (0x09F3E337, "black", "Scalpereur",
             "21e85329fd6d4432ab662142831d6af000ff910b5f105fa2259831ebb075adf5")):
        found = raid_encounter.generate(seed, "scarlet", "paldea", "6star", content)
        french = gen9.write(gen9.load(raid.boss_record(found)), nickname=name, language=3)
        assert hashlib.sha256(gen9.encrypt(french)).hexdigest() == digest
    assert hashlib.sha256(raid.empty_participant()).hexdigest() == \
        "befa78ce3efc6035ef511bfab95dd962e1019612e7b9bef80c85fb7955e36ae4"


def test_the_raidpoint_matches_three_retail_points():
    """Words of a two-star (Growlithe, BD13FB43) and a four-star (Forretress, FDAE7B7D) retail
    RaidPoint, Violet, Paldea, four-star progress, a three-star (Larvitar, 7B741233) and a black
    (09F3E337) Scarlet one. Retail rows carry the table's subject (2 guests, 1 host), the rare flag,
    then three more lottery draws under subject 4 and the Tera Shard boost under subject 5."""
    two = raid.raid_point(raid_encounter.generate(0xBD13FB43), name="RaidPoint_12_1_11")
    assert two[:0x30] == bytes.fromhex("52616964506f696e745f31325f315f3131000000000000004000000000000000"
                                       "02000000000000000100000014000000")
    assert struct.unpack_from("<I", two, 0x4C) == (500,) and two[0x50:0xE0] == bytes(0x90)
    assert [struct.unpack_from("<II", two, 0xE4 + 16 * i) for i in range(9)] == [
        (1125, 3), (1961, 2), (566, 1), (1961, 1), (88, 1), (1961, 1), (155, 1), (566, 1), (88, 1)]
    assert struct.unpack_from("<7I", two, 0x3B8) == (2, 58, 0, 0, 20, 0, 11)
    four = raid.raid_point(raid_encounter.generate(0xFDAE7B7D), name="RaidPoint_10_01_07")
    assert struct.unpack_from("<4I", four, 0x20) == (4, 0, 1, 45)
    assert struct.unpack_from("<25I", four, 0x4C) == (
        1200, 60, 40, 9999, 30, 0, 334, 20, 80, 40, 3, 1, 90, 106, 2, 2, 60, 0, 3, 1, 40, 106, 0, 0, 0)
    assert [struct.unpack_from("<II", four, 0xE4 + 16 * i) for i in range(15)] == [
        (1126, 2), (1127, 1), (1983, 4), (567, 2), (1983, 2), (1868, 1), (1868, 2), (1126, 1),
        (157, 1), (1126, 1), (171, 3), (171, 3), (1126, 1), (89, 1), (1983, 2)]
    assert struct.unpack_from("<7I", four, 0x3B8) == (4, 205, 0, 0, 45, 0, 1)
    three = raid.raid_point(raid_encounter.generate(0x7B741233, "scarlet", "paldea", "5star"),
                            name="RaidPoint_14_1_12")
    assert three[:0x30] == bytes.fromhex("52616964506f696e745f31345f315f313200000000000000"
                                         "400000000000000003000000000000000100000023000000")
    assert [struct.unpack_from("<4I", three, 0xE4 + 16 * i) for i in range(18)] == [
        (1125, 1, 0, 0), (1126, 2, 0, 0), (1993, 3, 0, 0), (566, 2, 0, 0), (1993, 2, 0, 2),
        (1867, 1, 0, 0), (1867, 1, 0, 1), (159, 1, 0, 0), (90, 1, 0, 0), (1126, 2, 0, 0),
        (1126, 1, 0, 0), (159, 1, 0, 0), (91, 1, 0, 0), (91, 1, 0, 4), (1125, 1, 0, 4),
        (90, 1, 0, 4), (1867, 2, 0, 5), (0, 0, 0, 0)]
    assert three[0xE4 + 16 * 17:0x3B4] == bytes(0x3B4 - 0xE4 - 16 * 17)
    assert struct.unpack_from("<37I", three, 0x4C)[:14] == (800, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 2, 75,
                                                            201)
    assert struct.unpack_from("<7I", three, 0x3B8) == (3, 246, 0, 1, 35, 0, 14)
    # A black crystal's (record 6045): crystal 1 and the catch level at 0x20, the record's active
    # raidTimeData at 0x30 as retail's, the battle level in the summary.
    black = raid.raid_point(raid_encounter.generate(0x09F3E337, "scarlet", "paldea", "6star", "black"))
    assert struct.unpack_from("<4I", black, 0x20) == (6, 1, 1, 75)
    assert struct.unpack_from("<7I", black, 0x30) == (1, 450, 0, 60, 0, 0, 0)
    assert struct.unpack_from("<14I", black, 0x4C) == (2500, 65, 55, 9999, 35, 0, 0, 20, 75, 35, 1, 1,
                                                       85, 0)
    assert struct.unpack_from("<7I", black, 0x3B8) == (6, 1008, 0, 0, 90, 0, 17)
    assert [struct.unpack_from("<4I", black, 0xE4 + 16 * i) for i in range(20)] == [
        (1127, 4, 0, 0), (1128, 1, 0, 0), (2049, 5, 0, 0), (566, 3, 0, 0), (2049, 3, 0, 2),
        (1879, 3, 0, 0), (1879, 3, 0, 1), (1127, 2, 0, 0), (1233, 1, 0, 0), (1127, 1, 0, 0),
        (566, 2, 0, 0), (1127, 2, 0, 0), (50, 1, 0, 0), (2049, 2, 0, 0), (92, 1, 0, 0),
        (92, 1, 0, 4), (91, 1, 0, 4), (795, 1, 1, 4), (1879, 12, 0, 5), (0, 0, 0, 0)]
    assert black[0xE4 + 16 * 19:0x3B4] == bytes(0x3B4 - 0xE4 - 16 * 19)


def test_a_boss_past_916_is_named_by_its_devid():
    """Tinkatink, National Dex 957, is DevID 1000 in the game's raid table (raid_enemy_02, no 2050)."""
    found = raid_encounter.generate(0x123)
    assert (found.species, found.row["identifier"]) == (957, 2050)
    assert struct.unpack_from("<I", raid.raid_point(found), 0x3BC) == (1000,)
    assert struct.unpack_from("<I", raid.descriptor(0x105, found), 18 + 4) == (1000,)
    assert gen9.read(gen9.load(raid.boss_record(found)))["species"] == 957


def test_a_reward_list_replaces_the_seed_s_and_must_fit():
    found = raid_encounter.generate(0xFDAE7B7D)
    point = raid.raid_point(found, [(15, 500), (15, 500)])
    assert struct.unpack_from("<8I", point, 0xE0) == (0, 15, 500, 0, 0, 15, 500, 0)
    assert point[0x100:0x3B8] == bytes(0x2B8)
    with pytest.raises(ValueError):
        raid.raid_point(found, [(1, 1)] * (raid.REWARD_ROWS + 1))


# What a retail Scarlet joining our host showed in its two empty slots, the partner seed and the
# unlock stage written over the RaidPoint (docs/sv_raid.md, Partners).
RETAIL_PARTNERS = [
    (0, 2, [("Samantha", "Glalie"), ("Zoe", "Sandaconda")]),
    (0x12345678DEADBEEF, 2, [("Henry", "Bronzong"), ("Ava", "Floatzel")]),
    (0x26, 2, [("Ava", "Floatzel"), ("Logan", "Gogoat")]),
    (0, 0, [("Chase", "Dedenne"), ("Samantha", "Snorunt")]),
    (0, 1, [("Chase", "Dedenne"), ("Samantha", "Snorunt")]),
    (0, 3, [("Samantha", "Weavile"), ("Zoe", "Mudsdale")]),
    (0, 4, [("Samantha", "Weavile"), ("Zoe", "Mudsdale")]),
    (0xAF05B3D1838735C0, 4, [("Eli", "Gardevoir"), ("Ava", "Toxapex")])]


@pytest.mark.parametrize("seed, stage, shown", RETAIL_PARTNERS)
def test_a_partner_seed_draws_the_trainers_a_retail_scarlet_showed(seed, stage, shown):
    pool = raid_partners.pool(stage)
    assert [(pool[i].trainer, pool[i].name) for i in raid_partners.draw(seed, stage)] == shown


def test_the_unlock_stage_is_the_progress_less_one_or_six_stars_for_a_black_or_seven_star_raid():
    assert [raid_partners.stage_of(p) for p in raid_encounter.PROGRESS] == [0, 0, 1, 2, 3, 4]
    assert raid_partners.stage_of("3star", "black") == raid_partners.stage_of("4star", "might") == 4
    assert raid_partners.stage_of("3star", "event") == 1


def test_partners_take_four_fifths_of_the_host_pokemon_s_level_whatever_the_stage():
    """Serebii's 16, 40 and 80 are a Lv 20, 50 and 100 host's; retail Scarlets showed Eli's Gardevoir
    at Lv 80 beside a Lv 100 host Pokemon and at Lv 29 beside a Lv 37 one, and the level-16 pool's
    Kirlia and Staravia at Lv 80 beside a Lv 100 one."""
    assert [raid_partners.level_for(host) for host in (20, 50, 100, 37, 12)] == [16, 40, 80, 29, 9]


# Partner seed, then the encryption constant, TID, SID, PID, height and weight both partners' records
# held in an emulated Scarlet 4.0.0's memory during five raid battles (docs/sv_raid.md, Partners).
PARTNER_RECORDS = [
    (0xB040669FFB23783B, 0x1DC0E296, 20321, 19657, 0xAB3F81C5, 106, 198),
    (0x89F4C84C70AD570C, 0x934AC167, 61641, 52925, 0x7BB08914, 88, 136),
    (0x8AF9920EC9C3F0CA, 0xEC615B25, 53888, 50857, 0x86C6240B, 110, 71),
    (0xAB3BCF8D691DC958, 0x8BBB33B3, 30677, 58200, 0x4BA16A7D, 151, 195),
    (0xC39985CC37F43B70, 0x5A91A5CB, 24528, 23528, 0x76D0FABB, 87, 172)]


@pytest.mark.parametrize("record", PARTNER_RECORDS)
def test_a_partner_seed_gives_the_identity_and_size_a_scarlet_gave_its_partners(record):
    assert raid_partners.identity(record[0]) == record[1:]


def test_the_partner_table_is_the_game_s_raid_trainer_tables():
    """raid_partners.json is the game's raid_trainer_01..03 and trdata entries; Serebii's text agrees
    with it, with Steel for Henry, and Dylan and Luke take their species' default Tera type."""
    for stage in range(len(raid_partners.LEVELS)):
        game, ours = raid_partners.game_pool(stage), raid_partners.pool(stage)
        assert [g["species"] for g in game] == [p.species for p in ours]
        assert {g["level"] for g in game} == {raid_partners.LEVELS[stage]}
        assert [raid_encounter.TERA_TYPES[g["tera"]] if g["tera"] is not None else p.trainer
                for g, p in zip(game, ours)] == [p.trainer if p.trainer in ("Dylan", "Luke") and stage > 2
                                                  else p.tera for p in ours]


def test_a_partner_seed_draws_the_trainers_asked_for_in_slot_order():
    for names in ([], ["Luke"], ["Dylan", "Luke"], ["ava", " Eli "]):
        wanted = [raid_partners.trainer(name) for name in names]
        seed = raid_partners.seed_for(4, wanted)
        assert raid_partners.draw(seed, 4)[:len(wanted)] == wanted
    for stage, wanted in ((1, ["Dylan"]), (4, ["Ava", "Ava"]), (4, ["Ava", "Eli", "Zoe"])):
        with pytest.raises(ValueError):
            raid_partners.seed_for(stage, [raid_partners.trainer(name) for name in wanted])
    with pytest.raises(ValueError):
        raid_partners.trainer("Nemona")


def test_the_raidpoint_carries_the_partner_seed_and_the_raid_s_stage():
    found = raid_encounter.generate(0xFDAE7B7D)
    assert struct.unpack_from("<QI", raid.raid_point(found), raid.POINT_PARTNERS) == (0, 2)
    black = raid_encounter.generate(0x09F3E337, "scarlet", "paldea", "6star", "black")
    assert struct.unpack_from("<QI", raid.raid_point(black, partner_seed=0x26),
                              raid.POINT_PARTNERS) == (0x26, 4)
    assert struct.unpack_from("<I", raid.raid_point(found, stage=0), 0x3E0) == (0,)
    with pytest.raises(ValueError):
        raid.raid_point(found, stage=5)


def test_lz4_blocks_cross_an_independent_decoder():
    """Ours read by the NSO reader's `lz4_block`; one liblz4 1.10 made (LZ4_compress_default), with
    overlapping matches, read by both."""
    from pokeldn.switch.nso import lz4_block
    plain = raid.bootstrap(raid_encounter.generate(0xBD13FB43), ())
    assert lz4_block(lz4.compress(plain), len(plain)) == plain
    theirs = bytes.fromhex("ff0552616964506f696e745f504f4b454c444e5f30000100145f504b4c444e0500240f6300"
                           "06500000000000")
    want = b"RaidPoint_POKELDN_0" + bytes(40) + b"PKLDN" * 12 + bytes(30)
    assert lz4.decompress(theirs, 149) == lz4_block(theirs, 149) == want


def test_the_port2_session_and_the_channel_table_are_a_retail_host_s():
    """A retail raid host's type 6 on 0x7C port 2 (its station id replaced) and its six-key table."""
    assert port2.build_session(0x0102030405060708) == bytes.fromhex(
        "06b905b905b906050400bc09000000000000000000bc8080" + "00" * 128 + "000000b90183080706050403020100ba04b9018308"
        "07060504030201b90100b90100b90100bc04000000000100")
    assert raid.channel_table() == bytes.fromhex(
        "b90106b902b9027b0001b902b902320101b902b902320201b902b902320301b902b90280803301b902b902808034"
        "01")


def test_a_search_keeps_the_best_boss_of_the_species_asked_for():
    scope = raid_search.contexts("violet", "paldea", "4star", "standard")
    found = raid_search.search(0, 3000, scope, "physical", species_id=624, limit=3)
    every = [raid_encounter.generate(s) for s in range(3000)]
    pawniard = sorted((r.boss["stats"][0] * r.boss["stats"][2], r.seed) for r in every if r.species == 624)
    assert [(f.score, f.seed) for f in found] == pawniard[:3]


def test_a_search_for_rewards_finds_every_raid_that_gives_them():
    """At least two Ability Patches from a black crystal: every seed whose raid gives them, with its
    rewards; and every quantity a raid gives is among those the finder lists."""
    def totals(rewards):
        out = {}
        for item, quantity in rewards:
            out[item] = out.get(item, 0) + quantity
        return out
    scope = raid_search.contexts("violet", "paldea", "6star", "black")
    found = raid_search.search(0, 8000, scope, rewards={1606: 2}, limit=100)
    every = [raid_encounter.generate(s, "violet", "paldea", "6star", "black") for s in range(8000)]
    giving = {r.seed: r.rewards for r in every if totals(r.rewards).get(1606, 0) >= 2}
    assert giving and {f.seed: f.rewards for f in found} == giving
    choices = raid_search.reward_choices(scope)
    assert all(q in choices[i] for r in every for i, q in totals(r.rewards).items())


def searched_both_ways(monkeypatch, *args, **kwargs):
    """-> (the helper's scan's search, the plain Python one) as (seed, context, stars, score, rewards, PID)."""
    if not raid_scan.available():
        pytest.skip("needs the PKHeX helper")
    out = []
    for fast in (True, False):
        monkeypatch.setattr(raid_search, "FAST", fast)
        out.append([(f.seed, f.context, f.stars, f.score, f.rewards, f.boss["pid"])
                    for f in raid_search.search(*args, **kwargs)])
    return out


@pytest.mark.parametrize("filters", [
    {}, {"objective": "hardest"}, {"shiny": False, "objective": "offense"}, {"nature": 3, "gender": 0},
    {"ivs": ((20, 31), (0, 15), (0, 31), (0, 31), (10, 31), (0, 31))}, {"tera_type": 4, "stars": 5},
    {"rewards": {50: 2, 645: 1}}, {"one_per_species": True, "limit": 100},
    {"one_per_species": True, "ability": 22, "objective": "special"}])
@pytest.mark.parametrize("scope, start", [
    (raid_search.contexts("violet", "paldea", "any", "standard"), 0x12345678),
    (raid_search.contexts("any", "kitakami", "any", "black"), 0xFFFFFF00),     # past FFFFFFFF to 0
    (raid_search.contexts("scarlet", "blueberry", "5star", "standard"), 7)])
def test_the_helper_s_scan_finds_what_python_finds(monkeypatch, scope, start, filters):
    """pokeldn.sv.raid_scan only picks the seeds the search keeps; the raids, their order and the
    ties between seeds and contexts are the Python search's."""
    filters = {"objective": "overall", "limit": 12, **filters}
    compiled, python = searched_both_ways(monkeypatch, start, 3600 // len(scope), scope,
                                          filters.pop("objective"), **filters)
    assert compiled == python
    assert compiled or {"ability", "nature", "stars"} & set(filters)     # a black crystal has no 5 stars


@pytest.mark.parametrize("chunk", [1 << 24, 1000])
@pytest.mark.parametrize("filters", [
    {}, {"shiny": True}, {"rewards": {645: 1}, "objective": "hardest"}, {"nature": 3}])
def test_the_search_can_stop_at_its_first_match(monkeypatch, chunk, filters):
    """The earliest seed that matches in the first context with a match, whatever its score; the
    helper's scan, chunked or not, is Python's."""
    monkeypatch.setattr(raid_scan, "CHUNK", chunk)
    scope = raid_search.contexts("any", "paldea", "6star", "standard")
    compiled, python = searched_both_ways(monkeypatch, 0xFFFFF000, 6000, scope, stop_at_first=True, **filters)
    assert compiled == python and len(python) == 1
    context, offset = python[0][1], (python[0][0] - 0xFFFFF000) % (1 << 32)
    before = scope[:scope.index(context)]
    assert not before or not raid_search.search(0xFFFFF000, 6000, before, **filters)
    assert not offset or not raid_search.search(0xFFFFF000, offset, [context], **filters)


@pytest.mark.parametrize("filters", [
    {}, {"objective": "hardest"}, {"one_per_species": True}, {"one_per_species": True, "objective": "hardest"},
    {"ivs": ((0, 31), (0, 31), (0, 5), (0, 31), (0, 31), (0, 31)), "objective": "physical"}])
def test_the_helper_s_requests_turn_away_seeds_that_cannot_beat_those_kept(monkeypatch, filters):
    """A request after the first passes the ranks kept so far (each species' with one per species),
    and the helper skips a seed that cannot beat them before its boss: the search is still Python's."""
    monkeypatch.setattr(raid_scan, "CHUNK", 500)
    monkeypatch.setattr(raid_scan, "MAX_CHUNK", 500)
    filters = {"objective": "overall", **filters}
    scope = raid_search.contexts("scarlet", "paldea", "6star", "any")
    compiled, python = searched_both_ways(monkeypatch, 0xFFFFF800, 4000, scope, filters.pop("objective"), **filters)
    assert compiled == python and compiled


@pytest.mark.parametrize("size_mark, seeds", [
    ("either", {0x10002082, 0x10006545, 0x1000749D, 0x1000908D}), ("mini", {0x10002082, 0x10006545}),
    ("jumbo", {0x1000749D, 0x1000908D})])
def test_the_helper_s_scan_draws_the_scale_as_python_does(monkeypatch, size_mark, seeds):
    """A boss's scale is drawn after its height and weight, two draws each: these seeds hold two of
    scale 0, for the Mini mark, and two of 255, for the Jumbo mark."""
    scope = raid_search.contexts("scarlet", "paldea", "5star", "standard")
    compiled, python = searched_both_ways(monkeypatch, 0x10002000, 0x7400, scope, size_mark=size_mark, limit=10)
    assert compiled == python and {seed for seed, *_ in compiled} == seeds
    with pytest.raises(ValueError, match="no size mark"):
        raid_search.search(0, 10, scope, size_mark="huge")


HERBA, SWEET, PATCH, CAP = 1907, 1904, 1606, 795      # Bitter and Sweet Herba Mystica, Ability Patch, Bottle Cap


def test_most_desired_rewards_ranks_the_first_wanted_first():
    """A herba over its least and no patch over beat no herba over and three patches: each total is a
    digit, its place among the item's totals from the least, the first wanted the most significant."""
    black = raid_search.contexts("scarlet", "paldea", "6star", "black")
    ranked = raid_search.ranked_rewards(black, {HERBA: 2, PATCH: 2})
    assert ranked == [(HERBA, tuple(range(2, 12))), (PATCH, tuple(range(2, 12)))]
    score = lambda herba, patches: raid_search.reward_score([(HERBA, herba), (PATCH, patches), (CAP, 3)], ranked)
    assert score(3, 2) > score(2, 5) > score(2, 2) == 0
    assert raid_search.reward_score([(HERBA, 1), (HERBA, 2), (PATCH, 2)], ranked) == score(3, 2)


def test_most_desired_rewards_ranks_by_as_many_as_one_score_holds():
    """A black crystal's raids give 1 to 11 of a herba, a patch or caps, and of a material 8 to 30 by
    twos: 11^4 * 12^4 fits under the score's limit and a fifth material does not, so Mankey Fur and
    the items after it only want their least; without wanted rewards there is nothing to rank by."""
    black = raid_search.contexts("scarlet", "paldea", "6star", "black")
    wanted = dict.fromkeys([HERBA, SWEET, PATCH, CAP, 2159, 2158, 2157, 2156, 1960, 1129], 1)
    ranked = raid_search.ranked_rewards(black, wanted)
    materials = tuple(range(8, 31, 2))
    assert ranked == [(HERBA, tuple(range(1, 12))), (SWEET, tuple(range(1, 12))), (PATCH, tuple(range(1, 12))),
                      (CAP, tuple(range(1, 12))), (2159, materials), (2158, materials), (2157, materials),
                      (2156, materials)]
    assert 11 ** 4 * 12 ** 4 <= raid_search.SCORE_LIMIT < 11 ** 4 * 12 ** 5
    totals = lambda fur: [(HERBA, 2), (SWEET, 1), (PATCH, 1), (CAP, 1), (2159, fur), (2158, 9)]
    score = lambda fur: raid_search.reward_score(totals(fur), ranked)
    assert score(10) > score(9) == score(8) > 0         # 9 is no total: 8's place, and 9 of 2158 too
    with pytest.raises(ValueError, match="want at least one"):
        raid_search.search(0, 10, black, "rewards")


@pytest.mark.parametrize("scope, rewards, filters", [
    (raid_search.contexts("scarlet", "paldea", "6star", "black"), {HERBA: 1, PATCH: 1}, {}),
    (raid_search.contexts("scarlet", "paldea", "6star", "black"), {HERBA: 1, PATCH: 1}, {"one_per_species": True}),
    (raid_search.contexts("any", "paldea", "6star", "black"), {CAP: 2, HERBA: 1}, {"shiny": False}),
    (raid_search.contexts("violet", "kitakami", "6star", "any"), {1128: 1}, {"tera_type": 3}),
    (raid_search.contexts("scarlet", "paldea", "5star", "standard"), {CAP: 1, 1862: 1}, {"one_per_species": True})])
def test_the_helper_s_scan_ranks_by_rewards_as_python_does(monkeypatch, scope, rewards, filters):
    """The rewards drawn once for every item, the scan turning away a seed that cannot beat the bar
    before its boss, and a row that cannot give the least wanted: the search is still Python's."""
    monkeypatch.setattr(raid_scan, "CHUNK", 2000)
    monkeypatch.setattr(raid_scan, "MAX_CHUNK", 2000)
    compiled, python = searched_both_ways(monkeypatch, 0xFFFFF000, 12000 // len(scope), scope, "rewards",
                                          rewards=rewards, **filters)
    assert compiled == python and compiled
    scores = [score for _, _, _, score, _, _ in compiled]
    assert scores == sorted(scores, reverse=True) or filters.get("one_per_species")


def test_the_helper_s_scan_draws_any_tera_type_under_rule_0(monkeypatch):
    """Breloom's five-star raid, Tera rule 0: any of 18, as raid_encounter.tera_type, so a Water
    Breloom (neither Grass nor Fighting) and its Water shards are found by both scans."""
    scope = raid_search.contexts("scarlet", "paldea", "6star", "standard")
    breloom = next(r for r, _ in raid_search._rows(scope[0]) if r["species"] == 286)
    assert breloom["tera"] == 0 and raid_search._gems(breloom) == set(range(18))
    compiled, python = searched_both_ways(monkeypatch, 0, 40_000, scope, "hardest", species_id=286, tera_type=10,
                                          rewards={raid_encounter.TERA_SHARDS[10]: 1})
    assert compiled == python and compiled


def test_a_stopped_helper_search_keeps_what_it_found(monkeypatch):
    if not raid_scan.available():
        pytest.skip("needs the PKHeX helper")
    monkeypatch.setattr(raid_scan, "CHUNK", 1000)
    monkeypatch.setattr(raid_scan, "MAX_CHUNK", 1000)
    seen = []
    found = raid_search.search(0, 10_000, raid_search.contexts("violet", "paldea", "6star", "standard"),
                               progress=lambda done, total: seen.append(done), cancelled=lambda: len(seen) >= 3)
    assert seen[:3] == [1000, 2000, 3000] and len(found) == 12 and max(f.seed for f in found) < 3000


def test_with_the_helper_a_search_covers_every_seed_of_every_context(monkeypatch):
    """No cap over the contexts: the finder's hundred million seeds, or every seed, in each of the 42."""
    monkeypatch.setattr(raid_search, "FAST", True)
    assert raid_search.most_seeds(1) == raid_search.most_seeds(42) == 1 << 32
    with pytest.raises(ValueError, match="1 to 4,294,967,296 seeds in each context"):
        raid_search.search(0, (1 << 32) + 1, raid_search.contexts("violet", "paldea", "6star", "standard"))


def test_without_the_helper_the_search_scans_in_python():
    import subprocess
    code = "; ".join((
        "from pokeldn import pokemon", "pokemon._command = lambda: (_ for _ in ()).throw(pokemon.BuilderError())",
        "from pokeldn.sv import raid_search",
        "assert not raid_search.FAST",
        "assert raid_search.DEFAULT_COUNT == 100_000",
        "assert raid_search.most_seeds(1) == 1_000_000 and raid_search.most_seeds(42) == 23_809",
        "import pytest",
        "pytest.raises(ValueError, raid_search.search, 0, 250_001, raid_search.contexts('violet', 'paldea'))",
        "found = raid_search.search(0, 2000, raid_search.contexts('violet', 'paldea', '6star', 'standard'))",
        "assert len(found) == 12"))
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, timeout=120)


# The scripted console. Addresses and ids as tests/test_sv_departure.py's.
HOST_IP, JOIN_IP, BROADCAST = "169.254.10.1", "169.254.10.2", "169.254.10.255"
HOST_MAC, JOIN_MAC = bytes.fromhex("02aabbccdd01"), bytes.fromhex("02aabbccdd02")
SSID = bytes.fromhex("7b744617795970bb6882b24ded4cae15")
CONSOLE_CID, CONSOLE_VAR = bytes.fromhex("eb9b2220f1480000"), 0x23AE


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    monotonic = time

    def sleep(self, seconds):
        self.now += seconds


def reliable(protocol, seq, payload, flags):
    if protocol == 0x7C:
        return reliable5.build_header(flags, seq, len(payload), lowest_pending=seq) + payload
    return reliable5.build_header(flags, seq, len(payload), lowest_pending=1, destination_bits=3,
                                  bitmap=[1]) + payload


def party(species):
    return gen9.encrypt(gen9.build(species=species, level=50, moves=(33, 0, 0, 0), ot_name="Player"))


class RaidGuestConsole:
    """A retail guest as captured against a raid host: it acknowledges the station list, joins port 2
    after the host's type 6, shows its Pokemon after the type 9s and its Ready 1.9 to 3.6 s later
    when its player presses it, answers the start with 0x0d, loads
    the bootstrap, and marks the battle; handed the network as a retail joiner was (docs/sv.md,
    Leaving), it answers the type 7 with a type 8 and the is-migrating status, then leaves at the
    first NetStartHostMigration."""

    def __init__(self, clock, ready_after=2.4, n=1, species=658, join_at=0.2):
        self.clock, self.keys = clock, sv.session_keys(SSID)
        self.ready_after = ready_after          # its player's Ready after its Pokemon, or never
        self.ip = JOIN_IP if n == 1 else f"169.254.10.{n + 1}"
        self.mac = JOIN_MAC if n == 1 else JOIN_MAC[:5] + bytes([n + 1])
        self.cid = CONSOLE_CID if n == 1 else CONSOLE_CID[:7] + bytes([n])
        self.var = CONSOLE_VAR + n - 1
        self.later, self.queue, self.seen, self.seqs = [], [], [], {}
        self.done = set()
        self.packet_ids = {}                # destination 1 or not -> the last packet id taken
        self.left = False
        self.stay = 0.0                         # seconds on the network after NetStartHostMigration
        self.leave_at = None
        self.pokemon = party(species)
        self.later_join = clock.now + join_at - 0.2      # on the network before its join
        self.at(join_at, pia6.build_session_join(self.cid, self.var, self.ip,
                                                 pia_connect.ldn_constant_id(HOST_MAC), 1, "Player",
                                                 bytes(4)), 0x98)

    def at(self, delay, body, protocol, port=0, flags=0):
        self.later.append((self.clock.now + delay, body, protocol, port, flags))

    def send_data(self, delay, protocol, port, payload, compressed=False):
        seq = self.seqs.get((protocol, port), 1)
        self.seqs[(protocol, port)] = seq + 1
        flags = (raid.COMPLETE_ZLIB if compressed else raid.COMPLETE) \
            | (reliable5.FLAG_IS_INITIALIZED if seq == 1 else 0)
        body = streams.compress(payload) if compressed else payload
        self.at(delay, reliable(protocol, seq, body, flags), protocol, port)

    def once(self, name):
        if name in self.done:
            return False
        self.done.add(name)
        return True

    def received(self, packet, dst):
        header, plain, ids = pia6.parse_packet(self.keys.session_key, HOST_IP, self.keys.network_id,
                                               packet)
        if dst not in (self.ip, BROADCAST) or (ids and self.var not in ids):
            return                              # another console's
        if header.packet_id and self.done & {"seated"}:
            # Per sender, one id sequence for destination 1 and one for the rest; a non-zero id
            # must be newer than the last, or the packet is dropped (`0x6e9854`, `0x6f3ff4`).
            key = header.dst_var == 1
            last = self.packet_ids.get(key)
            if last is not None and ((header.packet_id - last) & 0xFFFF) - (
                    0x10000 if (header.packet_id - last) & 0x8000 else 0) < 1:
                return
            self.packet_ids[key] = header.packet_id
        for msg in pia6.parse_messages(plain):
            p, row = bytes(msg.payload), dict(t=self.clock.now, dst=dst, protocol=msg.protocol,
                                              port=msg.port, flags=msg.message_flags)
            if msg.protocol in (0x7C, 0x80, 0x81) and len(p) >= reliable5.HEADER_SIZE:
                rm = reliable5.parse(p)
                row.update(seq=rm["sequence_id"], rflags=rm["flags"], lowest=rm["lowest_pending"],
                           bitmap=rm["bitmap"])
                if rm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                    body = rm["payload"]
                    if rm["flags"] & reliable5.FLAG_ZLIB:
                        body = zlib.decompressobj().decompress(body)
                    row["data"] = body
                    self.answer_data(msg.protocol, msg.port, rm, body)
            else:
                row["data"] = p
                self.answer(msg.protocol, p)
            self.seen.append(row)

    def answer(self, protocol, p):
        if protocol == 0x2C and p[1] == 0x11:
            self.at(0.01, pia_connect.build_net_response(int.from_bytes(p[4:8], "big")), 0x2C, 0, 0x11)
        if protocol == 0x2C and p[1] == 0x50:
            self.at(0.02, bytes([1, 0x51, 0, 0]) + p[4:8], 0x2C, 0, 0x11)
        if protocol == 0x98 and p[0] == 2:
            self.done.add("seated")             # a station now stands at the host's address
        if protocol == 0x98 and p[0] == 5:
            update = pia_connect.parse_session_update_v11(p, route_bytes=0)
            self.at(0.03, pia_connect.build_session_update_ack_v11(self.cid, update["sequence_id"]), 0x98)
        if protocol == 0x58 and p[0] == 0:
            self.at(0.01, streams.build_rtt_response(p, 1), 0x58)
        migration = pia_connect.parse_session_migration_v11(p) if protocol == 0x98 else None
        if migration and migration["target_var"] == self.var:
            self.at(0.0, pia_connect.build_session_migration_ack_v11(
                self.cid, self.var, migration["host_constant_id"], migration["host_var"]), 0x98)
        if protocol == 0x2C and p[:2] == bytes([1, 0x40]) and self.leave_at is None:
            self.leave_at = self.clock.now + self.stay

    def answer_data(self, protocol, port, rm, body):
        if protocol == 0x7C:
            self.at(0.01, game_channel.build_ack(rm["sequence_id"] + 1, lowest_pending=1), 0x7C, port)
        else:
            self.at(0.01, streams.build_ack({0: rm["sequence_id"]}, 1, 1), protocol, port, 0xA0)
        if (protocol, port) == (0x7C, 2) and body[:1] == b"\x06" and self.once("join"):
            self.send_data(0.3, 0x7C, 2, port2.build_join(0))
        if (protocol, port) == (0x80, 2) and body[:1] == b"\x09" and self.once("lobby"):
            self.lobby_at = self.clock.now
            self.send_data(0.5, 0x80, 0, raid.state(1, raid.STATE_IDLE), compressed=True)
            self.send_data(0.52, 0x80, 0, raid.pokemon(2, self.pokemon))
            if self.ready_after is not None:
                self.send_data(0.52 + self.ready_after, 0x80, 0, raid.state(3, raid.STATE_READY),
                               compressed=True)
        if ((protocol, port) == (0x80, 2) and body[:1] == b"\x09" and "lobby" in self.done
                and body[-8:] != port2.station_id(self.cid).to_bytes(8, "little") and body[4:5] != b"\x00"):
            # A member joined: the Lua lobby answers it with our Pokemon and our state (0.15829).
            self.send_data(0.1, 0x80, 0, raid.pokemon(5, self.pokemon))
        if (protocol, port) != (0x80, 0):
            return
        if raid.state_of(body) == raid.STATE_START and self.once("start"):
            self.send_data(0.4, 0x80, 0, raid.state(4, raid.STATE_STARTED), compressed=True)
        if rm["flags"] == raid.FRAGMENT_END_ZLIB and self.once("load"):
            self.send_data(1.0, 0x80, 0, raid.message(raid.KEY_LOAD, 0x6E, 0, 5, bytes(4)))
            self.send_data(3.0, 0x80, 0, raid.message(raid.KEY_LOAD, 0x73, 0, 6, bytes(4)))
        if body[:4] == raid.BATTLE and self.once("battle"):
            self.send_data(2.0, 0x80, 0, raid.message(raid.KEY_BATTLE, 0x93, 1, 7, bytes(4)))

    def tick(self):
        if self.leave_at is not None and self.clock.now >= self.leave_at:
            self.left = True
        for item in [x for x in self.later if x[0] <= self.clock.now]:
            self.later.remove(item)
            _, body, protocol, port, flags = item
            # A retail guest's footer names the host's variable id (0xc6).
            self.queue.append(sv_join.build_out(self.keys, self.ip, body, sv_host.PIA_HOST_VAR,
                                                protocol=protocol, port=port, flags=flags,
                                                src_var=self.var))


def run_raid_host(monkeypatch, tmp_path, rewards=(), extra=(), ready_after=2.4, seconds=60,
                  consoles=None, bag=None):
    """-> the scripted console (or the list given in `consoles`, made with the clock) and the clock,
    after the host has run against them."""
    clock = Clock()
    made = [RaidGuestConsole(clock, ready_after)] if consoles is None else consoles(clock)
    console = made[0]

    class Transport:
        ssid, our_ip, our_mac, broadcast = SSID, HOST_IP, HOST_MAC, BROADCAST
        join_events = 1

        @property
        def participants(self):
            return [(c.mac, c.ip) for c in made if not c.left and clock.now >= c.later_join]

        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def set_application_data(self, _):
            pass

        def send(self, packet, dst):
            for c in made:
                if not c.left:
                    c.received(packet, dst)

        def wait_readable(self, _):
            clock.now += 0.01
            for c in made:
                c.tick()

        def recv(self):
            out = []
            for c in made:
                queued, c.queue = c.queue, []
                out += [(packet, c.ip) for packet in queued]
            return out

    ours = tmp_path / "ours.pk9"
    ours.write_bytes(party(25))
    monkeypatch.setattr(sv_host, "time", clock)
    monkeypatch.setattr(sv_host, "HostTransport", Transport)
    monkeypatch.setattr(sv_host, "find_ap_phy", lambda log=None: "esp32")
    monkeypatch.setattr(sv_host, "needs_root", lambda: False)
    monkeypatch.setattr(sv_host.pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(sv_host.pokemon_service.SERVICE, "names",
                        lambda game, kind: bag if bag is not None else [{"id": 15, "name": "Quick Ball"}])
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    args = build(tool, {"--raid-pokemon": {"file": str(ours)}, "--raid-seed": "000F34C3",
                        "--raid-reward": [{"item_id": str(i), "quantity": str(q)} for i, q in rewards]},
                 {}, Settings())
    assert sv_host.main(args + ["--keys", str(tmp_path / "prod.keys"), "--seconds", str(seconds),
                                *extra]) == 0
    return (console if consoles is None else made), clock


# What the host's twenty raid messages start with, their reliable flags and lowest pending, as the
# host a retail console fought its raids against sent them.
RAID_MESSAGES = [
    ("80332c01", 31, 1), ("80332d01", 7, 1), ("80332e01", 7, 1), ("80333001", 7, 4),
    ("80333001", 7, 5), ("80333001", 7, 6), ("80332d01", 23, 7), ("80333001", 7, 8),
    ("80333001", 7, 9), ("80332d01", 23, 10), ("80332f01", 3, 11), (None, 21, 11),
    ("32017300", 7, 13), ("80349301", 7, 14), ("7b001327", 23, 15), ("7b001327", 23, 15),
    ("7b001327", 23, 15), ("7b001327", 23, 17), ("7b001327", 23, 18), ("7b001327", 23, 20)]


def test_a_console_fights_the_raid_we_host(monkeypatch, tmp_path):
    console, clock = run_raid_host(monkeypatch, tmp_path, rewards=[(15, 500)])
    first = {}
    for row in console.seen:
        if (row["protocol"], row["port"]) == (0x80, 0) and "data" in row:
            first.setdefault(row["seq"], row)
    assert sorted(first) == list(range(1, 21))
    assert [((first[s]["data"][:4].hex() if s != 12 else None), first[s]["rflags"], first[s]["lowest"])
            for s in range(1, 21)] == RAID_MESSAGES
    assert all(r["dst"] == BROADCAST for r in first.values())
    sent = lambda s: first[s]["t"]
    whole = first[11]["data"] + first[12]["data"]
    plain = raid.payload_of(whole)
    assert plain[:gen9.SIZE_PARTY] == party(25)
    assert plain[gen9.SIZE_PARTY:2 * gen9.SIZE_PARTY] == console.pokemon
    assert plain[2 * gen9.SIZE_PARTY:4 * gen9.SIZE_PARTY] == raid.empty_participant() * 2
    point = plain[raid.RAIDPOINT:]
    assert struct.unpack_from("<8I", point, 0xE0) == (0, 15, 500, 0, 0, 0, 0, 0)
    net = [r for r in console.seen if r["protocol"] == 0x2C and r["data"][1:2] == b"\x50"]
    session = [r for r in console.seen if r["protocol"] == 0x98 and r["data"][0] == 5
               and pia_connect.parse_session_update_v11(r["data"], route_bytes=0)["sequence_id"] == 1]
    assert net and net[0]["flags"] == 0x31 and net[0]["data"][27] == 7
    assert sent(10) < net[0]["t"] < session[0]["t"] < sent(11) <= sent(12) < sent(13) < sent(14) < sent(15)
    assert [sent(s) - sent(15) for s in range(15, 21)] == pytest.approx(raid.HANDOFF_AT, abs=0.011)
    handed = [r for r in console.seen if r["protocol"] == 0x98 and r["data"][0] == 7]
    status = [r for r in console.seen if r["protocol"] == 0x2C and r["data"][1] == 0x11
              and r["data"][26] == 2 and r["data"][29] == 1]
    start = [r for r in console.seen if r["protocol"] == 0x2C and r["data"] == bytes.fromhex("01400000")]
    assert handed[0]["t"] - sent(20) == pytest.approx(raid.LINGER, abs=0.05)
    assert len(handed) == 1 and handed[0]["t"] < status[0]["t"] < start[0]["t"]
    assert start[0]["flags"] == 0x11 and clock.now - start[0]["t"] < 0.1


def lobby_rows(console):
    """-> the host's messages on 0x80 port 0 to `console`, first copy of each sequence, in order."""
    first = {}
    for row in console.seen:
        if (row["protocol"], row["port"]) == (0x80, 0) and "data" in row:
            first.setdefault(row["seq"], row)
    return [first[seq] for seq in sorted(first)]


def start_of(console):
    return next(r for r in lobby_rows(console) if raid.state_of(r["data"]) == raid.STATE_START)


def test_three_consoles_fight_one_raid(monkeypatch, tmp_path):
    """`--raid-players 3`: each console takes the next seat, every station list names the four
    stations, the start waits for the last console's Ready, the one bootstrap carries every
    Pokemon in its seat, and the network goes to seat 1 while seats 2 and 3 draw the is-migrating
    status and NetStartHostMigration; seats 2 and 3 stay on the network a while after seat 1 has
    left, as a retail Violet did. A fourth console's join goes unanswered."""
    def consoles(clock):
        made = [RaidGuestConsole(clock, 2.4, n, species, join_at) for n, species, join_at in
                ((1, 658, 0.2), (2, 6, 8.0), (3, 150, 15.0), (4, 1, 17.0))]
        made[1].stay = made[2].stay = 1.5
        return made
    made, clock = run_raid_host(monkeypatch, tmp_path, extra=["--raid-players", "3"], seconds=120,
                                consoles=consoles)
    consoles, fourth = made[:3], made[3]
    assert not [r for r in fourth.seen if r["protocol"] == 0x98]
    readies = []
    for n, console in enumerate(consoles, 1):
        response = next(pia_connect.parse_session_join_response_v11(r["data"]) for r in console.seen
                        if r["protocol"] == 0x98 and r["data"][0] == 2)
        assert response["station_index"] == n
        lists = [pia_connect.parse_session_update_v11(r["data"], route_bytes=0) for r in console.seen
                 if r["protocol"] == 0x98 and r["data"][0] == 5]
        assert [st["station_index"] for st in lists[-1]["stations"]] == [0, 1, 2, 3]
        # A seated console takes every later list, not only the battle's.
        taken = sorted({upd["sequence_id"] for upd in lists})
        assert taken == list(range(taken[0], taken[-1] + 1))
        tables = [r["data"] for r in console.seen if r["protocol"] == 0x2C and r["data"][1] == 0x11
                  and r["data"][29] == 0]
        # Each new seat reaches the seated consoles' Net tables too, under a new sequence.
        assert [tables[-1][30 + 21 * k + 1] for k in range(4)] == [0, 1, 2, 3]
        assert int.from_bytes(tables[-1][4:8], "big") > int.from_bytes(tables[0][4:8], "big") or n == 3
        accepts = [r["data"] for r in console.seen if (r["protocol"], r["port"]) == (0x80, 2)
                   and r.get("data", b"")[:1] == b"\x09"]
        # Every member's code, ours 0, whatever the order the consoles joined in.
        assert set(accepts) == {port2.build_accept(port2.station_id(cid), code=k) for k, cid in
                                enumerate([pia_connect.ldn_constant_id(HOST_MAC)]
                                          + [c.cid for c in consoles])}
        sessions = [r["data"] for r in console.seen if (r["protocol"], r["port"]) == (0x7C, 2)
                    and r.get("data", b"")[:1] == b"\x06"]
        assert sessions[0] == port2.build_session(
            port2.station_id(pia_connect.ldn_constant_id(HOST_MAC)),
            members=[(port2.station_id(c.cid), k) for k, c in enumerate(consoles[:n - 1], 1)])
        rows = lobby_rows(console)
        assert all(r["bitmap"] == [1 << n] for r in rows)
        timers = [struct.unpack_from("<I", r["data"], 34)[0] for r in rows
                  if r["data"][:4] == raid.trade.build(raid.KEY_LOBBY, raid.KIND_COUNTDOWN, 1)]
        assert timers == sorted(set(timers), reverse=True) and timers[0] <= raid.LOBBY_SECONDS
        readies.append(console.lobby_at + 0.52 + 2.4)
        plain = raid.payload_of(next(r["data"] for r in rows if r["data"][:4] == raid.trade.build(
            raid.KEY_LOBBY, raid.KIND_BOOTSTRAP, 1)) + next(r["data"] for r in rows if "data" in r
                                                             and r["rflags"] == raid.FRAGMENT_END_ZLIB))
        assert [plain[k * gen9.SIZE_PARTY:(k + 1) * gen9.SIZE_PARTY] for k in range(4)] == [
            party(25)] + [c.pokemon for c in consoles]
        assert console.left
    assert all(start_of(c)["t"] > max(readies) for c in consoles)
    handed = [[r for r in c.seen if r["protocol"] == 0x98 and r["data"][0] == 7] for c in consoles]
    assert handed[0] and not handed[1] and not handed[2]
    for console in consoles:
        status = [r["data"] for r in console.seen if r["protocol"] == 0x2C and r["data"][1] == 0x11
                  and r["data"][29] == 1]
        # Every console ranks every seat: one ranking only itself after us opened its own network.
        assert status and [status[-1][30 + 21 * k + 1] for k in range(4)] == [0, 1, 2, 3]
        assert all(status[-1][30 + 21 * k + 3:30 + 21 * k + 7] != bytes(4) for k in range(4))
        nets = [r["data"][29] for r in console.seen if r["protocol"] == 0x2C and r["data"][1] == 0x11]
        # No plain table after the is-migrating one: it takes the console back as our station.
        assert 0 not in nets[nets.index(1):]
    for console in consoles[1:]:
        assert any(r["data"] == bytes.fromhex("01400000") for r in console.seen
                              if r["protocol"] == 0x2C)


@pytest.mark.parametrize("ready_after, players", [(None, 1), (2.4, 2)])
def test_the_raid_starts_when_the_lobby_timer_runs_out(monkeypatch, tmp_path, ready_after, players):
    """A console that never readies, or fewer consoles than `--raid-players`: the lobby timer counts
    down a step a second and the raid starts when it reaches zero, then runs to its battle."""
    console, clock = run_raid_host(monkeypatch, tmp_path, extra=["--raid-players", str(players)],
                                   ready_after=ready_after, seconds=240)
    rows = lobby_rows(console)
    timers = [struct.unpack_from("<I", r["data"], 34)[0] for r in rows
              if r["data"][:4] == raid.trade.build(raid.KEY_LOBBY, raid.KIND_COUNTDOWN, 1)]
    assert timers == list(range(raid.LOBBY_SECONDS, -1, -1))
    assert start_of(console)["t"] - rows[0]["t"] == pytest.approx(raid.LOBBY_SECONDS, abs=1.1)
    assert rows[-1]["data"] == raid.HANDOFF[-1] and console.left


def test_the_partners_we_choose_reach_the_bootstrap(monkeypatch, tmp_path, capsys):
    """`--raid-partner`, in slot order, and `--raid-partner-progress`: the RaidPoint's partner seed
    draws them from that stage's pool. A trainer the stage's pool lacks is refused before the radio."""
    console, _ = run_raid_host(monkeypatch, tmp_path, extra=[
        "--raid-partner", "luke", "--raid-partner", "Ava", "--raid-partner-progress", "6star"])
    first = {}
    for row in console.seen:
        if (row["protocol"], row["port"]) == (0x80, 0) and "data" in row:
            first.setdefault(row["seq"], row)
    point = raid.payload_of(first[11]["data"] + first[12]["data"])[raid.RAIDPOINT:]
    seed, stage = struct.unpack_from("<QI", point, raid.POINT_PARTNERS)
    assert stage == 4 and raid_partners.draw(seed, stage) == [17, 1]
    assert (f"[sv] raid partners from the 6star pool, level 40, partner seed {seed:016X}: Luke (Clodsire), "
            f"Ava (Toxapex) (2 of 2 chosen)") in capsys.readouterr().out
    with pytest.raises(SystemExit):
        run_raid_host(monkeypatch, tmp_path,
                      extra=["--raid-partner", "Dylan", "--raid-partner-progress", "3star"])


def test_the_raid_host_puts_its_lobby_on_the_screen(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sv_host.screen, "lobby", lambda *args, **kw: calls.append(("lobby", args, kw)))
    monkeypatch.setattr(sv_host.screen, "joined", lambda count: calls.append(("joined", count)))
    run_raid_host(monkeypatch, tmp_path)
    found = raid_encounter.generate(0x000F34C3)
    assert calls == [("lobby", ("Tera Raid", found.species, found.boss["nickname"], 1),
                      {"stars": found.stars, "code": "4970", "form": found.boss["form"]}),
                     ("joined", 1)]


def test_two_consoles_leave_one_slot_to_the_partner_we_choose(monkeypatch, tmp_path, capsys):
    """`--raid-players 2`: the consoles take seats 1 and 2, and the RaidPoint's partner seed draws the
    one partner chosen for seat 3. A second partner, or any with three consoles, is refused before the
    radio."""
    assert [raid_partners.slots(n) for n in (1, 2, 3)] == [2, 1, 0]
    made, _ = run_raid_host(
        monkeypatch, tmp_path, extra=["--raid-players", "2", "--raid-partner", "Eli",
                                      "--raid-partner-progress", "6star"], seconds=120,
        consoles=lambda clock: [RaidGuestConsole(clock, 2.4, n, species, join_at)
                                for n, species, join_at in ((1, 658, 0.2), (2, 6, 8.0))])
    rows = lobby_rows(made[0])
    plain = raid.payload_of(next(r["data"] for r in rows if r["data"][:4] == raid.trade.build(
        raid.KEY_LOBBY, raid.KIND_BOOTSTRAP, 1)) + next(r["data"] for r in rows
                                                         if r["rflags"] == raid.FRAGMENT_END_ZLIB))
    assert [plain[k * gen9.SIZE_PARTY:(k + 1) * gen9.SIZE_PARTY] for k in range(4)] == [
        party(25), made[0].pokemon, made[1].pokemon, raid.empty_participant()]
    seed, stage = struct.unpack_from("<QI", plain[raid.RAIDPOINT:], raid.POINT_PARTNERS)
    assert stage == 4 and raid_partners.draw(seed, stage, 1) == [raid_partners.trainer("Eli")]
    assert (f"[sv] raid partners from the 6star pool, level 40, partner seed {seed:016X}: Eli (Gardevoir) "
            f"(1 of 1 chosen)") in capsys.readouterr().out
    for extra in (["--raid-players", "2", "--raid-partner", "Eli", "--raid-partner", "Ava"],
                  ["--raid-players", "3", "--raid-partner", "Eli"]):
        with pytest.raises(SystemExit):
            run_raid_host(monkeypatch, tmp_path, extra=extra)


@pytest.mark.parametrize("capture, extra, word, record, summary", [
    (1, [], 1, 2022120904, "caught as any raid boss"),
    (2, [], 2, 2022120904, "caught once per save"),
    (2, ["--raid-catch-normal"], 1, 2022120999,
     "caught once per save, served as a normal catch of record 2022120999"),
    (0, ["--raid-catch-normal"], 0, 2022120904, "cannot be caught")])
def test_a_console_fights_an_event_raid_we_host(monkeypatch, tmp_path, capsys, capture, extra, word, record,
                                                summary):
    """`--raid-event`: the seed draws from the delivery's encounters at the tool's progress, and
    the bootstrap carries that boss and a RaidPoint with the event crystal, the record's capture
    rate and its rewards. Under `--raid-catch-normal` a catch-once record is a normal catch, and the
    lobby shows a record number no save caught."""
    salamence = dict(species=373, form=0, ability=1, flawless_ivs=3, level=45, capture_level=45,
                     moves=[428, 337, 242, 814], tera=1, stars=4, rate=2, identifier=2022120904,
                     fixed_rewards="1", lottery_rewards="1", boss_desc=[1200] + [0] * 36, evs=[0] * 6,
                     rom=0, group=1, capture_rate=capture, ivs=None, gender=None, nature=None, shiny=0,
                     scale_type=0, scale=0, held_item=0, time=[1, 450, 0, 60, 0, 0, 0])
    event = raid_event.Event(20221209, "", (salamence,),
                             {"1": [dict(category=0, item=1126, amount=2, probability=100, subject=0)]},
                             {"1": []}, (5,) + (0,) * 9)
    monkeypatch.setattr(sv_host.raid_event, "load", lambda folder: event)
    console, _ = run_raid_host(monkeypatch, tmp_path, extra=["--raid-event", "delivery", *extra])
    tera = raid_encounter.tera_type(0x000F34C3, salamence)
    assert f"Tera type {tera}, {summary}\n" in capsys.readouterr().out
    first = {}
    for row in console.seen:
        if (row["protocol"], row["port"]) == (0x80, 0) and "data" in row:
            first.setdefault(row["seq"], row)
    assert sorted(first) == list(range(1, 21))
    plain = raid.payload_of(first[11]["data"] + first[12]["data"])
    boss = gen9.read(gen9.load(plain[4 * gen9.SIZE_PARTY:5 * gen9.SIZE_PARTY]))
    assert (boss["species"], boss["level"]) == (373, 45)
    point = plain[raid.RAIDPOINT:]
    assert struct.unpack_from("<4I", point, 0x20) == (4, 2, word, 45)
    assert struct.unpack_from("<7I", point, 0x30) == (1, 450, 0, 60, 0, 0, 0)
    assert struct.unpack_from("<4I", point, raid.POINT_REWARDS) == (1126, 2, 0, 0)
    descriptor = struct.unpack_from("<11I", first[1]["data"], 18)
    assert (descriptor[1], descriptor[4], descriptor[7]) == (373, 4, record)
    # The delivery's record stays.
    assert (salamence["capture_rate"], salamence["identifier"]) == (capture, 2022120904)


def test_a_normal_catch_needs_an_event_raid(monkeypatch, tmp_path):
    with pytest.raises(SystemExit):
        run_raid_host(monkeypatch, tmp_path, extra=["--raid-catch-normal"])


HOST_VAR = sv_host.PIA_HOST_VAR
HOST_CID = pia_connect.ldn_constant_id(HOST_MAC)


class RaidHostConsole:
    """A retail raid host as a captured guest saw it: the join response and station list together,
    the list again 2 s later until acknowledged, the six-key table and the type 6, the start 3 s
    after the guest's Pokemon, the battle 2 s after its answer."""

    def __init__(self, clock):
        self.clock, self.keys = clock, sv.session_keys(SSID)
        self.queue, self.later, self.got, self.seqs, self.done = [], [], [], {}, set()
        self.list_acked = False
        self.at(0.0, sv_host.build_net_probe(self.keys, HOST_IP, HOST_MAC, [HOST_IP, JOIN_IP], 3,
                                             os.urandom(8), 4, net_flags=0x31))

    def at(self, delay, packet):
        self.later.append((self.clock.now + delay, packet))

    def reply(self, body, protocol=0x98, port=0, flags=0, mesh=False):
        return sv_host.build_reply(self.keys, HOST_IP, body, sv_join.OUR_VAR, os.urandom(8),
                                   protocol=protocol, port=port, flags=flags, mesh=mesh)

    def data(self, delay, protocol, port, payload, compressed=False):
        seq = self.seqs.get((protocol, port), 1)
        self.seqs[(protocol, port)] = seq + 1
        flags = (raid.COMPLETE_ZLIB if compressed else raid.COMPLETE) \
            | (reliable5.FLAG_IS_INITIALIZED if seq == 1 else 0)
        body = streams.compress(payload) if compressed else payload
        self.at(delay, self.reply(reliable(protocol, seq, body, flags), protocol, port))

    def station_list(self, sequence):
        stations = [dict(constant_id=HOST_CID, variable_id=HOST_VAR, ip=HOST_IP, port=12345,
                         station_index=0, route=None, join_order=0, token=bytes(32),
                         players=[dict(player_id=pia_connect.DEFAULT_PLAYER_ID, name="Player")]),
                    dict(constant_id=self.guest_cid, variable_id=sv_join.OUR_VAR, ip=JOIN_IP,
                         port=12345, station_index=1, route=None, join_order=1, token=bytes(32),
                         players=[dict(player_id=pia_connect.DEFAULT_PLAYER_ID, name="POKELDN")])]
        return self.reply(pia_connect.build_session_update_v11(HOST_CID, HOST_VAR, stations,
                                                               sequence_id=sequence), mesh=True)

    def resend_list(self):
        if not self.list_acked:
            self.queue.append(self.station_list(0))
            self.later.append((self.clock.now + 2.0, None))

    def sendto(self, packet, _):
        _, plain, _ = pia6.parse_packet(self.keys.session_key, JOIN_IP, self.keys.network_id, packet)
        for msg in pia6.parse_messages(plain):
            p = bytes(msg.payload)
            row = dict(t=self.clock.now, protocol=msg.protocol, port=msg.port, flags=msg.message_flags,
                       payload=p)
            self.got.append(row)
            if msg.protocol == 0x98 and p[0] == 0 and "join" not in self.done:
                self.done.add("join")
                self.guest_cid = pia_connect.parse_session_join_v11(p)["source_constant_id"]
                self.queue.append(self.reply(pia_connect.build_session_join_response_v11(
                    HOST_CID, HOST_VAR, self.guest_cid, sv_join.OUR_VAR, version=0, sequence_id=0,
                    route=None, random4=bytes(4))))
                self.queue.append(self.station_list(0))
                self.later.append((self.clock.now + 2.0, None))
            elif msg.protocol == 0x98 and p[0] == 3:
                self.queue.append(self.reply(pia_connect.build_session_leave_response_v11(
                    p, random4=bytes(4))))
            elif msg.protocol == 0x98 and p[0] == 6 and not self.list_acked:
                self.list_acked = True
                self.data(0.1, 0x7C, 1, raid.channel_table(), compressed=True)
                self.data(0.1, 0x7C, 2, port2.build_session(port2.station_id(HOST_CID)), compressed=True)
            elif msg.protocol in (0x7C, 0x80, 0x81) and len(p) >= reliable5.HEADER_SIZE:
                rm = reliable5.parse(p)
                row.update(seq=rm["sequence_id"], rflags=rm["flags"])
                if rm["flags"] & reliable5.FLAG_APPLICATION_DATA:
                    body = rm["payload"]
                    if rm["flags"] & reliable5.FLAG_ZLIB:
                        body = zlib.decompressobj().decompress(body)
                    row["data"] = body
                    if msg.protocol == 0x80 and body[:4] == raid.CONSOLE_POKEMON and "start" not in self.done:
                        self.done.add("start")
                        self.data(3.0, 0x80, 0, raid.state(0x10E, raid.STATE_START), compressed=True)
                    if msg.protocol == 0x80 and raid.state_of(body) == raid.STATE_STARTED \
                            and "battle" not in self.done:
                        self.done.add("battle")
                        self.data(2.0, 0x80, 0, raid.BATTLE_READY)

    def recvfrom(self, _):
        if self.queue:
            return self.queue.pop(0), (HOST_IP, sv.PIA_PORT)
        raise BlockingIOError

    def close(self):
        pass

    def tick(self):
        self.clock.now += 0.01
        for item in [x for x in self.later if x[0] <= self.clock.now]:
            self.later.remove(item)
            if item[1] is None:
                self.resend_list()
            else:
                self.queue.append(item[1])


def test_our_guest_joins_a_console_s_raid_and_leaves_its_pokemon_in_the_battle(monkeypatch, tmp_path):
    clock = Clock()
    host = RaidHostConsole(clock)

    async def wait_readable(_):
        host.tick()
        await trio.lowlevel.checkpoint()

    ours = tmp_path / "ours.pk9"
    ours.write_bytes(party(25))
    monkeypatch.setattr(sv_join, "time", clock)
    monkeypatch.setattr(sv_join, "make_socket", lambda *a: host)
    monkeypatch.setattr(trio.lowlevel, "wait_readable", wait_readable)
    monkeypatch.setattr(sv_join.pokemon_service, "prepare_file", lambda game, path, **kw: path)
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-join")
    ap = sv_join.build_parser()
    args = ap.parse_args(build(tool, {"--raid-pokemon": {"file": str(ours)}}, {}, Settings())
                         + ["--ip-join", "--rtt-period", "0"])
    sv_join.raid_guest(ap, args)
    seat = trio.run(sv_join.run_session, args, host.keys, HOST_IP, HOST_MAC, JOIN_IP, JOIN_MAC,
                    lambda **row: None)
    assert seat["raided"]
    got = host.got
    first = lambda pred: next(r for r in got if pred(r))
    acks = [r for r in got if r["protocol"] == 0x98 and r["payload"][0] == 6]
    # The station list that came with the join response is left; its retransmission is answered.
    assert acks[0]["t"] >= got[0]["t"] + 2.0
    clock_request = first(lambda r: r["protocol"] == 0x77)
    assert clock_request["payload"] == bytes(9) + b"\x01" + bytes(8)
    assert all(r["flags"] == 0x11 for r in got if r["protocol"] == 0x2C)
    tables = [r for r in got if (r["protocol"], r["port"]) == (0x7C, 1) and "data" in r]
    assert [len(channel_table.parse(r["data"])) for r in tables[:2]] == [4, 2]
    assert tables[1]["t"] - tables[0]["t"] == pytest.approx(sv_join.RAID_KEYS_DELAY, abs=0.02)
    port2_join = first(lambda r: (r["protocol"], r["port"]) == (0x7C, 2) and "data" in r)
    assert port2_join["data"] == port2.build_join(0)
    assert port2_join["t"] - tables[0]["t"] == pytest.approx(sv_join.RAID_PORT2_DELAY, abs=0.02)
    channel_acks = [r for r in got if r["protocol"] == 0x7C and "data" not in r]
    assert channel_acks and all(r["flags"] == streams.MESSAGE_FLAGS_ACK for r in channel_acks)
    sends = {r["seq"]: r for r in reversed(got) if (r["protocol"], r["port"]) == (0x80, 0) and "data" in r}
    lobby = [sends[seq] for seq in sorted(sends)]
    assert [raid.state_of(r["data"]) for r in lobby] == [raid.STATE_IDLE, None, raid.STATE_READY,
                                                         raid.STATE_STARTED]
    assert raid.pokemon_of(lobby[1]["data"]) == gen9.load(party(25))
    assert lobby[2]["t"] - lobby[0]["t"] == pytest.approx(2.0, abs=0.02)
    battle_ack = [r for r in got if (r["protocol"], r["port"]) == (0x80, 0) and "data" not in r]
    leave = [r for r in got if r["protocol"] == 0x98 and r["payload"][0] == 3]
    assert len(leave) == 1 and leave[0] is got[-1] and leave[0]["t"] - battle_ack[-1]["t"] < 0.06


class ServedBattleConsole(RaidGuestConsole):
    """The scripted console, then at battle slot 2 of a served battle (pokeldn.sv.raid_battle) whose
    bootstrap is `boot`: each odd server step answered 0.3 s later, a request with its Pokemon's first
    move on the boss and the boss's first move on it, on 0x80 port 0 as its battle-start frames."""

    def __init__(self, clock, boot):
        super().__init__(clock)
        self.battle = []                        # (x, message) received in the battle
        self.boot = boot

    def answer_data(self, protocol, port, rm, body):
        super().answer_data(protocol, port, rm, body)
        if (protocol, port) != (0x80, 0):
            return
        framed = raid_battle.unframe(body)
        if framed is None:
            return
        x, _, msg = framed
        self.battle.append((x, msg))
        if x != raid_battle.SERVER:
            return
        if msg[0] == raid_battle.REQUEST:
            moves = [raid_battle.first_move(self.boot[o:o + gen9.SIZE_PARTY]) if self.boot else 0
                     for o in (gen9.SIZE_PARTY, 4 * gen9.SIZE_PARTY)]
            reply = raid_battle.command(msg, 2, *moves)
        elif msg[0] & 1:
            reply = raid_battle.answer(msg, 2)
        else:
            return
        self.send_data(0.3, 0x80, 0, raid_battle.frame(3, 5, reply), compressed=True)


class ScriptedServer:
    """A battle server with the plugin interface (docs/plugins.md, A battle server): step 1 to every
    slot, a request (5) once every slot answered it, then the end sequence once the four player slots
    sent their commands. Moves the battle in each frame that queued something."""
    END = (0x25, 0x29, 0x49, 0x35, 0x37)

    def __init__(self, bootstrap, partners):
        assert len(bootstrap) >= 6 * gen9.SIZE_PARTY and len(partners) == 2
        self.t, self.queued, self.got = 0.0, {s: [] for s in range(5)}, {}

    def _send(self, kind):
        for slot in range(5):
            self.queued[slot].append(bytes([kind]) + bytes(0x17) + bytes([5, slot]) + bytes(6))

    def start(self, now):
        self.t = now
        self._send(0x01)
        return 1

    def receive(self, slot, message):
        self.got.setdefault(message[0], set()).add(slot)
        if (message[0], len(self.got[message[0]])) in ((0x02, 5), (0x06, 4)):    # the boss sends no command
            for kind in ((0x05,) if message[0] == 0x02 else self.END):
                self._send(kind)

    def run(self, until):
        self.t = max(self.t, until)
        return 0

    def sent(self, slot):
        out, self.queued[slot] = self.queued[slot], []
        return out


def test_a_console_fights_the_battle_we_serve(monkeypatch, tmp_path, capsys):
    """The launcher's served battle through the scripted console, with a plugin's battle server: the
    console's answers reach the server, the server's steps reach the console, and the run closes at
    the battle's end with no handover."""
    from pokeldn import plugins
    plugin = plugins.Plugin(id="scripted", name="scripted")
    plugins.API(plugin).add_battle_server("sv", "scripted", ScriptedServer)
    monkeypatch.setattr(plugins, "load", lambda: [plugin])
    try:
        made, _ = run_raid_host(monkeypatch, tmp_path, extra=["--raid-serve", "scripted"], seconds=900,
                                consoles=lambda clock: [ServedBattleConsole(clock, None)])
    finally:
        plugins._battle_servers.clear()
    console = made[0]
    kinds = [m[0] for x, m in console.battle if x == raid_battle.SERVER]
    assert kinds == [0x01, 0x05, *ScriptedServer.END]
    assert not [r for r in console.seen if r["protocol"] == 0x98 and r["data"][0] == 7]   # no handover
    out = capsys.readouterr().out
    assert "serving the raid battle with scripted" in out and "the served battle is over" in out
