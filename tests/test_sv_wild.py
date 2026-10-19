"""The Union Circle's crafted encounters (docs/sv_union_circle.md, Crafted encounters): where the host stands
from the wild Pokemon its game shares, our spawns kept out around it, and the app entry."""
import math
import random

import pytest

import sv_join
from pokeldn import gen9
from pokeldn.sv import circle, streams, wild
from test_sv_circle import (DEMO_ENDED, FIELD_KEYS, HOST_OBJECTS, HOST_WALK, RETAIL_SPAWN, moved,
                            position, sent, spawn_out, stands)

MEADOW, LAKE, CAVE = 1, 2, 3
TABLE = wild.Table((
    wild.Area(MEADOW, "Meadow", (wild.Slot(25, 0, 10, 12), wild.Slot(16, 0, 8, 10), wild.Slot(664, -1, 5, 9))),
    wild.Area(LAKE, "Lake", (wild.Slot(25, 0, 11, 14), wild.Slot(129, 0, 5, 20))),
    wild.Area(CAVE, "Cave", (wild.Slot(74, 0, 20, 25), wild.Slot(16, 0, 8, 10))),
))
PIKACHU, PIDGEY, MAGIKARP, GEODUDE = 25, 16, 129, 74


def test_a_table_reads_pkhex_s_reply_and_answers_where_and_at_which_levels():
    reply = {"areas": [{"location": 7, "name": "Meadow", "slots": [[25, 0, 10, 12], [664, -1, 5, 9]]}]}
    table = wild.table(reply)
    assert [a.location for a in table.where(25, 0, 11)] == [7] and table.where(25, 0, 13) == []
    assert table.where(664, 18, 6) and table.levels(25, 0) == [10, 11, 12]
    assert table.name(7) == "Meadow" and table.name(99) == "location 99"


def locating(wanted):
    locator = wild.Locator(TABLE, wanted)
    locator.host_moved((0.0, 0.0, 0.0))
    return locator


def test_the_host_s_spawns_narrow_its_area_until_our_spawn_is_legal_in_every_one_left():
    locator = locating({MEADOW})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    assert locator.candidates == {MEADOW, LAKE} and not locator.found
    locator.host_spawn(PIDGEY, 0, 9, (0.0, 0.0, 20.0))
    assert locator.candidates == {MEADOW} and locator.found and locator.found_at == (0.0, 0.0, 0.0)
    assert locator.notes[-1] == "the host's area is found: Meadow, where our spawn is legal"


def test_every_area_left_allowing_our_spawn_is_enough():
    locator = locating({MEADOW, LAKE})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    assert locator.found


def test_an_area_our_spawn_is_not_legal_in_is_never_found():
    locator = locating({MEADOW})
    locator.host_spawn(MAGIKARP, 0, 6, (10.0, 0.0, 0.0))
    assert locator.candidates == {LAKE} and not locator.found
    assert locator.notes == []      # a step of the search, not news
    assert locator.details == ["the host is in one of 1 area(s): Lake; our spawn is legal in 0 of them"]


def test_a_spawn_no_area_left_holds_starts_over_from_it():
    locator = locating({CAVE})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    locator.host_spawn(GEODUDE, 0, 22, (12.0, 0.0, 0.0))
    assert locator.candidates == {CAVE} and locator.found
    assert locator.spawns == [(GEODUDE, 0, 22, (12.0, 0.0, 0.0))]


def test_a_spawn_no_wild_slot_holds_is_left_out():
    locator = locating({MEADOW})
    locator.host_spawn(PIKACHU, 0, 99, (10.0, 0.0, 0.0))
    assert locator.candidates is None and locator.details[-1].endswith("fits no wild slot; left out")


def test_a_drawn_form_fits_any_form():
    locator = locating({MEADOW})
    locator.host_spawn(664, 7, 6, (10.0, 0.0, 0.0))
    assert locator.found


