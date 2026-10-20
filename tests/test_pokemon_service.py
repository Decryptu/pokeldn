"""The shared service validates the bytes every game adapter actually sends."""
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pokeldn import gen8, gen9, pokemon
from pokeldn.app.settings import Settings
from pokeldn.pla import pokemon as pa8
from pokeldn.swsh import wc8

TRAINER = {"ot": "POKELDN", "tid": 12345, "sid": 54321, "language": 2, "gender": 0}
FORMATS = {"frlg": "PK3", "lgpe": "PB7", "swsh": "PK8", "bdsp": "PB8", "pla": "PA8", "sv": "PK9", "za": "PA9"}


@pytest.fixture
def display(service, monkeypatch):
    """gui.localization's display service in a chosen pack locale, over the shared PKHeX process."""
    from gui.localization import DisplayService
    from pokeldn.app import i18n

    def make(language):
        monkeypatch.setattr(i18n, "locale", lambda: language)
        return DisplayService()
    return make


@pytest.mark.parametrize("language,game,kind,names", [
    ("zh-Hans", "frlg", "species", {25: "皮卡丘", 252: "木守宫"}),
    ("zh-Hans", "frlg", "species3", {25: "皮卡丘", 277: "木守宫"}),          # Treecko: national 252, cartridge 277
    ("zh-Hans", "frlg", "items", {42: "黑色玻璃哨", 68: "神奇糖果", 374: "蓝宝石"}),   # Gen 3 item ids
    ("fr-FR", "sv", "species", {7: "Carapuce"}),
    ("de", "sv", "species", {4: "Glumanda"}),
    ("unknown-XX", "sv", "species", {4: "Charmander"}),
])
def test_a_display_language_names_the_same_ids(service, display, language, game, kind, names):
    shown = {n["id"]: n["name"] for n in display(language).names(game, kind)}
    english = service.names(game, kind)
    assert {n: shown[n] for n in names} == names
    assert set(shown) == {n["id"] for n in english}


@pytest.mark.parametrize("mode", ["empty", "made"])
def test_a_display_language_builds_the_same_record_with_english_names_kept(service, display, mode):
    service.home_tracker = mode
    try:
        shown = display("zh-Hans")
        found = shown.paste("sv", "Pikachu @ Light Ball\nAbility: Static\nTimid Nature\n- Thunderbolt", TRAINER)[0]
        assert not found["errors"] and found["species"] == "皮卡丘" and found["moves"] == ["十万伏特"]
        assert (found["options"]["held_item"], found["options"]["ability"]) == (236, 9)
        built = shown.make("swsh", 809, TRAINER)
        assert built["species"] == "美录梅塔" and built["legal"] and built["home_tracker"] == mode
        assert (built["tracker"] != "0") == (mode == "made")
        info = shown.make("sv", 25, TRAINER)
        assert info["canonical"]["species"] == "Pikachu" and info["is_nicknamed"] is False
        assert pokemon.summary(info).startswith("Pikachu · level ") and "'" not in pokemon.summary(info)
        assert Path(info["file"]).name.startswith("Pikachu-")
        assert service.check_bytes("sv", base64.b64decode(info["data"]))["legal"]
    finally:
        service.home_tracker = "empty"


@pytest.mark.parametrize("failure, error, requests", [
    ("interrupted", None, 2),
    ("persistent", "could not complete its legality analysis after restarting", 2),
    ("illegal", "Invalid: encounter mismatch", 1),
    ("interrupted-then-illegal", "Invalid: encounter mismatch", 2),
])
def test_an_interrupted_analysis_is_retried_in_a_fresh_process(tmp_path, monkeypatch,
                                                             failure, error, requests):
    """A JSON-line validator whose analysis fails until restart; completed illegal checks stay refused."""
    helper = tmp_path / "validator.py"
    trace = tmp_path / "requests.jsonl"
    helper.write_text('''import json, sys
from pathlib import Path
from uuid import uuid4

trace, failure = Path(sys.argv[1]), sys.argv[2]
first_process = not trace.exists()
process = uuid4().hex
for line in sys.stdin:
    request = json.loads(line)
    with trace.open("a") as out:
        out.write(json.dumps({"process": process, "request": request}) + "\\n")
    parsed = not (failure == "persistent" or (first_process and failure.startswith("interrupted")))
    legal = parsed and "illegal" not in failure
    print(json.dumps({"ok": True, "parsed": parsed, "legal": legal, "data": request["data"],
                      "report": "Legal!" if legal else "Invalid: encounter mismatch" if parsed else
                                "Analysis not available for this Pokémon."}), flush=True)
''', encoding="utf-8")
    monkeypatch.setattr(pokemon, "_command", lambda: [sys.executable, str(helper), str(trace), failure])
    from pokeldn.pla.trade_box import REFERENCE_RECORD
    instance = pokemon.Service()
    try:
        if error:
            with pytest.raises(pokemon.BuilderError, match=error):
                instance.prepare("pla", REFERENCE_RECORD, fresh=True, fields={"ot_name": "HOST"})
        else:
            assert instance.prepare("pla", REFERENCE_RECORD, fresh=True,
                                    fields={"ot_name": "HOST"}) == REFERENCE_RECORD
    finally:
        instance.close()
    recorded = [json.loads(line) for line in trace.read_text().splitlines()]
    assert len(recorded) == requests
    assert len({row["process"] for row in recorded}) == requests
    assert all(row["request"] == {"cmd": "check", "game": "pla", "fresh": True,
                                  "data": base64.b64encode(REFERENCE_RECORD).decode(),
                                  "fields": {"ot_name": "HOST"}, "home_tracker": "empty"} for row in recorded)


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    try:
        pokemon._command()
    except pokemon.BuilderError:
        if not shutil.which("dotnet"):
            pytest.skip("PKHeX integration needs the .NET 10 SDK or a published service")
        subprocess.run(["dotnet", "build", "-c", "Release", pokemon.HERE, "-warnaserror"], check=True)
    patch = pytest.MonkeyPatch()
    patch.setattr(pokemon, "POKEMON", tmp_path_factory.mktemp("pokemon"))
    patch.setattr(pokemon, "SESSION", tmp_path_factory.mktemp("session"))
    instance = pokemon.Service()
    patch.setattr(pokemon, "SERVICE", instance)
    yield instance
    instance.close()
    patch.undo()


