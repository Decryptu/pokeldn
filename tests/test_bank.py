"""The bank keeps what a trade brought in and sends it to another game the way HOME moves it."""
import base64
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeldn import pokemon
from pokeldn.app import bank, command
from pokeldn.app.catalog import GAMES
from pokeldn.app.settings import Settings
from test_pokemon_service import TRAINER, service  # noqa: F401  (the PKHeX helper, built once)

OWNER = {"ot": "ASH", "tid": 1111, "sid": 2222, "language": 2, "gender": 0}
TOOLS = {tool.key: tool for game in GAMES for tool in game.tools}


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(bank, "BANK", tmp_path / "Bank")
    return tmp_path


# Built by PKHeX's encounter generator: a Black 2 save holding a Patrat with an Oran Berry in party slot 1, a
# Lillipup in box 1 slot 3 and a Patrat knowing Roar of Time in box 2 slot 1; a Bidoof that knows Rock Smash
# (.pk4) and a Fletchling holding an Oran Berry (.pk6).
FIXTURE = json.loads((Path(__file__).parent / "data" / "bank_import.json").read_text(encoding="utf-8"))
TRAINERS = {game: OWNER for game in pokemon.EXTENSIONS}


def receive(service, folder, game, species, options=None):
    """A record written where a launcher writes what it received, banked as the session panel banks it."""
    built = service.make(game, species, TRAINER, options=options)
    path = folder / f"{game}-{species}-received.{pokemon.EXTENSIONS[game]}"
    path.write_bytes(base64.b64decode(built["data"]))
    return bank.deposit(game, str(path), service.check(game, str(path))), built


@pytest.mark.parametrize("mode", ["empty", "made"])
@pytest.mark.parametrize("source, target", [
    ("frlg", "swsh"), ("lgpe", "sv"), ("swsh", "bdsp"), ("bdsp", "pla"), ("pla", "sv"), ("sv", "za"),
])
def test_a_moved_pokemon_keeps_who_it_is_and_its_launcher_takes_it(service, vault, monkeypatch, source, target,
                                                                    mode):
    monkeypatch.setattr(service, "home_tracker", mode)
    entry, built = receive(service, vault, source, 25)
    item = bank.offer(entry, target, OWNER)
    offer = pokemon.prepare_file(target, item["file"], fresh=False)   # what the launcher sends
    moved = service.check_bytes(target, Path(offer).read_bytes())
    assert moved["legal"] and moved["species_id"] == 25 and item["bank"] == entry.id
    pid = built["pid"]
    if source == "frlg" and 8 <= TRAINER["tid"] ^ TRAINER["sid"] ^ pid >> 16 ^ pid & 0xFFFF < 16:
        pid ^= 0x80000000     # HOME flips it so Gen 6's shiny threshold of 16 keeps it non-shiny
    assert (moved["pid"], moved["encryption_constant"]) == (pid, built["encryption_constant"])
    assert (moved["ot"], moved["trainer_id"]) == (built["ot"], built["trainer_id"])
    assert item["home_tracker"] == mode
    assert int(moved["tracker"]) == (entry.tracker if mode == "made" else 0) and entry.tracker != 0
    routes = bank.destinations(entry, OWNER)
    assert routes[target] == {"ok": True, "reason": "", "home_tracker": mode}


@pytest.mark.parametrize("source, target, why", [
    ("swsh", "lgpe", "HOME cannot send"),  # HOME sends nothing to Let's Go
    ("frlg", "lgpe", "HOME cannot send"),  # Let's Go's format is above FireRed's: the converter takes a PK3
    ("sv", "frlg", "HOME cannot send"),    # nor to a GBA game
    ("frlg", "sv", "held item"),             # HOME's FireRed/LeafGreen screen
    ("swsh", "pla", "Charizard is not in"),  # Charizard is not in Legends Arceus
])
def test_a_move_home_would_refuse_is_refused_with_its_reason(service, vault, source, target, why):
    species, options = (6, None) if why.startswith("Charizard") else (25, None)
    if why == "held item":
        options = {"held_item": 139}        # an Oran Berry
    entry, _ = receive(service, vault, source, species, options)
    routes = bank.destinations(entry, OWNER)
    assert not routes[target]["ok"] and why in routes[target]["reason"]
    assert routes[source]["ok"]
    with pytest.raises(pokemon.BuilderError, match=why):
        bank.offer(entry, target, OWNER)