def test_a_host_far_from_a_spawn_weighed_starts_over():
    locator = locating({MEADOW})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    locator.host_moved((10.0, 0.0, wild.SPREAD - 1))
    assert locator.candidates == {MEADOW, LAKE}
    locator.host_moved((10.0, 0.0, wild.SPREAD + 1))
    assert locator.candidates is None and locator.spawns == []


def test_the_area_found_holds_within_fifty_metres_of_where_it_was_found():
    locator = locating({MEADOW, LAKE})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    locator.host_moved((wild.HOLD - 1, 0.0, 0.0))
    locator.host_spawn(MAGIKARP, 0, 6, (60.0, 0.0, 0.0))     # weighed no more once found
    assert locator.found and locator.candidates == {MEADOW, LAKE}
    locator.host_moved((wild.HOLD + 1, 0.0, 0.0))
    assert not locator.found and locator.spawns == []
    assert locator.notes[-1].startswith("the host went more than 50 m from where its area was found")


class Located:
    """A locator whose verdict a test sets."""

    def __init__(self):
        self.found, self.notes, self.details, self.spawns, self.at = False, [], [], [], []

    def host_spawn(self, *spawn):
        self.spawns.append(spawn)

    def host_moved(self, at):
        self.at.append(at)


def keeping(copies=circle.SPAWN_COPIES, locator=None, crafted=None):
    """-> a member keeping `copies` Pikachu (dev number) out from the demo's end at 100, the host's
    player where HOST_WALK has it."""
    member = circle.Member(spawner=circle.Spawner(25, 12, tera=12, copies=copies, crafted=crafted,
                                                  rng=random.Random(1)),
                           locator=locator)
    member.on_table(FIELD_KEYS)
    for declaration in HOST_OBJECTS:
        member.on_object(declaration)
    sent(member)
    member.on_lua(DEMO_ENDED)
    member.tick(100.0)
    stands(member, HOST_WALK, 100.0)
    return member


def run(member, start, end, step=0.05):
    """-> the labels of the spawns and removals sent from `start` to `end`."""
    labels, now = [], start
    while now < end:
        labels += [label for label, _ in spawn_out(member, round(now, 2))[0] if label]
        now += step
    return labels


def test_a_member_keeps_three_out_15_to_25_metres_from_the_host():
    member = keeping()
    labels = run(member, 110.0, 120.0)
    assert len([l for l in labels if "species 25 level 12" in l]) == 3 and len(member.spawner.live) == 3
    host = position(HOST_WALK)
    for _, at, _, _ in member.spawner.live:
        assert 15.0 <= math.hypot(at[0] - host[0], at[2] - host[2]) <= 25.0


def test_one_the_host_battles_comes_again():
    member = keeping()
    run(member, 110.0, 113.0)
    station, n = streams.JOINER_INDEX, circle.SPAWN_FIRST
    member.on_object(bytes.fromhex("260005b902b90201810001b9020006"))
    labels = run(member, 113.0, 115.0)
    assert member.notes == ["our spawns are coming out around the host's player",
                            "a console battles one of our spawns; another comes"]
    assert labels[0] == f"spawn ({station}, {n}) handed over as (0, 6)"
    assert labels[1].startswith(f"spawn ({station}, {n + 3}) species 25")


def test_one_the_host_removes_comes_again():
    member = keeping()
    run(member, 110.0, 113.0)
    station, n = streams.JOINER_INDEX, circle.SPAWN_FIRST + 1
    member.on_lua(bytes.fromhex("260002") + circle.spawn_id(station, n))
    labels = run(member, 113.0, 115.0)
    assert member.details == [f"the host removed our spawn ({station}, {n}); another comes"]
    assert labels[0].startswith(f"spawn ({station}, {circle.SPAWN_FIRST + 3}) species 25")
    # Another station's spawn the host removes is none of ours.
    member.on_lua(bytes.fromhex("260002") + circle.spawn_id(0, n))
    assert len(member.spawner.live) == 3