@pytest.mark.parametrize("game", FORMATS)
def test_creation_import_and_launcher_preparation_remain_legal(service, game):
    built = service.make(game, 25, TRAINER)
    imported = service.import_file(game, built["file"])
    assert imported["legal"] and imported["format"] == FORMATS[game]
    assert imported["file"] != built["file"]
    offer = pokemon.prepare_file(game, imported["file"], fresh=True)   # the launchers' --fresh-pid
    final = service.check_bytes(game, Path(offer).read_bytes())
    assert final["legal"] and final["ot"] == imported["ot"]
    assert "Event" not in built["encounter"]   # Pikachu has wild and egg encounters in every game


@pytest.mark.parametrize("game", FORMATS)
def test_a_built_pokemon_shows_the_trainer_typed_in_settings(service, game):
    """FireRed shows the 16-bit TID; a Switch title shows the 32-bit id as six digits and a secret ID,
    here the largest pair 32 bits hold. PKHeX's DisplayTID reads them back. Z-A matches the gender too."""
    settings = Settings(tid=12345, sid=54321, switch_tid=967295, switch_sid=4294, gender=1)
    built = service.make(game, 25, settings.trainer(game))
    shown = (12345, 54321) if game == "frlg" else (967295, 4294)
    assert (built["trainer_id"], built["secret_id"], built["ot_gender"]) == (*shown, 1) and built["legal"]


def test_an_event_pokemon_offered_under_a_new_pid_keeps_its_own(service, capsys):
    """Melmetal reaches Sword only as an event; its PID is part of the event."""
    built = service.make("swsh", 809, TRAINER)
    assert "Event" in built["encounter"] or "Gift" in built["encounter"]
    offer = Path(pokemon.prepare_file("swsh", built["file"], fresh=True)).read_bytes()
    assert service.check_bytes("swsh", offer)["legal"]
    assert offer[:4] == base64.b64decode(built["data"])[:4]   # the encryption constant
    assert "kept its own PID" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["empty", "made"])
def test_an_event_that_reached_the_game_through_home_gets_the_tracker_the_setting_asks_for(service, monkeypatch,
                                                                                         mode):
    """Melmetal reached Sword only through HOME, so PKHeX wants a HOME tracker on it [HomeTrackerUtil]. "made"
    fills one; "empty" leaves it unset, and that one problem is accepted there and by the launcher's check."""
    monkeypatch.setattr(service, "home_tracker", mode)
    built = service.make("swsh", 809, TRAINER)
    assert built["legal"] and built["home_tracker"] == mode and (built["tracker"] != "0") == (mode == "made")
    offer = Path(pokemon.prepare_file("swsh", built["file"])).read_bytes()
    assert service.check_bytes("swsh", offer)["legal"]
    monkeypatch.setattr(service, "home_tracker", "made")
    refused = service.check_bytes("swsh", base64.b64decode(built["data"]))
    assert refused["legal"] == (mode == "made") and refused["home_tracker"] == ("empty" if mode == "empty" else "")


@pytest.mark.parametrize("game, species, edit, encounter", [
    ("swsh", 823, {}, "Wild"),          # Corviknight: PKHeX lists an egg and dozens of raid dens before Route 10
    ("frlg", 16, {}, "Wild"),
    ("sv", 963, {"level": 1}, "Egg"),   # Finizen: only an egg is level 1, and PKHeX lists it after 300 others
])
def test_a_species_is_built_as_a_catch_and_hatched_only_when_nothing_else_carries_the_request(service, game, species,
                                                                                               edit, encounter):
    built = service.make(game, species, TRAINER, **edit)
    assert built["legal"] and built["encounter"].startswith(encounter)


