"""The shared service validates the bytes every game adapter actually sends."""
import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from pokeldn import pokemon
from pokeldn.swsh import wc8

TRAINER = {"ot": "PkCamp", "tid": 12345, "sid": 54321, "language": 2, "gender": 0}
FORMATS = {"frlg": "PK3", "lgpe": "PB7", "swsh": "PK8", "bdsp": "PB8", "pla": "PA8", "sv": "PK9", "za": "PA9"}


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
    offer = pokemon.prepare_file(game, imported["file"])
    final = service.check_bytes(game, Path(offer).read_bytes())
    assert final["legal"] and final["ot"] == imported["ot"]


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
    ("swsh", 809, {}),                                   # an event that reached the game through HOME has a tracker
    ("za", 801, {}),                                     # a gift that arrives already handled
])
def test_a_shiny_level_or_evolved_request_is_built_legal(service, game, species, edit):
    built = service.make(game, species, TRAINER, **edit)
    assert built["legal"]
    assert built["shiny"] == edit.get("shiny", False)
    if "level" in edit:
        assert built["level"] == edit["level"]


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


def test_a_fixed_event_trainer_cannot_be_overwritten(service):
    built = service.make("swsh", 25, TRAINER)
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
    with pytest.raises(pokemon.BuilderError, match="checksum"):
        service.validate_gift(bytes(720))
    for fields in ({"held_item": 65535}, {"move1": 65535}, {"species": 9999}):
        args = {"species": 25, **fields}
        with pytest.raises(pokemon.BuilderError):
            service.validate_gift(wc8.pokemon_card(**args))
    with pytest.raises(pokemon.BuilderError, match="species"):
        service.validate_gift(wc8.pokemon_card(1, form=255))