def test_one_the_host_walks_away_from_goes_and_comes_again_near_it():
    member = keeping()
    run(member, 110.0, 113.0)
    stands(member, moved(HOST_WALK, 0.0, circle.SPAWN_CULL + 30), 113.0)
    labels = run(member, 113.0, 117.0)
    gone = [l for l in labels if l.endswith(f"gone: the host is more than {circle.SPAWN_CULL:g} m away")]
    assert len(gone) == 3 and len(member.spawner.live) == 3
    host = position(moved(HOST_WALK, 0.0, circle.SPAWN_CULL + 30))
    for _, at, _, _ in member.spawner.live:
        assert math.hypot(at[0] - host[0], at[2] - host[2]) <= 25.0


def test_the_crafted_values_go_in_the_record():
    member = keeping(crafted={"form": 1, "item": 234, "scale": 255, "sex": 1, "nature": 3,
                              "ivs": (31, 0, 31, 0, 31, 0), "ability": 2})
    messages = []
    for now in (110.0, 110.05):
        messages += spawn_out(member, now)[0]
    fields = circle.record_fields([plain for label, plain in messages if label][0][5:])
    assert {k: fields[k] for k in ("species", "form", "item", "scale", "sex", "nature", "ivs", "ability", "tera")} == {
        "species": 25, "form": 1, "item": 234, "scale": 255, "sex": 1, "nature": 3,
        "ivs": (31, 0, 31, 0, 31, 0), "ability": 2, "tera": 12}


def test_a_located_member_spawns_only_while_the_host_s_area_is_found():
    located = Located()
    member = keeping(locator=located)
    assert run(member, 110.0, 114.0) == [] and set(located.at) == {position(HOST_WALK)}
    member.on_lua(bytes.fromhex("260001bc60") + RETAIL_SPAWN)
    ((species, form, level, at),) = located.spawns
    assert (species, form, level) == (gen9.national(954), 0, 27)
    located.found = True
    assert len(run(member, 114.0, 118.0)) == 3
    lost = "the host went more than 50 m from where its area was found"
    located.found, located.notes = False, [lost]
    labels = run(member, 118.0, 119.0)
    assert len([l for l in labels if " gone" in l]) == 3 and member.spawner.live == []
    assert member.notes == ["our spawns are coming out around the host's player", lost]
    assert located.notes == []


def host_spawn(member, n, at, now):
    """The host's console shares its wild Pikachu `n` (station 0) standing at `at`, at `now`."""
    record = circle.spawn_record(4 * n, at, species=25, level=12)
    member.on_lua(bytes.fromhex("260001bc60") + record, now)


def test_with_the_host_s_transforms_gone_its_newest_spawns_place_it():
    """As in Area Zero: the host's console shares its wild Pokemon but not where its player stands."""
    located = Located()
    member = keeping(locator=located)
    run(member, 110.0, 111.0)
    member.test_host_frame = None
    x, y, z = position(HOST_WALK)
    far = [(x + 300.0 + dx, y - 40.0, z + dz) for dx, dz in ((10, 0), (-10, 0), (0, 20), (0, -20))]
    for n, at in enumerate(far):
        host_spawn(member, 0x40 + n, at, 111.5)
    assert member.host_at == tuple(position(HOST_WALK)) and located.source == wild.GAME   # still fresh
    labels = run(member, 111.5, 114.0)
    middle = (x + 300.0, y - 40.0, z)
    assert located.source == wild.SPAWNS and member.host_at == pytest.approx(middle)
    assert located.at[-1] == pytest.approx(middle)
    located.found = True
    labels = run(member, 114.0, 118.0)
    assert len([l for l in labels if "species 25 level 12" in l]) == 3
    for _, at, _, _ in member.spawner.live:
        assert 15.0 <= math.hypot(at[0] - middle[0], at[2] - middle[2]) <= 25.0 and at[1] == pytest.approx(y - 40.0)
    # Only the newest few count, and only for a while.
    for n in range(circle.ESTIMATE_SPAWNS):
        host_spawn(member, 0x50 + n, (x + 600.0, y, z), 118.0)
    assert member.host_at == pytest.approx((x + 600.0, y, z))
    run(member, 118.0, 118.0 + circle.ESTIMATE_WINDOW + 0.1)
    assert located.source == wild.LOST and member.host_at is None
    assert run(member, 149.0, 150.0) == [] and len(member.spawner.live) == 3
    stands(member, HOST_WALK, 150.0)
    run(member, 150.0, 150.2)
    assert located.source == wild.GAME and member.host_at == tuple(position(HOST_WALK))