def test_a_fire_red_pokemon_that_knows_an_hm_stays_in_its_game(service, vault):
    entry, built = receive(service, vault, "frlg", 25, {"moves": [249]})     # Rock Smash
    assert "Rock Smash" in built["moves"]
    with pytest.raises(pokemon.BuilderError, match="HM move"):
        bank.offer(entry, "swsh", OWNER)


def test_an_edit_is_kept_only_while_pkhex_finds_it_legal(service, vault):
    entry, _ = receive(service, vault, "frlg", 113)             # Chansey
    before = bank.data(entry)
    for fields, why in (({"moves": [221]}, "its moves is not legal"),     # Sacred Fire
                        ({"level": 1}, "never loses levels")):
        with pytest.raises(pokemon.BuilderError, match=why):
            bank.edit(entry, fields)
        assert bank.data(entry) == before
    edited = bank.edit(entry, {"nickname": "LUCKY", "level": 60, "moves": [135, 94]})   # Soft-Boiled, Psychic
    info = service.check_bytes("frlg", bank.data(edited))
    assert info["legal"] and edited.legal and edited.id == entry.id
    assert (info["nickname"], info["level"], info["moves"]) == ("LUCKY", 60, ["Soft-Boiled", "Psychic"])
    assert "'LUCKY'" in edited.summary and bank.offer(edited, "swsh", OWNER)["legal"]


def test_a_file_read_again_is_banked_once(service, vault):
    entry, _ = receive(service, vault, "swsh", 133)
    path = vault / "swsh-133-received.pk8"
    assert bank.deposit("swsh", str(path), service.check("swsh", str(path))) is None
    assert [e.id for e in bank.entries()] == [entry.id] and entry.game == "swsh" and entry.legal


def banked_queue(settings, entry_id):
    return [{"file": "built.pk8", "species": 1}, {"file": "banked.pk8", "species": 25, "bank": entry_id}]


def test_a_banked_offer_keeps_its_pid_and_the_launcher_still_parses_the_line(tmp_path):
    from pokeldn.app.introspect import parser_of
    tool = TOOLS["swsh-host"]
    settings = Settings(keys=str(tmp_path / "prod.keys"), received=str(tmp_path))
    built = command.build(tool, {"--offer-file": [{"file": "built.pk8"}]}, {}, settings)
    banked = command.build(tool, {"--offer-file": banked_queue(settings, "X")}, {"--fresh-pid": True}, settings)
    assert "--fresh-pid" in built and "--fresh-pid" not in banked
    parser_of(tool.script).parse_args(banked)


def test_a_completed_trade_takes_the_pokemon_out_of_the_bank_and_its_queue(vault, monkeypatch):
    """Trade 1 is a built offer, trade 2 the banked one: only trade 2's completion empties the bank, and
    the queue keeps the built offer for the next run."""
    pytest.importorskip("flet")
    from gui.views import games
    source = vault / "received.pk8"
    source.write_bytes(b"record")
    entry = bank.deposit("swsh", str(source), {"species": "Pikachu", "species_id": 25, "level": 5, "legal": True})
    tool = TOOLS["swsh-host"]
    settings = Settings(keys="", received=str(vault))
    settings.save = lambda: None
    values = settings.tool_values.setdefault(tool.key, {"values": {}, "extra": {}})["values"]
    values["--offer-file"] = banked_queue(settings, entry.id)
    panel = games.SessionPanel.__new__(games.SessionPanel)
    panel.__dict__.update(
        app=SimpleNamespace(settings=settings, ui=lambda fn: fn()), tool=tool, traded=0, stopping=False,
        restart=False, games=SimpleNamespace(values=values, visible=False, show_run_cards=lambda: None),
        log=SimpleNamespace(add=lambda line: None), offering=SimpleNamespace(update=lambda: None),
        partner_state=None)
    panel.render_offering = panel.refresh = panel.set_status = lambda *a, **k: None
    panel.bank_trades = bank.TradeSession(panel.offered_entries())
    assert bank.queued(settings, entry.id) == [tool.key]
    panel._line("[done] trade 1 complete")
    assert bank.find(entry.id) is not None
    panel._line("[done] trade 2 complete")
    assert bank.find(entry.id) is None
    panel._exited(0)
    assert values["--offer-file"] == [{"file": "built.pk8", "species": 1}]
    pending = []
    panel.app.ui = pending.append
    panel._line("[done] trade 3 complete")
    next_entry = bank.deposit("swsh", str(source),
                              {"species": "Pikachu", "species_id": 25, "level": 5, "legal": True})
    panel.bank_trades = bank.TradeSession([{"bank": next_entry.id}])
    panel.traded = 0
    for callback in pending:
        callback()
    assert panel.traded == 0 and bank.find(next_entry.id) is not None