@pytest.mark.parametrize("game, species, edit", [
    ("frlg", 132, {"shiny": True}),                      # a Gen 3 PID is chosen with the encounter, not patched in
    ("frlg", 132, {"shiny": True, "version": "LG"}),
    ("frlg", 6, {"shiny": True}),                        # an evolved starter must be raised to its evolution level
    ("frlg", 2, {}),
    ("pla", 36, {"level": 50}),                          # height and weight follow the evolved species
    ("za", 16, {"level": 50}),                           # plus-move flags follow the level
    ("bdsp", 12, {}),                                    # the ability names the species the encounter was
    ("bdsp", 186, {}),                                   # a trade evolution needs a second handler
    ("lgpe", 65, {}),
    ("za", 1000, {}),                                    # a repair that fixes one species must not be applied first to another
    ("bdsp", 416, {}),                                   # a female-only species comes only from a female encounter
    ("bdsp", 292, {}),                                   # Shedinja is genderless though Nincada is not
    ("za", 865, {}),                                     # Galarian Farfetch'd evolves into a species with one form
    ("bdsp", 350, {}),                                   # Milotic evolves at Beauty 170, which needs Sheen
    ("za", 801, {}),                                     # a gift that arrives already handled
])
def test_a_shiny_level_or_evolved_request_is_built_legal(service, game, species, edit):
    built = service.make(game, species, TRAINER, **edit)
    assert built["legal"]
    assert built["shiny"] == edit.get("shiny", False)
    if "level" in edit:
        assert built["level"] == edit["level"]


# Growlithe, Arcanine, Voltorb, Electrode, Typhlosion, Qwilfish, Samurott, Lilligant, Basculin, Zorua, Zoroark,
# Braviary, Sliggoo, Goodra, Avalugg, Decidueye: Legends Arceus has them only in a Hisuian form.
HISUIAN_ONLY = [58, 59, 100, 101, 157, 211, 503, 549, 550, 570, 571, 628, 705, 706, 713, 724]


def test_the_legends_arceus_list_is_the_hisui_dex_and_a_hisuian_only_species_builds(service):
    listed = {s["id"] for s in service.species("pla")}
    assert len(listed) == 242 and set(HISUIAN_ONLY) <= listed
    for species in HISUIAN_ONLY:
        built = service.make("pla", species, TRAINER)
        assert built["legal"] and pa8.read(pa8.load(base64.b64decode(built["data"])))["form"] != 0, species
    zorua, = service.paste("pla", "Zorua\n", TRAINER)
    assert not zorua["errors"] and zorua["form"]


def test_a_wild_slot_level_range_does_not_make_a_request_fail_at_random(service):
    # Chingling's slots straddle level 50; one roll in ten landed above it and the build was refused.
    for _ in range(40):
        assert service.make("pla", 433, TRAINER, level=50)["level"] == 50


def test_a_tr_move_in_the_suggested_moveset_does_not_make_a_request_fail_at_random(service):
    # An egg Porygon2's suggested moves include TR moves; without their record flags half the builds failed.
    for _ in range(10):
        assert service.make("swsh", 233, TRAINER, shiny=True, level=50)["legal"]


@pytest.mark.parametrize("game, species, edit, message", [
    ("sv", 150, {"level": 50}, "cannot be lower than level"),  # a fixed-level encounter names its level
    ("sv", 377, {}, "no legal"),                               # an encounter PKHeX does not have
    ("swsh", 802, {"shiny": True}, "cannot be shiny"),         # every encounter is shiny-locked
])
def test_an_impossible_request_is_refused_with_its_reason(service, game, species, edit, message):
    with pytest.raises(pokemon.BuilderError, match=message):
        service.make(game, species, TRAINER, **edit)


def named(names, name):
    return next(n["id"] for n in names if n["name"] == name)


@pytest.mark.parametrize("game", ["swsh", "bdsp", "sv"])
def test_offer_options_land_in_the_record_the_launcher_sends(service, game):
    listed = service.options(game, 25, TRAINER)
    options = {"nature": 3, "ability": named(listed["abilities"], "Lightning Rod"), "gender": 1,
               "held_item": named(listed["held"], "Light Ball"), "ball": named(listed["balls"], "Ultra Ball"),
               "ivs": {"hp": 31, "atk": 0, "spe": 31}, "effort": {"hp": 252, "spe": 4}}
    built = service.make(game, 25, TRAINER, level=30, options=options)
    offer = Path(pokemon.prepare_file(game, built["file"])).read_bytes()
    if game == "sv":
        f = gen9.read(gen9.load(offer))
        nature, ball = f["stat_nature"], f["ball"]
    else:
        plain = gen8.load(offer)
        f = gen8.read(plain)
        nature, ball = plain[0x21], plain[gen8.OFF_BALL]    # G8PKM StatAlignment, the nature stats are read from
    # Record order is HP, Atk, Def, Spe, SpA, SpD.
    assert (nature, f["ability"], f["gender"], f["held_item"], ball) == (
        3, options["ability"], 1, options["held_item"], options["ball"])
    assert (f["ivs"][0], f["ivs"][1], f["ivs"][3]) == (31, 0, 31)
    assert f["evs"] == (252, 0, 0, 4, 0, 0)


@pytest.mark.parametrize("game, species, handled", [
    ("swsh", 447, 0),      # Riolu, evolved at friendship 160 on level-up
    ("sv", 447, 0),
    ("bdsp", 68, 1),       # Machamp, a trade evolution: the build gains a handler, whose friendship is its own
])
def test_friendship_lands_in_the_original_trainers_byte(service, game, species, handled):
    """A console keeps the original trainer's friendship when its player is that trainer (docs/architecture.md)."""
    built = service.make(game, species, TRAINER, options={"friendship": 222})
    offer = Path(pokemon.prepare_file(game, built["file"])).read_bytes()
    f = gen9.read(gen9.load(offer)) if game == "sv" else gen8.read(gen8.load(offer))
    assert built["legal"] and (f["current_handler"], f["ot_friendship"]) == (handled, 222)