def test_a_transform_at_the_origin_does_not_place_the_host():
    member = keeping()
    import struct
    set_down = (HOST_WALK[:circle.POSITION_AT] + struct.pack("<3f", 0.0, 0.0, -2.0)
                + HOST_WALK[circle.POSITION_AT + 12:])
    member.on_frame(set_down, 100.5)
    assert member.host_at == tuple(position(HOST_WALK))


def test_the_zone_card_says_when_the_host_s_position_is_estimated_or_lost():
    locator = locating({MEADOW, LAKE})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    locator.source = wild.SPAWNS
    assert rows(card_of(locator))["Your position"].startswith("Estimated from the wild Pokemon")
    assert rows(card_of(locator))["Stay within"].endswith("now 0 m")
    locator.source = wild.LOST
    card = card_of(locator)
    assert rows(card)["Your position"].startswith("Your game stopped sharing where you stand")
    assert rows(card)["Stay within"] == "50 m of where it was found"
    locator.source = wild.GAME
    assert "Your position" not in rows(card_of(locator))


def test_our_own_spawns_are_not_weighed():
    located = Located()
    member = keeping(locator=located)
    ours = bytearray(RETAIL_SPAWN)
    ours[:2] = (streams.JOINER_INDEX + 4 * 300).to_bytes(2, "little")
    member.on_lua(bytes.fromhex("260001bc60") + bytes(ours))
    assert located.spawns == []


# The app entry

def encounters_tool():
    from pokeldn.app import catalog
    return next(t for t in catalog.SV.tools if t.key == "sv-circle-encounters-join")


def test_the_encounters_entry_crafts_the_spawn_s_arguments():
    from pokeldn.app import command
    from pokeldn.app.introspect import parser_of
    from pokeldn.app.settings import Settings
    tool = encounters_tool()
    values = {"--code": "4807"}
    assert command.problems(tool, values) == ["Pick the Pokemon to spawn."]
    values["--spawn"] = {"legal": True, "species": 906, "level": 20, "shiny": True, "tera": 11, "form": 0,
                         "nature": None, "gender": 1, "ability": 2, "scale": None, "item": 0,
                         "ivs": "31/31/31/0/0/31"}
    assert command.problems(tool, values) == []
    parsed = parser_of(tool.script).parse_args(command.build(tool, values, {}, Settings()))
    assert parsed.union_circle and parsed.follow_host
    assert parsed.spawn == (gen9.internal_index(906), 20) and parsed.spawn_legal and parsed.spawn_shiny
    assert (parsed.spawn_tera, parsed.spawn_form, parsed.spawn_gender, parsed.spawn_ability) == (11, 0, 1, 2)
    assert parsed.spawn_nature is None and parsed.spawn_scale is None and parsed.spawn_item is None
    assert sv_join.spawn_ivs(parsed.spawn_ivs) == (31, 31, 31, 31, 0, 0)    # HP Atk Def Spe SpA SpD
    values["--spawn"] = dict(values["--spawn"], legal=False, level=0)
    assert command.problems(tool, values) == ["The level is 1 to 100."]


def circle_args(argv):
    ap = sv_join.build_parser()
    args = ap.parse_args(["--union-circle", *argv])
    return ap, args


