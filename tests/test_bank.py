"""The bank keeps what a trade brought in and sends it to another game the way HOME moves it."""
import base64
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


def receive(service, folder, game, species, options=None):
    """A record written where a launcher writes what it received, banked as the session panel banks it."""
    built = service.make(game, species, TRAINER, options=options)
    path = folder / f"{game}-{species}-received.{pokemon.EXTENSIONS[game]}"
    path.write_bytes(base64.b64decode(built["data"]))
    return bank.deposit(game, str(path), service.check(game, str(path))), built


@pytest.mark.parametrize("source, target", [
    ("frlg", "swsh"), ("lgpe", "sv"), ("swsh", "bdsp"), ("bdsp", "pla"), ("pla", "sv"), ("sv", "za"),
])
def test_a_moved_pokemon_keeps_who_it_is_and_its_launcher_takes_it(service, vault, source, target):
    entry, built = receive(service, vault, source, 25)
    item = bank.offer(entry, target, OWNER)
    offer = pokemon.prepare_file(target, item["file"], fresh=False)   # what the launcher sends
    moved = service.check_bytes(target, Path(offer).read_bytes())
    assert moved["legal"] and moved["species_id"] == 25 and item["bank"] == entry.id
    assert (moved["pid"], moved["encryption_constant"]) == (built["pid"], built["encryption_constant"])
    assert (moved["ot"], moved["trainer_id"]) == (built["ot"], built["trainer_id"])
    assert int(moved["tracker"]) == entry.tracker != 0


@pytest.mark.parametrize("source, target, why", [
    ("swsh", "lgpe", "Nothing goes back"),  # HOME sends nothing to Let's Go
    ("sv", "frlg", "Nothing goes back"),    # nor to a GBA game
    ("frlg", "sv", "held item"),            # HOME's FireRed/LeafGreen screen
    ("swsh", "pla", "absent"),              # Charizard is not in Legends Arceus
])
def test_a_move_home_would_refuse_is_refused_with_its_reason(service, vault, source, target, why):
    species, options = (6, None) if why == "absent" else (25, None)
    if why == "held item":
        options = {"held_item": 139}        # an Oran Berry
    entry, _ = receive(service, vault, source, species, options)
    routes = pokemon.SERVICE.destinations(entry.game, bank.data(entry), entry.tracker, OWNER)
    assert not routes[target]["ok"] and why in routes[target]["reason"]
    assert routes[source]["ok"]
    with pytest.raises(pokemon.BuilderError, match=why):
        bank.offer(entry, target, OWNER)


def test_a_fire_red_pokemon_that_knows_an_hm_stays_in_its_game(service, vault):
    entry, built = receive(service, vault, "frlg", 25, {"moves": [249]})     # Rock Smash
    assert "Rock Smash" in built["moves"]
    with pytest.raises(pokemon.BuilderError, match="HM move"):
        bank.offer(entry, "swsh", OWNER)


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
        restart=False, games=SimpleNamespace(values=values, visible=False),
        log=SimpleNamespace(add=lambda line: None), offering=SimpleNamespace(update=lambda: None))
    panel.render_offering = panel.refresh = panel.set_status = lambda *a, **k: None
    panel.banked = [e.get("bank", "") for e in panel.offered_entries()]
    assert bank.queued(settings, entry.id) == [tool.key]
    panel._line("[done] trade 1 complete")
    assert bank.find(entry.id) is not None
    panel._line("[done] trade 2 complete")
    assert bank.find(entry.id) is None
    panel._exited(0)
    assert values["--offer-file"] == [{"file": "built.pk8", "species": 1}]
