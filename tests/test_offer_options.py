"""Offer options set in the app (species, level, shiny, nickname, nature, ability, gender, ball, held
item, moves, IVs, EVs) reach the console in the record the app built, in the BDSP and Scarlet host and
joiner entry points: the app's own argument list goes through the real launcher up to the point it
would put the record on the air. Needs the PKHeX service (dotnet), like tests/test_pokemon_service.py."""
import sys
from pathlib import Path

import pytest

from pokeldn import gen8, gen9, pokemon
from pokeldn.app.catalog import GAMES
from pokeldn.app.command import build
from pokeldn.app.settings import Settings
from pokeldn.bdsp import host as bdsp_host_lib, room
from pokeldn.ldn import reliable5 as rl
from tests.test_bdsp_host import HOST_VAR, _game_out, _joined
from tests.test_pokemon_service import service  # noqa: F401 - the fixture

OPTIONS = {"nature": 10, "ability": 31, "gender": 1, "ball": 11, "held_item": 236,
           "moves": [84, 85, 98, 86],
           "ivs": {"hp": 31, "atk": 0, "def": 17, "spa": 29, "spd": 3, "spe": 30},
           "effort": {"hp": 252, "atk": 0, "def": 4, "spa": 0, "spd": 0, "spe": 252}}
LEVEL, NICKNAME = 37, "TESTMON"
# The record stores its stats in PKHeX's order: HP, Attack, Defense, Speed, Sp. Atk, Sp. Def.
STORED = ("hp", "atk", "def", "spe", "spa", "spd")
TOOLS = {t.key: t for g in GAMES for t in g.tools}


@pytest.fixture
def settings(tmp_path):
    return Settings(ot="PkCamp", tid=41234, sid=12345, language=2, received=str(tmp_path / "Received"),
                    keys=str(tmp_path / "prod.keys"), capture=False)


def _made(service, game, settings, options=OPTIONS):
    info = service.make(game, 25, settings.trainer(), LEVEL, True, NICKNAME, "", options)
    assert info["legal"]
    return info


def _argv(key, settings, file):
    tool = TOOLS[key]
    field = next(f for f in tool.fields if f.kind == "pokemon")
    return build(tool, {field.key: {"file": file, "legal": True}}, {}, settings, stamp="t")


def _check_options(read, level_of):
    """What a console reads off the summary screen, from the sent record alone."""
    assert read["species"] == 25 and level_of(read) == LEVEL
    assert read["nickname"] == NICKNAME and read["is_nicknamed"]
    assert read["nature"] == OPTIONS["nature"] and read["ability"] == OPTIONS["ability"]
    assert read["gender"] == OPTIONS["gender"] and read["ball"] == OPTIONS["ball"]
    assert read["held_item"] == OPTIONS["held_item"]
    assert [m for m in read["moves"] if m] == OPTIONS["moves"]
    assert dict(zip(STORED, read["ivs"])) == OPTIONS["ivs"]
    assert dict(zip(STORED, read["evs"])) == OPTIONS["effort"]
    assert (read["trainer_id"], read["secret_id"], read["ot_name"]) == (41234, 12345, "PkCamp")


def _same_but_identity(sent, built, size):
    """The two plain records differ only in the encryption constant, checksum and PID that
    --fresh-pid draws; shiny state is kept."""
    differing = {i for i in range(size) if sent[i] != built[i]}
    assert differing <= {0, 1, 2, 3, 6, 7, 28, 29, 30, 31}


def _shiny(read):
    return (read["trainer_id"] ^ read["secret_id"] ^ (read["pid"] >> 16) ^ (read["pid"] & 0xFFFF)) < 16


def _bdsp_level(read):
    # Pikachu grows at the medium-fast rate: experience is the cube of the level.
    return max(n for n in range(1, 101) if n ** 3 <= read["experience"])