def test_a_legal_spawn_learns_where_pkhex_accepts_it(monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(wild, "areas", lambda service: TABLE)
    monkeypatch.setattr(wild, "legal_at", lambda service, spawn: asked.append(spawn) or ([MEADOW, LAKE], {}))
    ap, args = circle_args(["--spawn", "25:11", "--spawn-legal", "--spawn-tera", "12", "--spawn-ivs",
                            "31/30/29/28/27/26", "--spawn-gender", "1"])
    sv_join.circle_guest(ap, args)
    assert args.spawn_wanted == [MEADOW, LAKE] and args.spawn_table is TABLE
    assert asked[0]["species"] == 25 and asked[0]["level"] == 11 and asked[0]["tera"] == 12
    assert asked[0]["ivs"] == [31, 30, 29, 26, 28, 27] and asked[0]["gender"] == 1
    assert "at 2 location(s): Meadow, Lake" in capsys.readouterr().out


def test_a_legal_spawn_pkhex_accepts_nowhere_stops_the_run(monkeypatch, capsys):
    monkeypatch.setattr(wild, "areas", lambda service: TABLE)
    monkeypatch.setattr(wild, "legal_at", lambda service, spawn: ([], {LAKE: ["Tera Type mismatch."]}))
    ap, args = circle_args(["--spawn", "25:11", "--spawn-legal", "--spawn-tera", "9"])
    with pytest.raises(SystemExit):
        sv_join.circle_guest(ap, args)
    assert "caught nowhere (Lake: Tera Type mismatch.)" in capsys.readouterr().err


@pytest.mark.parametrize("argv, why", [
    (["--spawn-legal"], "checks the --spawn"),
    (["--spawn", "25"], "is not SPECIES:LEVEL"),
    (["--spawn", "25:0"], "at a level from 1 to 100"),
    (["--spawn", "25:101"], "at a level from 1 to 100"),
    (["--spawn", "25:11", "--spawn-scale", "256"], "do not fit its record"),
    (["--spawn", "25:11", "--spawn-ivs", "31/31/31/31/31/32"], "do not fit its record")])
def test_a_crafted_spawn_refuses_what_its_record_cannot_carry(argv, why, capsys):
    with pytest.raises(SystemExit):
        ap, args = circle_args(argv)
        sv_join.circle_guest(ap, args)
    assert why in capsys.readouterr().err


def _pkhex_available():
    from pokeldn import pokemon
    try:
        pokemon._command()
    except pokemon.BuilderError:
        return False
    return True


@pytest.mark.skipif(not _pkhex_available(), reason="needs the PKHeX helper")
def test_pkhex_accepts_a_wild_pikachu_only_where_and_as_its_slots_allow():
    """Paldea's Pikachu are Electric Tera Types; Kitakami's take any, as PKHeX reads its outbreaks there."""
    from pokeldn import pokemon
    service = pokemon.Service()
    try:
        table = wild.areas(service)
        assert 10 in table.levels(25, 0) and 99 not in table.levels(25, 0)
        pikachu = {"species": 25, "form": 0, "level": 10, "shiny": True, "ability": 2}
        places = {p["name"]: p for p in wild.scan(service, dict(pikachu, tera=12))}
        assert set(places) == {a.name for a in table.where(25, 0, 10)}
        assert places["South Province (Area Two)"]["teras"] == [12]
        assert places["Kitakami Road"]["teras"] == list(range(18))
        legal, refused = wild.legal_at(service, dict(pikachu, tera=9))
        assert {table.name(loc) for loc in legal} == {"Kitakami Road", "Apple Hills", "Wistful Fields"}
        assert refused and all(refused.values())
        assert wild.legal_at(service, dict(pikachu, level=99, tera=12)) == ([], {})
        info = wild.species(service, 25)
        assert info["types"] == [12, 12] and [a["slot"] for a in info["abilities"]] == [0, 1, 2]
        bundle = {"species": 991, "form": 0, "level": 57, "shiny": False, "gender": 0, "tera": 10}
        assert [(p["name"], p["teras"]) for p in wild.scan(service, bundle)] == [("Area Zero (5)", [10, 14])]
    finally:
        service.close()


# The zone search's status card

def card_of(locator):
    from pokeldn import panel
    shown = wild.card(locator)
    return panel.read(panel.PREFIX + __import__("json").dumps(
        {"id": "zone", **{k: v for k, v in shown.items()}}))     # within what a [panel] line holds


def rows(card):
    return {row[0]: row[1] for row in card["lines"] if isinstance(row, list)}


def test_the_zone_card_starts_finding_and_advises_a_picnic():
    card = card_of(locating({MEADOW}))
    assert card["title"] == "Finding your area" and card["tone"] == "info" and card["chips"] == []
    assert rows(card) == {"Legal at": "Meadow"} and wild.PICNIC in card["lines"]


def test_the_zone_card_counts_what_is_left_while_narrowing():
    locator = locating({MEADOW})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    card = card_of(locator)
    assert card["title"] == "Narrowing down your area"
    assert card["chips"] == [["Areas left", "2"], ["Legal in", "1"], ["Pokemon weighed", "1"]]
    assert rows(card) == {"You may be in": "Lake, Meadow", "Legal at": "Meadow"}


def test_the_zone_card_says_where_to_go_when_no_area_left_allows_it():
    locator = locating({MEADOW})
    locator.host_spawn(MAGIKARP, 0, 6, (10.0, 0.0, 0.0))
    card = card_of(locator)
    assert card["title"] == "Not in an area where it is legal" and card["tone"] == "error"
    assert rows(card) == {"You seem to be in": "Lake", "Go to": "Meadow"} and wild.PICNIC in card["lines"]


def test_the_zone_card_shows_the_area_found_and_how_far_the_host_went_in_steps():
    locator = locating({MEADOW, LAKE})
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    locator.host_moved((13.0, 0.0, 0.0))
    card = card_of(locator)
    assert card["title"] == "Area found: spawning" and card["tone"] == "ok"
    assert rows(card) == {"You are in": "Lake, Meadow", "Stay within": "50 m of where it was found: now 10 m"}
    locator.host_moved((14.0, 0.0, 0.0))
    assert wild.card(locator) == wild.card(locator) and rows(card_of(locator))["Stay within"].endswith("now 10 m")


@pytest.mark.parametrize("wanted, moves, why, then", [
    ({MEADOW, LAKE}, [(10.0, 0.0, 0.0), (wild.HOLD + 11, 0.0, 0.0)],
     "more than 50 m from where your area was found", "Area found: spawning"),
    ({MEADOW}, [(10.0, 0.0, wild.SPREAD + 1)],
     "more than 100 m from a wild Pokemon it had read", "Not in an area where it is legal")])
def test_the_zone_card_shows_a_reset_after_moving_too_far_until_the_next_spawn(wanted, moves, why, then):
    locator = locating(wanted)
    locator.host_spawn(PIKACHU, 0, 11, (10.0, 0.0, 0.0))
    for at in moves:
        locator.host_moved(at)
    card = card_of(locator)
    assert card["title"] == "Moved too far: finding your area again" and card["tone"] == "warning"
    assert why in rows(card)["Why"]
    locator.host_spawn(MAGIKARP, 0, 6, (60.0, 0.0, 0.0))
    assert card_of(locator)["title"] == then


def test_a_long_list_of_areas_is_cut_with_how_many_more():
    names = [f"South Province (Area {n})" for n in range(12)]
    listed = wild._listed(names)
    assert len(listed) <= wild.CARD_NAMES and listed.endswith(" more")
    assert wild._listed(names[:2]) == "South Province (Area 0), South Province (Area 1)"


def test_a_built_in_run_s_cards_top_its_tool_s_options_only_while_it_runs(monkeypatch):
    import flet as ft
    from types import SimpleNamespace
    from gui.views.games import GamesView, SessionPanel
    from pokeldn import panel as cards, plugins
    monkeypatch.setattr(plugins, "owner", lambda key: None)
    tool, other = encounters_tool(), SimpleNamespace(key="sv-circle-join")
    process = SimpleNamespace(running=True)
    app = SimpleNamespace(ui=lambda fn: fn(), process=process)
    logged = []
    games = GamesView.__new__(GamesView)
    session = SessionPanel.__new__(SessionPanel)
    games.__dict__.update(app=app, session=session, tool=tool, run_panel=ft.Column(visible=False))
    session.__dict__.update(app=app, games=games, log=SimpleNamespace(add=logged.append), run_cards={},
                            partner_state=None, traded=0, running_tool=tool)
    printed = []
    monkeypatch.setattr("builtins.print", lambda line, **kw: printed.append(line))
    cards.show("zone", "Narrowing down your area", ["You may be in\tLake, Meadow"], chips=[("Areas left", "2")])
    cards.show("zone", "Area found: spawning", ["You are in\tMeadow"], tone="ok")
    for line in printed:
        session._line(line)
    assert logged == [] and list(session.run_cards) == ["zone"]
    assert session.run_cards["zone"]["title"] == "Area found: spawning"
    assert games.run_panel.visible and len(games.run_panel.controls) == 1
    games.tool = other                          # another tool's page: not there
    games.show_run_cards(update=False)
    assert not games.run_panel.visible
    games.tool, process.running = tool, False   # the run is over
    games.show_run_cards(update=False)
    assert not games.run_panel.visible
    process.running = True
    printed.clear()
    cards.clear("zone")
    session._line(printed[0])
    assert not games.run_panel.visible and session.run_cards == {}


def test_a_union_circle_link_code_starts_empty_at_every_launch():
    from gui.views.games import forget_unremembered
    from pokeldn.app import catalog
    codes = [f for t in catalog.SV.tools if "circle" in t.key for f in t.fields if f.flag == "--code"]
    assert len(codes) == 2 and not any(f.remembered for f in codes)
    stored = {"sv-circle-join": {"values": {"--code": "1826", "--circle-task": "bp"}},
              "sv-circle-encounters-join": {"values": {"--code": "4807"}},
              "sv-raid-host": {"values": {"--code": "12345678"}}}
    forget_unremembered(stored, [catalog.SV])
    assert stored["sv-circle-join"]["values"] == {"--circle-task": "bp"}
    assert stored["sv-circle-encounters-join"]["values"] == {}
    assert stored["sv-raid-host"]["values"] == {"--code": "12345678"}


def test_a_new_species_on_the_card_starts_over_from_a_wild_one(monkeypatch):
    from types import SimpleNamespace
    from gui.views.encounter import EncounterPicker
    picker = EncounterPicker.__new__(EncounterPicker)
    loads = []
    picker.__dict__.update(value={"legal": True, "species": 25, "form": 8, "level": 57, "shiny": True, "tera": 11,
                                  "nature": 3, "gender": 1, "ability": 2, "scale": 9, "item": 4, "ivs": "1/2/3/4/5/6"},
                           info={}, scanned=[])
    picker._save = lambda redraw=True: None
    picker._load_species = lambda: loads.append(dict(picker.value))
    picker._species(SimpleNamespace(control=SimpleNamespace(value="991")))
    assert loads == [{"legal": True, "species": 991, "form": 0, "shiny": True}]
    assert picker.info is None and picker.scanned is None
    picker.value.update(legal=False, level=30)
    picker._species(SimpleNamespace(control=SimpleNamespace(value="25")))
    assert loads[-1] == {"legal": False, "species": 25, "form": 0, "level": 30, "shiny": True}