@pytest.mark.parametrize("game", ["frlg", "lgpe", "pla", "za"])
def test_every_listed_ability_and_ball_builds_legal(service, game):
    listed = service.options(game, 25, TRAINER)
    for option in [{"ability": a["id"]} for a in listed["abilities"]] + [{"ball": b["id"]} for b in listed["balls"]]:
        assert service.make(game, 25, TRAINER, options=option)["legal"], option


def test_an_option_the_game_cannot_give_is_refused_not_dropped(service):
    lightning_rod = named(service.options("swsh", 25, TRAINER)["abilities"], "Lightning Rod")
    assert all(a["id"] != lightning_rod for a in service.options("lgpe", 25, TRAINER)["abilities"])
    with pytest.raises(pokemon.BuilderError, match="Ability"):
        service.make("lgpe", 25, TRAINER, options={"ability": lightning_rod})


def test_gen3_evs_past_the_vitamin_cap_build_at_the_level_met(service):
    # A Gen 3 EV above 100 is legal only once the Pokemon has gained experience since it was met.
    built = service.make("frlg", 203, TRAINER, options={"effort": {"hp": 252, "atk": 252, "spe": 4}})
    record = base64.b64decode(built["data"])
    assert built["legal"] and tuple(record[0x38:0x3E]) == (252, 252, 0, 4, 0, 0)   # PK3 EVs, decrypted, Spe fourth


def test_an_arceus_effort_level_is_stored_net_of_its_iv_bias(service):
    # The level the game shows is the stored value plus 3 at IV 31; storing 10 there is illegal.
    built = service.make("pla", 491, TRAINER, options={"ivs": {"hp": 31, "atk": 0}, "effort": {"hp": 10, "atk": 10}})
    f = pa8.read(pa8.load(base64.b64decode(built["data"])))
    assert built["legal"] and (f["ivs"][0], f["ivs"][1]) == (31, 0)
    assert f["gvs"][:2] == (7, 10)


@pytest.mark.parametrize("game", ["sv", "za", "bdsp", "pla", "lgpe", "frlg"])
def test_a_legal_sword_record_cannot_be_sent_to_another_game(service, game):
    data = base64.b64decode(service.make("swsh", 25, TRAINER)["data"])
    with pytest.raises(pokemon.BuilderError):
        service.prepare(game, data)


def test_corrupt_records_and_illegal_final_edits_are_refused(service):
    data = bytearray(base64.b64decode(service.make("swsh", 25, TRAINER)["data"]))
    data[6] ^= 1
    with pytest.raises(pokemon.BuilderError, match="checksum"):
        service.prepare("swsh", data)
    good = service.make("swsh", 25, TRAINER)
    with pytest.raises(pokemon.BuilderError, match="Unsupported edit"):
        service.prepare("swsh", base64.b64decode(good["data"]), fields={"imaginary": 1})


HOME_GIFTS = {9021, 9022, 9023, 9024, 9035}   # Scarlet/Violet's gifts HOME gave, at PKHeX.Core 26.8.26


def made_under(game, gifts, events, mode):
    """Each of `events` reads legal; the gifts HOME gave have the tracker `mode` gives them, the others none."""
    assert {e["card_id"] for e in events if e["home_tracker"]} == gifts
    assert all(e["legal"] and e["home_tracker"] == (mode if e["card_id"] in gifts else "") for e in events)


@pytest.mark.parametrize("mode", ["empty", "made"])
def test_every_scarlet_violet_mystery_gift_pokemon_is_made_for_a_trade(service, monkeypatch, mode):
    """Mystery Gift - Simulated (docs/gift_simulated.md): every Pokemon card PKHeX knows, newest first, made
    fresh for the app's trainer, passes the check the host runs on its offer, under a new PID where
    the card allows one. HOME's gifts get the HOME tracker the setting asks for (docs/gui.md, The HOME
    tracker setting): none under "empty", a made one under "made"."""
    monkeypatch.setattr(service, "home_tracker", mode)
    events = service.gift_events("sv", TRAINER)
    assert len(events) >= 100 and len({e["key"] for e in events}) == len(events)
    dates = [e["date"] for e in events if e["date"]]
    assert dates == sorted(dates, reverse=True)
    made_under("sv", HOME_GIFTS, events, mode)
    for event in events:
        built = service.gift_event("sv", event["key"], TRAINER)
        assert (built["legal"], built["home_tracker"]) == (True, event["home_tracker"]), event["title"]
        assert (built["tracker"] != "0") == (built["home_tracker"] == "made"), event["title"]
        assert built["species_id"] == event["species_id"]
        assert built["form_id"] == event["form_id"]
        offer = service.check_bytes("sv", Path(pokemon.prepare_file("sv", built["file"], fresh=True)).read_bytes())
        assert offer["legal"], event["title"]


OTHER_HOME_GIFTS = {"lgpe": set(), "bdsp": {9015, 9016, 9017, 9026}, "pla": {9018, 9019, 9020, 9027},
                    "za": {9031, 9032, 9033, 9034}}   # at PKHeX.Core 26.8.26
CHINESE_ONLY = {"1501-808-0", "1502-809-0"}     # Let's Go's Chinese Meltan and Melmetal, for the receiver's trainer


