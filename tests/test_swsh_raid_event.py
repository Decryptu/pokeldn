"""An event Max Raid from a Wild Area Event delivery (pokeldn.swsh.raid_event, docs/swsh_raid.md, Event
raids), against Index 010's own files (Wild Area Event #7, Gigantamax Toxtricity), the readme naming
it, PKHeX's distribution encounter list and the den boss records two emulated hosts sent."""
import base64
import hashlib
import json
import random
import struct
import zipfile
import zlib
from pathlib import Path

import pytest

from pokeldn import gen8
from pokeldn.app import events_gallery as gallery, screen
from pokeldn.swsh import beacon, raid, raid_event

import swsh_host

DATA = Path(__file__).parent / "data"
FIXTURE = json.loads((DATA / "swsh_event_010.json").read_text())
SWORD, SHIELD = 1, 2


def event_folder(path):
    path.mkdir(parents=True, exist_ok=True)
    for name, entry in FIXTURE["files"].items():
        raw = zlib.decompress(base64.b64decode(entry["zlib"]))
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        (path / name).write_bytes(raw)
    return path


@pytest.fixture
def event(tmp_path):
    return raid_event.load(event_folder(tmp_path / "Index 010"))


def boss(event, version, stars, species, form=0):
    return next(b for b in event.choices(version, stars - 1) if (b.species, b.form) == (species, form))


def test_index_010_holds_wild_area_event_7_as_its_readme_and_pkhex_name_it(event):
    """The readme: Gigantamax Toxtricity, Kingler and Grimmsnarl in Sword, Orbeetle and Hatterene in
    Shield. PKHeX encounter_sw_dist.pkl, index 10: Toxtricity level 60, Dynamax level 10,
    Gigantamax, five perfect IVs, moves 786 586 482 506, any ability."""
    assert event.index == 10 and event.areas() == ["Wild Area"]
    five = {SWORD: {b.species for b in event.choices(SWORD, 4)}, SHIELD: {b.species for b in event.choices(SHIELD, 4)}}
    assert five == {SWORD: {868, 99, 861, 849}, SHIELD: {868, 826, 858, 849}}
    tox = boss(event, SWORD, 5, 849)
    assert (tox.level, tox.dynamax_level, tox.gigantamax, tox.flawless_ivs, tox.moves, tox.ability) == \
        (60, 10, True, 5, (786, 586, 482, 506), 4)
    assert (tox.shiny, tox.nature, tox.gender, tox.probabilities) == (0, 25, 0, (0, 0, 0, 0, 30))
    assert boss(event, SHIELD, 3, 849, 1).moves == (85, 599, 496, 103)       # Low Key, Shield only
    assert boss(event, SWORD, 3, 849).moves == (85, 474, 496, 103)
    assert [b.name for b in event.choices(SWORD, 2)] == [
        "Gigantamax Milcery", "Gigantamax Kingler", "Morgrem", "Gigantamax Toxtricity"]


def test_every_rank_draws_from_a_hundred_percent(event):
    for version in (SWORD, SHIELD):
        for rank in range(raid_event.RANKS):
            assert sum(b.probabilities[rank] for b in event.choices(version, rank)) == 100


def test_rewards_are_the_bonus_rows_then_the_drops_as_an_emulated_den_gave_them(event):
    """A 1-star boss's bonus table is the game's own: Exp. Candy XS x5, S x1, Dynamax Candy x1, the
    first rows of an emulated den host's Rewards. Its drops come from the delivery's table."""
    milcery = boss(event, SWORD, 1, 868)
    every = raid_event.rewards(event, milcery, 0)
    assert every[:3] == list(raid.DEN_REWARDS[:3])
    assert every[3:] == [(1129, 1), (50, 1), *((item, 1) for item in range(1109, 1116)), (134, 1)]

    class Unlucky(random.Random):
        def randrange(self, *args):
            return 99
    assert raid_event.rewards(event, milcery, 0, Unlucky()) == every[:3] + [(1129, 1), (50, 1)]
    for version in (SWORD, SHIELD):
        for rank in range(raid_event.RANKS):
            for found in event.choices(version, rank):
                assert not raid_event.missing_rewards(event, found)
                assert 0 < len(raid_event.rewards(event, found, rank)) <= raid.REWARD_SLOTS


def den_bosses():
    ads = json.loads((DATA / "swsh_raid_adverts.json").read_text())
    return [bytes.fromhex(ads["boss_hoothoot"]), raid.WILD_BOSS.read_bytes()]