def imported_from(entry):
    return json.loads(Path(entry.path).with_suffix(".json").read_text(encoding="utf-8"))["imported"]["where"]


def test_a_save_is_imported_slot_by_slot_once_even_after_a_trade_takes_one_out(service, vault, monkeypatch):
    monkeypatch.setattr(service, "home_tracker", "made")
    save = vault / "main"          # a 3DS save has no extension; this one is Black 2's size
    save.write_bytes(gzip.decompress(base64.b64decode(FIXTURE["black2_save_gz"])))
    before = save.read_bytes()
    first = bank.import_file(str(save), TRAINERS)
    assert first.save == "Black 2, ROSA"
    assert [(p.where, p.species, p.state, p.detail) for p in first.pokemon] == [
        ("Party, slot 1", "Patrat", "banked", "Left its Oran Berry behind · Can't be deposited in HOME"),
        ("Box 1, slot 3", "Lillipup", "banked", "Can't be deposited in HOME"),
        ("Box 2, slot 1", "Patrat", "refused", "One of its moves is not legal.")]
    kept = {imported_from(e): e for e in bank.entries()}
    assert {e.home_tracker for e in kept.values()} == {"made"}
    patrat = service.check_bytes(kept["Party, slot 1"].game, bank.data(kept["Party, slot 1"]))
    assert patrat["legal"] and patrat["species_id"] == 504 and patrat["held_item_id"] == 0
    assert patrat["ot"] == "ROSA" and int(patrat["tracker"]) != 0
    bank.remove(kept["Party, slot 1"].id)       # as a completed trade takes it out
    again = bank.import_file(str(save), TRAINERS)
    assert [p.state for p in again.pokemon] == ["already", "already", "refused"]
    assert len(bank.entries()) == 1 and save.read_bytes() == before


def test_the_empty_setting_accepts_what_a_tracker_would_make_legal(service, vault):
    """PKHeX takes the party Patrat's Hidden Ability in Legends Z-A only with a tracker
    [AbilityVerifier.VerifyBirthAbility]; the Box 2 Patrat's move is illegal with one too."""
    save = vault / "main"
    save.write_bytes(gzip.decompress(base64.b64decode(FIXTURE["black2_save_gz"])))
    assert [(p.state, p.detail) for p in bank.import_file(str(save), TRAINERS).pokemon] == [
        ("banked", "Left its Oran Berry behind · PKHeX flags the missing HOME tracker"),
        ("banked", "PKHeX flags the missing HOME tracker"),
        ("refused", "One of its moves is not legal.")]
    for entry in bank.entries():
        info = service.check_bytes(entry.game, bank.data(entry))
        assert info["legal"] and info["tracker"] == "0" and entry.home_tracker == "empty"


@pytest.mark.parametrize("species, edit", [
    (25, {"level": 50, "options": {"moves": [344]}}),   # Pikachu hatched as Pichu: Volt Tackle comes only from an egg
    (134, {"level": 1, "options": {"gender": 1}}),      # Vaporeon hatched as Eevee: the other level 1 one is Penny's male
])
def test_a_pokemon_that_evolved_in_scarlet_moves_to_every_home_game_holding_it(service, species, edit):
    """Without a tracker PKHeX lets no evolution happen in another HOME game [EvolutionGroupHOME.CheckAllAdjacent]."""
    built = service.make("sv", species, TRAINER, **edit)
    assert built["encounter"] == "Egg"
    routes = service.destinations("sv", base64.b64decode(built["data"]), "0", TRAINER)
    assert {game for game, route in routes.items() if route["ok"]} == {"sv", "swsh", "bdsp", "pla", "za"}
    assert {route["home_tracker"] for game, route in routes.items() if route["ok"] and game != "sv"} == {"empty"}


@pytest.mark.parametrize("name, species, gone", [
    ("bidoof.pk4", 399, "Forgot Rock Smash"),                        # Poke Transfer refuses an HM
    ("fletchling.pk6", 661, "Left its Oran Berry behind"),
])
def test_a_record_of_an_older_game_moves_in_as_home_would_take_it(service, vault, name, species, gone):
    path = vault / name
    path.write_bytes(bytes.fromhex(FIXTURE[name.split(".")[1]]))
    [found] = bank.import_file(str(path), TRAINERS).pokemon
    assert found.state == "banked" and found.detail.startswith(gone)
    [entry] = bank.entries()
    info = service.check_bytes(entry.game, bank.data(entry))
    assert info["legal"] and info["species_id"] == species and info["held_item_id"] == 0
    assert "Rock Smash" not in info["moves"] and entry.game == found.game
    assert [p.state for p in bank.import_file(str(path), TRAINERS).pokemon] == ["already"]