@pytest.mark.parametrize("mode", ["empty", "made"])
@pytest.mark.parametrize("game", OTHER_HOME_GIFTS)
def test_every_mystery_gift_pokemon_of_the_other_switch_games_is_made_for_a_trade(service, monkeypatch, game, mode):
    """Mystery Gift - Simulated on Let's Go, Brilliant Diamond/Shining Pearl, Legends Arceus and Legends Z-A
    (docs/gift_simulated.md): every gift an English save received is made and passes the host's offer check under
    a new PID, HOME's with the tracker the setting asks for. Let's Go's HOME Meltan keeps HOME's height and weight;
    Z-A's HOME starters get HOME's IVs."""
    monkeypatch.setattr(service, "home_tracker", mode)
    events = service.gift_events(game, TRAINER)
    assert len(events) >= 8 and len({e["key"] for e in events}) == len(events)
    assert {e["key"] for e in events if e["refused"]} == (CHINESE_ONLY if game == "lgpe" else set())
    events = [e for e in events if not e["refused"]]
    made_under(game, OTHER_HOME_GIFTS[game], events, mode)
    for event in events:
        built = service.gift_event(game, event["key"], TRAINER)
        assert (built["legal"], built["home_tracker"]) == (True, event["home_tracker"]), event["title"]
        offer = service.check_bytes(game, Path(pokemon.prepare_file(game, built["file"], fresh=True)).read_bytes())
        assert offer["legal"], event["title"]


def test_a_mystery_gift_pokemon_keeps_what_its_card_gave(service, monkeypatch):
    """The card's own trainer, moves and item, or the receiver's trainer where the card gave none; a
    card one version received alone comes out legal; a HOME gift gets the tracker the setting asks for."""
    events = {e["key"]: e for e in service.gift_events("sv", TRAINER)}
    palafin = events["0503-964-0-10"]
    assert (palafin["title"], palafin["ot"], palafin["held_item"], palafin["moves"]) == (
        "Gavin’s Palafin Gift", "Gavin", "Mystic Water", ["Jet Punch", "Wave Crash", "Haze", "Protect"])
    assert events["1501-25-0-2"]["ot"] == "" and events["1501-25-0-2"]["tera"] == "Flying"
    assert service.gift_event("sv", "1501-25-0-2", TRAINER)["ot"] == TRAINER["ot"]
    koraidon = service.gift_event("sv", "1540-1007-0-1", TRAINER)     # Violet's card
    assert koraidon["legal"] and koraidon["shiny"] and koraidon["ot"] == "Paldea"
    monkeypatch.setattr(service, "home_tracker", "empty")
    home = service.gift_event("sv", "9021-906-0-11", TRAINER)
    assert (home["legal"], home["home_tracker"], home["tracker"]) == (True, "empty", "0")
    monkeypatch.setattr(service, "home_tracker", "made")
    tracked = service.gift_event("sv", "9021-906-0-11", TRAINER)
    assert (tracked["legal"], tracked["home_tracker"]) == (True, "made") and tracked["tracker"] != "0"
    with pytest.raises(pokemon.BuilderError, match="no Mystery Gift Pokemon"):
        service.gift_event("sv", "9999-1-0-0", TRAINER)


def test_a_mystery_gift_pokemon_is_made_for_the_receiving_save(service):
    """Made for the receiving player (docs/gift_simulated.md): a card that gives the receiver's trainer says so, and
    with `version` the copy is made on that version alone, as that save receives it; a card that fixes its
    version keeps it, and one with its own trainer is never refused."""
    save = {"ot": "Nemona", "tid": 4660, "sid": 66, "language": 5, "gender": 1}

    def made(key, version):
        reply = service.gift_event("sv", key, save, version=version, keep=False)
        return reply, gen9.read(gen9.load(base64.b64decode(reply["data"])))
    pikachu, fields = made("1501-25-0-2", "VL")
    assert pikachu["your_ot"] and pikachu["legal"] and "file" not in pikachu
    assert (fields["ot_name"], fields["trainer_id"], fields["secret_id"], fields["language"], fields["ot_gender"],
            fields["version"]) == ("Nemona", 4660, 66, 5, 1, gen9.VERSION_VIOLET)
    assert made("1501-25-0-2", "SL")[1]["version"] == gen9.VERSION_SCARLET
    assert made("9021-906-0-11", "VL")[1]["version"] == gen9.VERSION_SCARLET      # HOME's Sprigatito
    assert not service.gift_event("sv", "0503-964-0-10", save, keep=False)["your_ot"]     # Gavin's Palafin
    # Violet's Koraidon, which no Scarlet save received, has the card's own trainer: a traded Pokemon either holds.
    for version in ("SL", "VL"):
        koraidon = service.gift_event("sv", "1540-1007-0-1", save, version=version, keep=False)
        assert (koraidon["refused"], koraidon["legal"], koraidon["ot"]) == ("", True, "Paldea")