@pytest.mark.parametrize("record", den_bosses(), ids=["hoothoot", "pidove"])
def test_party_stats_experience_and_pp_are_a_recorded_den_bosss(record):
    """Two emulated den hosts' bosses (Hoothoot Dynamax level 2, Pidove level 1): HP carries the
    Dynamax level, experience is the level's least, PP the moves' own."""
    plain = gen8.decrypt(record)
    got = gen8.read(plain)
    base, _ratio, growth, abilities = raid_event.personal(got["species"], got["form"])
    stats = raid_event.party_stats(base, got["ivs"], got["level"], got["nature"],
                                   plain[raid_event.OFF_DYNAMAX_LEVEL])
    assert stats == tuple(got["stats"].values())
    assert struct.unpack_from("<H", plain, raid_event.OFF_HP_CURRENT)[0] == stats[0]
    assert raid_event.encounter.experience(got["level"], growth) == got["experience"]
    assert tuple(raid_event.tables()["move_pp"][str(m)] for m in got["moves"]) == got["move_pp"]
    slot = (plain[raid_event.OFF_ABILITY_NUMBER] & 7).bit_length() - 1
    assert abilities[slot] == got["ability"]


@pytest.mark.parametrize("seed", range(8))
def test_a_boss_record_is_the_tables_boss(event, seed):
    tox = boss(event, SHIELD, 5, 849, 1)
    record = raid_event.boss_pk8(tox, random.Random(seed))
    plain = gen8.decrypt(record)
    got = gen8.read(plain)
    assert (got["species"], got["form"], got["level"], got["moves"]) == (849, 1, 60, tox.moves)
    assert plain[raid.PK8_GIGANTAMAX] & 0x10 and plain[raid_event.OFF_DYNAMAX_LEVEL] == 10
    assert got["ivs"].count(31) >= 5 and got["evs"] == (0,) * 6 and got["held_item"] == 0
    assert got["nature"] in raid_event.encounter.TOXTRICITY_NATURES[1]
    slot = (plain[raid_event.OFF_ABILITY_NUMBER] & 7).bit_length() - 1
    assert got["ability"] == raid_event.personal(849, 1)[3][slot]
    base = raid_event.personal(849, 1)[0]
    assert tuple(got["stats"].values()) == raid_event.party_stats(base, got["ivs"], 60, got["nature"], 10)
    # Everything the den boss record does not take from the boss stays the den host's.
    wild = gen8.read(gen8.decrypt(raid.WILD_BOSS.read_bytes()))
    assert all(got[k] == wild[k] for k in ("trainer_id", "secret_id", "ot_name", "version", "ball", "language"))
    assert gen8.read(gen8.decrypt(raid.boss_record(record)))["species"] == 849
    advert = raid.den_advert(bytes.fromhex(json.loads((DATA / "swsh_raid_adverts.json").read_text())
                                           ["advert_pidove"]), record, 4)
    assert advert[raid.ADVERT_RANK] >> 4 == 4
    assert struct.unpack_from("<H", advert, raid.ADVERT_SHOWN)[0] == 849 | 1 << 10
    assert (advert[raid.ADVERT_SHOWN + 2] >> 4) & 3 == 2
    assert int.from_bytes(advert[0x18:0x1A], "little") == beacon.crc16(advert[0x1A:0x180])


@pytest.mark.parametrize("rule", [raid_event.SHINY_NEVER, raid_event.SHINY_ALWAYS])
def test_the_shiny_rule_holds_for_the_records_trainer(event, rule):
    wild = gen8.read(gen8.decrypt(raid.WILD_BOSS.read_bytes()))
    fixed = raid_event._with(boss(event, SWORD, 5, 849), shiny=rule)
    for seed in range(64):
        pid = gen8.read(gen8.decrypt(raid_event.boss_pk8(fixed, random.Random(seed))))["pid"]
        sparkles = (wild["trainer_id"] ^ wild["secret_id"] ^ (pid >> 16) ^ (pid & 0xFFFF)) < 16
        assert sparkles == (rule == raid_event.SHINY_ALWAYS)


README = """# Wild Area Event
- [Index 001 (Null)](Index%20001%20(Null)) - [Wild Area Event #00](#Wild-Area-Event-00)
- [Index 010](Index%20010) - [Wild Area Event #7](#Wild-Area-Event-7-Gigantamax-Toxtricity)
## [Wild Area Event #00](https://projectpokemon.org/home/files/file/4108-wild-area-event-00/)
## [Wild Area Event #7: Gigantamax Toxtricity](https://projectpokemon.org/home/files/file/4036-wild-area-event-7-gigantamax-toxtricity/)
"""