def test_a_record_of_a_game_the_bank_holds_is_kept_byte_for_byte(service, vault):
    built = service.make("swsh", 25, TRAINER, options={"held_item": 1})        # a Master Ball
    path = vault / "pikachu.pk8"
    path.write_bytes(base64.b64decode(built["data"]))
    [found] = bank.import_file(str(path), TRAINERS).pokemon
    [entry] = bank.entries()
    assert found.state == "banked" and found.detail == "" and entry.game == "swsh"
    assert bank.data(entry) == path.read_bytes()
    assert bank.deposit("swsh", str(path), service.check("swsh", str(path))) is None


def test_a_file_pkhex_cannot_read_is_refused(service, vault):
    path = vault / "notes.pk6"
    path.write_bytes(b"not a pokemon")
    with pytest.raises(pokemon.BuilderError, match="neither a Pokemon nor a game save"):
        bank.import_file(str(path), TRAINERS)


def test_an_external_frontend_imports_converts_and_completes_without_the_gui(service, tmp_path):
    from pokeldn.app.received import trades_done
    folder = tmp_path / "external-bank"
    source = tmp_path / "fletchling.pk6"
    original = bytes.fromhex(FIXTURE["pk6"])
    source.write_bytes(original)
    result = bank.import_file(str(source), TRAINERS, folder=folder)
    assert result.count("banked") == 1
    [entry] = bank.entries(folder=folder)
    assert bank.find(entry.id, folder=folder) == entry
    assert bank.destinations(entry, OWNER)["swsh"]["ok"]
    offer = bank.offer(entry, "swsh", OWNER)
    sent = service.check("swsh", offer["file"])
    assert sent["legal"] and sent["species_id"] == 661
    queue = [{"file": "built.pk8"}, offer]
    session = bank.TradeSession(queue, folder=folder)
    queue.clear()                       # the frontend can change its queue after starting a run
    assert session.completed == 0 and bank.find(entry.id, folder=folder)
    assert trades_done("[app] Exited with code 0.") is None
    session.advance(trades_done("[done] trade 1 complete"))
    assert bank.find(entry.id, folder=folder)  # a built offer completed; the Bank offer is still pending
    for count in (-1, True, 1.5):
        with pytest.raises(ValueError):
            session.advance(count)
    session.advance(trades_done("[done] trade 2 complete"))
    assert bank.entries(folder=folder) == []
    for count in (2, 1, 3):
        session.advance(count)          # duplicates, older messages and generated extra trades
    assert session.completed == 3
    assert bank.import_file(str(source), TRAINERS, folder=folder).count("already") == 1
    assert source.read_bytes() == original and Path(offer["file"]).is_file()


def test_a_completion_can_retry_after_one_record_cannot_be_removed(tmp_path, monkeypatch):
    for name in ("first", "second", "unoffered"):
        (tmp_path / f"{name}.pk8").write_bytes(b"record")
        (tmp_path / f"{name}.json").write_text("{}")
    session = bank.TradeSession([{"bank": "first"}, {"bank": "second"}], folder=tmp_path)
    unlink = Path.unlink

    def fail(path, *args, **kwargs):
        if path.name == "second.pk8":
            raise PermissionError("locked record")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail)
        with pytest.raises(PermissionError, match="locked record"):
            session.advance(2)
    assert session.completed == 1
    assert not (tmp_path / "first.pk8").exists() and (tmp_path / "second.pk8").exists()
    session.advance(2)
    assert session.completed == 2
    assert {p.name for p in tmp_path.iterdir()} == {"unoffered.pk8", "unoffered.json"}


def test_removal_uses_an_exact_id_and_preserves_unrelated_files(tmp_path):
    for name in ("pokemon.pk8", "pokemon.json", "pokemon.txt", "other.pk8", "other.json"):
        (tmp_path / name).write_bytes(b"record")
    before = {p.name for p in tmp_path.iterdir()}
    for entry_id in ("*", "../pokemon", "[po]*"):
        bank.remove(entry_id, folder=tmp_path)
        assert {p.name for p in tmp_path.iterdir()} == before
    bank.remove("pokemon", folder=tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {"pokemon.txt", "other.pk8", "other.json"}