def test_a_card_no_save_in_the_trainers_language_received_is_refused(service):
    """A card that gives the receiver's own trainer reached saves in the languages it was given in, which PKHeX's
    check knows: Let's Go's Chinese Meltan and Melmetal reached Simplified Chinese saves alone. Made for a trainer
    in another language the copy is refused, never kept, and listed as illegal with the reason; for a Simplified
    Chinese trainer it is made. Let's Go's Mew takes any language."""
    chinese = dict(TRAINER, language=9)
    for key in sorted(CHINESE_ONLY):
        refused = service.gift_event("lgpe", key, TRAINER)
        assert refused["your_ot"] and "file" not in refused
        assert refused["refused"] == f"card {key[:4]} gave it in Simplified Chinese alone, never to a save in English"
        made = service.gift_event("lgpe", key, chinese, keep=False)
        assert (made["refused"], made["legal"], made["ot"]) == ("", True, TRAINER["ot"])
    listed = {e["key"]: e for e in service.gift_events("lgpe", TRAINER)}
    assert (listed["1502-809-0"]["legal"], listed["1502-809-0"]["language"]) == (False, 9)
    assert listed["1502-809-0"]["refused"] == refused["refused"]
    assert (listed["2001-151-0"]["legal"], listed["2001-151-0"]["refused"]) == (True, "")
    assert service.gift_event("lgpe", "2001-151-0", dict(TRAINER, language=1), keep=False)["refused"] == ""


# A card that names its receiver, one that fixes its trainer, a save's version and the copy's, per game. HOME's
# Turtwig names Brilliant Diamond whichever the save is, as HOME's Sprigatito names Scarlet.
RECEIVER_GIFTS = {"lgpe": ("2001-151-0", "0002-150-0", "GE", 43), "bdsp": ("9015-387-0", "9026-490-0", "SP", 48),
                  "pla": ("9018-722-0", "9027-905-0", "PLA", 47), "sv": ("1501-25-0-2", "0503-964-0-10", "VL", 51),
                  "za": ("1601-280-0", "0101-531-0", "ZA", 52)}


@pytest.mark.parametrize("game", RECEIVER_GIFTS)
def test_a_host_makes_again_only_the_gifts_that_name_their_receiver(service, game):
    """--for-receiver (pokeldn.receiver_gift): the copy of a card that names its receiver is made again for the
    console's save on its version, through the checks the host's own offers take (its --fresh-pid, PKHeX's
    offer check, its loader), and PKHeX still finds it legal as the host sends it; one whose card fixes its
    trainer goes as made. The console's offer, in each host's own format, reads back as that save's."""
    import lgpe_host
    import za_host
    from pokeldn import receiver_gift
    from pokeldn.bdsp import pokemon as bdsp_pokemon
    from pokeldn.pla import pokemon as pla_pokemon
    from pokeldn.sv import trade
    load = {"lgpe": lgpe_host.boxed, "bdsp": bdsp_pokemon.build_from,       # the trade box ends on PKHeX's check
            "pla": lambda raw: pokemon.validate("pla", pla_pokemon.encrypt(pla_pokemon.load(raw))),
            "sv": trade.load_offer, "za": za_host.gift_offer}[game]
    yours, fixed, version, number = RECEIVER_GIFTS[game]
    assert receiver_gift.rounds(game, [yours, fixed], [b"yours", b"fixed"], log=lambda line: None) == [
        (yours, b"yours"), ("", b"fixed")]
    save = {"ot": "Nemona", "tid": 4660, "sid": 66, "language": 5, "gender": 1}
    body, what = receiver_gift.maker(game, load, fresh=True)(yours, save, version)
    assert service.check_bytes(game, body)["legal"]
    read = receiver_gift.owner_reader(game)
    f = read(body)
    assert (f["ot"], f["tid"], f["sid"], f["gender"], f["version"], f["egg"]) == ("Nemona", 4660, 66, 1, number, False)
    assert {"handler", "ht_name", "ht_gender", "ht_language"} <= set(f)
    assert " · level " in what
    try:                                    # an empty slot names no one, if it reads at all
        assert receiver_gift.unknown(game, read(bytes(len(body))))
    except ValueError:
        pass


@pytest.mark.parametrize("game", RECEIVER_GIFTS)
def test_a_gift_made_for_its_own_trainer_needs_no_handler(service, game):
    """A save that receives a Pokemon whose OT is its own clears the handler (docs/sv.md, What a trade rewrites):
    a card made for the receiving player must be legal without one. HOME's starters on Scarlet/Violet and
    Legends Z-A are legal only with a handler, so they go with the trainer from Settings."""
    save = {"ot": "Nemona", "tid": 4660, "sid": 66, "language": 2, "gender": 1}
    handled = []
    for event in service.gift_events(game, save):
        info = service.gift_event(game, event["key"], save, keep=False)
        if info["your_ot"] and not info["refused"]:
            assert service.owner(game, base64.b64decode(info["data"]))["handler"] == 0, event["key"]
        if info["handled"]:
            assert not info["your_ot"]
            handled.append(event["key"].split("-")[0])
    assert sorted(handled) == {"sv": ["9021", "9022", "9023"], "za": ["9031", "9032", "9033"]}.get(game, [])


def test_a_fixed_event_trainer_cannot_be_overwritten(service):
    built = service.make("swsh", 809, TRAINER)
    assert built["ot"] != TRAINER["ot"]
    with pytest.raises(pokemon.BuilderError):
        service.prepare("swsh", base64.b64decode(built["data"]), fields={"ot_name": "Changed"})


def test_full_pb7_import_is_saved_in_the_launchers_box_format(service, tmp_path):
    box = base64.b64decode(service.make("lgpe", 25, TRAINER)["data"])[:232]
    full = tmp_path / "full.pb7"
    full.write_bytes(box + bytes(260 - len(box)))
    imported = service.import_file("lgpe", str(full))
    assert imported["legal"]
    assert len(Path(imported["file"]).read_bytes()) == 260
    assert len(Path(pokemon.prepare_file("lgpe", imported["file"])).read_bytes()) == 232