def test_bdsp_host_sends_the_record_the_app_built(service, settings, monkeypatch, tmp_path):
    import bdsp_host
    info = _made(service, "bdsp", settings)
    argv = _argv("bdsp-host", settings, info["file"])
    assert "--fresh-pid" in argv
    keys = tmp_path / "prod.keys"
    keys.write_bytes(b"")
    captured = []

    class Stop(Exception):
        pass

    def partner(offers, *a, **k):
        captured.extend(offers)
        raise Stop

    monkeypatch.setattr(bdsp_host, "needs_root", lambda: False)
    monkeypatch.setattr(bdsp_host, "find_ap_phy", lambda log=None: "wlan0")
    monkeypatch.setattr(bdsp_host, "TradePartner", partner)
    with pytest.raises(Stop):
        bdsp_host.main(argv)
    [offer] = captured
    # The console receives it as the game's own trade message.
    p = bdsp_host_lib.TradePartner(offer, complete=True)
    s, c = _joined(p)
    body = room.build_trade_poke(bytes([0x40]) * 328)
    msg = rl.build_header(0x07 | 0x08, 1, len(body), lowest_pending=1) + body
    [sent] = _game_out(c.send([(msg, rl.PROTOCOL, 0, 1, 2)], 1.0, dst_var=HOST_VAR))
    assert sent == room.build_trade_poke(offer)
    wire = sent[room.HEADER_SIZE:]
    plain = gen8.load(wire)
    read = gen8.read(plain)
    _check_options(read, _bdsp_level)
    assert _shiny(read)
    assert plain[0x21] == OPTIONS["nature"]   # the nature the summary screen shows
    assert service.check_bytes("bdsp", wire)["legal"]
    built = gen8.load(Path(info["file"]).read_bytes())
    _same_but_identity(plain[:gen8.SIZE_STORED], built[:gen8.SIZE_STORED], gen8.SIZE_STORED)
    assert read["pid"] != gen8.read(built)["pid"]


def test_bdsp_joiner_sends_the_record_the_app_built(service, settings, monkeypatch, tmp_path):
    import bdsp_connect
    info = _made(service, "bdsp", settings)
    argv = _argv("bdsp-join", settings, info["file"])
    seen = []
    monkeypatch.setattr(bdsp_connect, "needs_root", lambda: False)
    monkeypatch.setattr(bdsp_connect.trio, "run", lambda fn, args: seen.append(args))
    monkeypatch.setattr(sys, "argv", ["bdsp_connect.py", *argv])
    bdsp_connect.main()
    [path] = seen[0].trade_template
    wire = Path(path).read_bytes()
    plain = gen8.load(wire)
    _check_options(gen8.read(plain), _bdsp_level)
    assert service.check_bytes("bdsp", wire)["legal"]
    built = gen8.load(Path(info["file"]).read_bytes())
    _same_but_identity(plain, built, gen8.SIZE_STORED)


@pytest.mark.parametrize("key, entry", [("sv-host", "sv_host"), ("sv-join", "sv_join")])
def test_scarlet_entry_points_offer_the_record_the_app_built(service, settings, monkeypatch, tmp_path,
                                                            key, entry):
    module = __import__(entry)
    info = _made(service, "sv", settings)
    argv = _argv(key, settings, info["file"])
    assert "--fresh-pid" in argv
    dump = tmp_path / "offer.hex"
    argv = [a for n, a in enumerate(argv) if a != "--capture" and argv[n - 1] != "--capture"]
    argv += ["--ip-host" if key == "sv-host" else "--ip-join", "--offer-dump", str(dump)]
    monkeypatch.setattr(sys, "argv", [entry + ".py", *argv])
    assert module.main() in (0, None)
    body = bytes.fromhex(dump.read_text().strip())
    plain = gen9.from_wire(body)
    read = gen9.read(plain)
    _check_options(read, lambda r: r["level"])
    assert _shiny(read)
    assert service.check_bytes("sv", plain)["legal"]
    built = gen9.load(Path(info["file"]).read_bytes())
    _same_but_identity(plain, built, gen9.SIZE_PARTY)
    assert read["pid"] != gen9.read(built)["pid"]


@pytest.mark.parametrize("game", ["bdsp", "sv"])
def test_a_nickname_the_record_cannot_hold_is_refused_not_cut(service, settings, game):
    assert service.make(game, 25, settings.trainer(), 30, False, "A" * 12)["nickname"] == "A" * 12
    with pytest.raises(pokemon.BuilderError, match="at most 12 characters"):
        service.make(game, 25, settings.trainer(), 30, False, "A" * 13)


@pytest.mark.parametrize("game", ["bdsp", "sv"])
def test_moves_no_legal_pokemon_knows_together_are_refused_in_words(service, settings, game):
    with pytest.raises(pokemon.BuilderError, match="can know these moves together"):
        service.make(game, 25, settings.trainer(), 5, False, "", "", {"moves": [56, 57, 89, 15]})