def test_the_swsh_copy_keeps_each_index_s_files_and_names_it_from_the_readme(tmp_path, monkeypatch):
    events = gallery.SWSH_EVENTS
    source = event_folder(tmp_path / "source")
    files = {f"{events}/Index 010/{p.name}": p.read_bytes() for p in source.iterdir()}
    files.update({f"{events}/readme.md": README.encode(), f"{events}/Index 010/notes.txt": b"x",
                  f"{gallery.RAID_EVENTS}/001 Eevee/Files/raid_enemy_array": b"sv"})
    zipped = tmp_path / "abc.zip"
    with zipfile.ZipFile(zipped, "w") as z:
        for name, data in files.items():
            z.writestr(f"EventsGallery-abc/{name}", data)
    asked = []
    monkeypatch.setattr(gallery, "_latest", lambda game="sv": asked.append(game) or ("abc", "2026-10-18T10:00:00Z"))
    monkeypatch.setattr(gallery.update, "fetch", lambda url, dest, progress, cancelled: dest.write_bytes(
        zipped.read_bytes()))
    root = tmp_path / "data" / gallery.SWSH_FOLDER
    assert gallery.download(root, game="swsh").commit == "abc" and asked == ["swsh"]
    kept = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())
    assert kept == sorted([gallery.MANIFEST, "readme.md", *(f"Index 010/{n}" for n in FIXTURE["files"])])
    assert gallery.holds("Index 010", root, "swsh") and not gallery.holds("Index 011", root, "swsh")
    [entry] = gallery.index(root, "swsh")
    assert (entry.key, entry.title, entry.number, entry.identifier) == (
        "Index 010", "Wild Area Event #7: Gigantamax Toxtricity", 10, 10)
    assert entry.species[:4] == ("Gigantamax Milcery", "Gigantamax Kingler", "Morgrem", "Gigantamax Toxtricity")
    assert gallery.load("Index 010", root, "swsh").index == 10
    gallery.forget()


def test_the_host_picks_an_event_boss_and_refuses_what_does_not_name_one(tmp_path, capsys):
    folder = str(event_folder(tmp_path / "Index 010"))
    app = swsh_host.build_advert(swsh_host.load_advert(str(raid.DEN_ADVERT)))
    pick = lambda *argv: swsh_host.event_raid(swsh_host.build_parser().parse_args(["--raid-event", folder, *argv]), app)
    assert "--raid-stars" in pick()
    listing = pick("--raid-stars", "5")
    assert "4. Gigantamax Toxtricity-1 Lv 60, 30%" in listing       # the emulated den host is a Shield
    assert "pass one" in pick("--raid-stars", "5", "--raid-event-boss", "1", "--raid-boss", "x.pk8")
    assert "no Crown Tundra table" in pick("--raid-area", "Crown Tundra")
    record, rank, rewards = pick("--raid-stars", "5", "--raid-event-boss", "4", "--raid-version", "sword",
                                 "--raid-event-drops", "all")
    assert gen8.read(gen8.decrypt(record))["form"] == 0 and rank == 4
    assert rewards[:3] == [(1127, 2), (1128, 1), (1129, 2)]
    assert swsh_host.main(["--ip-host", "--raid-stars", "5"]) == 1
    assert "pass --raid-event" in capsys.readouterr().out


def test_the_host_shows_a_gigantamax_boss_and_an_adventure_legendary(event, monkeypatch):
    calls = []
    monkeypatch.setattr(screen, "lobby", lambda *args, **kw: calls.append((args, kw)))
    toxtricity = raid_event.boss_pk8(boss(event, SHIELD, 5, 849, 1), random.Random(0))
    ads = json.loads((DATA / "swsh_raid_adverts.json").read_text())
    advert = raid.den_advert(bytes.fromhex(ads["advert_pidove"]), toxtricity, rank=4)
    swsh_host.show_lobby(advert, toxtricity, None, "12345678")
    swsh_host.show_lobby(advert, None, 150, "")
    assert calls == [(("Max Raid", 849, "Toxtricity", 3),
                      {"stars": 5, "code": "12345678", "form": 1, "gigantamax": True}),
                     (("Adventure", 150, "Mewtwo", 3), {"code": ""})]


def test_every_boss_the_app_offers_is_the_one_the_host_picks_and_shows_in_a_den(event, tmp_path):
    """The app's Event boss choices (raid_event.hostable, emitted as --raid-version, --raid-stars,
    --raid-event-boss, --raid-area) name the same boss when the host reads them back, and only bosses
    a base den holds are offered: Index 010's Milcery is not."""
    folder = event_folder(tmp_path / "Index 010")
    offered = raid_event.hostable(event)
    assert offered and all(any(raid.den_slot(v, b.species, b.form, b.gigantamax) for v in (SWORD, SHIELD))
                           for *_, b in offered)
    assert not any(b.species == 868 for *_, b in offered)
    advert = raid.DEN_ADVERT.read_bytes()
    for version, stars, number, area, chosen in offered:
        args = swsh_host.build_parser().parse_args(
            ["--raid-event", str(folder), "--raid-version", version, "--raid-stars", str(stars),
             "--raid-event-boss", str(number), "--raid-area", area])
        pk8, rank, _ = swsh_host.event_raid(args, advert)
        got = gen8.read(gen8.decrypt(pk8))
        assert (got["species"], got["form"], rank) == (chosen.species, chosen.form, stars - 1)