def test_gifts_need_no_game_image_and_reject_unsafe_ids(service):
    good = wc8.pokemon_card(25, level=25)
    assert service.validate_gift(good)["valid"]
    # 3 is the game's random gender (main 0x010b62ac); 4 has no meaning
    assert service.validate_gift(wc8.pokemon_card(25, gender=3))["valid"]
    with pytest.raises(pokemon.BuilderError, match="gender"):
        service.validate_gift(wc8.pokemon_card(25, gender=4))
    with pytest.raises(pokemon.BuilderError, match="checksum"):
        service.validate_gift(bytes(720))
    for fields in ({"held_item": 65535}, {"move1": 65535}, {"species": 9999}):
        args = {"species": 25, **fields}
        with pytest.raises(pokemon.BuilderError):
            service.validate_gift(wc8.pokemon_card(**args))
    with pytest.raises(pokemon.BuilderError, match="species"):
        service.validate_gift(wc8.pokemon_card(1, form=255))


GARCHOMP = """Garchomp @ Choice Scarf
Ability: Rough Skin
Tera Type: Steel
EVs: 252 Atk / 4 SpD / 252 Spe
Jolly Nature
- Outrage
- Earthquake
- Stone Edge
- Spikes
"""
ROTOM = """Sparky (Rotom-Wash) (M) @ Leftovers
Ability: Levitate
Level: 50
Shiny: Yes
EVs: 252 HP / 252 SpA / 4 Spe
Modest Nature
IVs: 0 Atk
- Hydro Pump
- Volt Switch
- Will-O-Wisp
- Protect
"""
CHARIZARD = """Charizard @ Leftovers
Ability: Blaze
Timid Nature
- Flamethrower
- Fly
- Dragon Claw
"""
# PKHeX's own French and Japanese exports (ShowdownSet.GetText) of CHARIZARD and of part of GARCHOMP.
CHARIZARD_FR = """Dracaufeu @ Restes
Talent : Brasier
Nature : Timide
- Lance-Flammes
- Vol
- Draco-Griffe
"""
GARCHOMP_JA = """ガブリアス @ こだわりスカーフ
特性 さめはだ
努力値 252 攻撃 / 4 特防 / 252 素早さ
ようき性格
- げきりん
- じしん
"""


@pytest.mark.parametrize("game, text, expect", [
    ("sv", GARCHOMP, {"species": "Garchomp", "nature": "Jolly", "ability": "Rough Skin", "level": 100,
                      "held_item": "Choice Scarf", "moves": ["Outrage", "Earthquake", "Stone Edge", "Spikes"]}),
    ("swsh", ROTOM, {"species": "Rotom", "form": "Wash", "nickname": "Sparky", "shiny": True, "level": 50,
                     "nature": "Modest", "held_item": "Leftovers",
                     "moves": ["Hydro Pump", "Volt Switch", "Will-O-Wisp", "Protect"]}),
    ("frlg", CHARIZARD, {"species": "Charizard", "nature": "Timid", "held_item": "Leftovers",
                         "moves": ["Flamethrower", "Fly", "Dragon Claw"]}),
    ("frlg", CHARIZARD_FR, {"species": "Charizard", "nature": "Timid", "held_item": "Leftovers",
                            "moves": ["Flamethrower", "Fly", "Dragon Claw"]}),
    ("sv", GARCHOMP_JA, {"species": "Garchomp", "nature": "Jolly", "ability": "Rough Skin",
                         "held_item": "Choice Scarf", "moves": ["Outrage", "Earthquake"]}),
])
def test_a_showdown_set_builds_a_legal_pokemon_carrying_what_it_names(service, game, text, expect):
    found, = service.paste(game, text, TRAINER)
    assert found["errors"] == []
    built = service.make(game, found["species_id"], TRAINER, found["level"], found["shiny"], found["nickname"],
                         options=found["options"])
    assert built["legal"]
    for key, value in expect.items():
        assert built[key] == value, key


def test_a_paste_reads_stats_in_the_order_its_text_names_them(service):
    """PKHeX's parser holds Speed fourth; the text says 252 Spe and 4 SpD."""
    found, = service.paste("sv", GARCHOMP, TRAINER)
    assert found["options"]["effort"] == {"hp": 0, "atk": 252, "def": 0, "spe": 252, "spa": 0, "spd": 4}
    rotom, = service.paste("swsh", ROTOM, TRAINER)
    assert rotom["options"]["ivs"]["atk"] == 0 and rotom["options"]["ivs"]["spe"] == 31


@pytest.mark.parametrize("game, text, error", [
    ("frlg", GARCHOMP, "Garchomp is not in this game."),
    ("sv", "Pikachu\nAbility: Levitate", "Pikachu cannot have Levitate."),
    ("sv", "Pikachu\n- Thunderbolt\n- Flarp", "Move not recognized: Flarp"),
    ("sv", "hello\nfoo", "The first line names no Pokemon."),
])
def test_a_set_the_game_cannot_take_is_refused_with_the_reason(service, game, text, error):
    found = service.paste(game, text, TRAINER)[0]
    assert error in found["errors"]


@pytest.mark.parametrize("game, text, note", [
    ("sv", GARCHOMP, "Tera Type"),
    ("lgpe", "Pikachu\nEVs: 252 Spe\n- Thunderbolt", "no EVs"),
])
def test_a_value_the_builder_does_not_set_is_reported(service, game, text, note):
    found, = service.paste(game, text, TRAINER)
    assert any(note in n for n in found["notes"])
    assert "effort" not in found["options"] or game != "lgpe"


@pytest.mark.parametrize("game, text, friendship", [
    ("swsh", "Riolu\nFriendship: 255\n- Quick Attack", 255),
    ("swsh", "Riolu\nHappiness: 0", 0),
    ("swsh", CHARIZARD_FR + "Bonheur : 200", 200),
    ("bdsp", "Manaphy\nLevel: 1", None),     # an event whose friendship is fixed: Showdown's 255 would refuse it
])
def test_a_set_asks_for_friendship_only_by_naming_it(service, game, text, friendship):
    found, = service.paste(game, text, TRAINER)
    assert found["errors"] == [] and found["options"].get("friendship") == friendship
    assert service.make(game, found["species_id"], TRAINER, found["level"], options=found["options"])["legal"]


@pytest.mark.parametrize("game, text, ivs", [
    ("swsh", "Wooloo\nLevel: 12", None),   # Showdown's six 31s would allow only a raid or an egg
    ("swsh", CHARIZARD_FR + "IVs : 0 Atq", {"hp": 31, "atk": 0, "def": 31, "spe": 31, "spa": 31, "spd": 31}),
])
def test_a_set_asks_for_ivs_only_by_naming_them(service, game, text, ivs):
    found, = service.paste(game, text, TRAINER)
    assert found["errors"] == [] and found["options"].get("ivs") == ivs
    built = service.make(game, found["species_id"], TRAINER, found["level"], options=found["options"])
    assert built["legal"] and (ivs is not None or built["encounter"].startswith("Wild"))


def test_a_team_paste_returns_every_set_in_order(service):
    """Showdown's team export opens with a header line, and a paste may mix languages."""
    sets = service.paste("sv", "=== [gen9] Team ===\n\n" + GARCHOMP + "\n\n" + ROTOM + "\n" + GARCHOMP_JA, TRAINER)
    assert [s["species"] for s in sets] == ["Garchomp", "Rotom", "Garchomp"]
    assert all(s["errors"] == [] for s in sets)


def test_the_frlg_item_list_names_gen_3_ids(service):
    """The FRLG gift script carries the game's own item id [pokefirered include/constants/items.h]."""
    names = {n["id"]: n["name"] for n in service.names("frlg", "items")}
    assert (names[42], names[50], names[68], names[374]) == ("Black Flute", "Yellow Shard", "Rare Candy", "Sapphire")
    assert max(names) == 374


def test_the_sv_bag_holds_every_reward_a_raid_seed_gives(service):
    """A raid reward goes straight into the bag: the list a reward row is chosen from is the bag's
    pouches without key items and unreleased items, and holds everything the raid tables award."""
    from pokeldn.sv import raid_encounter
    bag = {n["id"] for n in service.names("sv", "bag")}
    tables = raid_encounter.tables()
    awarded = {e["item"] for rows in (*tables["fixed_rewards"].values(), *tables["lottery_rewards"].values())
               for e in rows if e["item"]}
    awarded |= {int(i) for i in tables["material_items"].values() if int(i)} | set(raid_encounter.TERA_SHARDS)
    assert awarded <= bag
    assert 16 not in bag and 1230 not in bag          # Cherish Ball and TM00, unreleased
    assert 1829 not in bag and 2405 not in bag        # key items of PKHeX's Event pouch


def test_a_hanging_parser_is_killed_and_the_next_check_recovers(tmp_path, monkeypatch):
    helper = tmp_path / 'parser.py'
    marker = tmp_path / 'first-request'
    helper.write_text('''import json, sys, threading
from pathlib import Path
marker = Path(sys.argv[1])
for line in sys.stdin:
    request = json.loads(line)
    if not marker.exists():
        marker.write_text('started')
        threading.Event().wait()
    print(json.dumps({'ok': True, 'legal': True, 'parsed': True, 'data': request['data']}), flush=True)
''', encoding='utf-8')
    monkeypatch.setattr(pokemon, '_command', lambda: [sys.executable, str(helper), str(marker)])
    monkeypatch.setattr(pokemon, 'CHECK_TIMEOUT', 0.5)
    from pokeldn.pla.trade_box import REFERENCE_RECORD
    instance = pokemon.Service()
    try:
        with pytest.raises(pokemon.BuilderError, match='took too long'):
            instance.check_bytes('pla', REFERENCE_RECORD)
        assert marker.exists() and instance.proc is None
        assert instance.prepare('pla', REFERENCE_RECORD) == REFERENCE_RECORD
    finally:
        instance.close()


@pytest.mark.parametrize("command,library", [
    # GitHub's macOS runner: Python itself lives in Python.framework, and a test's helper runs on it.
    (["/Users/runner/hostedtoolcache/Python/3.13.15/arm64/Python.framework/Versions/3.13/bin/python3"], False),
    (["/private/var/containers/Bundle/Application/X/pokeldn.app/Frameworks/pokeldn_pkhex.framework/pokeldn_pkhex"], True),
    (["/tmp/pkhex-osx/pokeldn-pkhex.dylib"], True),
    (["dotnet", "/tmp/pokeldn-pkhex.dll"], False),
])
def test_only_the_helper_built_as_a_library_runs_in_process(command, library):
    assert pokemon._library(command) is library
