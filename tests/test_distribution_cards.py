"""The JPAJ distribution eggs (docs/frlg_gift.md, Distribution cards), and the RAM script
checksum a save injection must write."""

import pytest

from pokeldn.frlg.gift import gift_registry, wonder_card_events as event
from pokeldn.frlg.gift.gift_composer import FLAG_MYSTERY_GIFT_DONE, compile_definition
from pokeldn.frlg.save import save_inject
from test_gift_composer import ScriptVM

PARTY_INDEX_LAST = 7            # setmonmove's "the last party mon" [decomp:src/scrcmd.c:1773]


def test_the_ram_script_checksum_is_the_one_the_game_writes():
    """An emulated English FireRed stored 0xB2DC through InitRamScript for this exact script: the
    CRC runs over sizeof(RamScriptData) = 1000 bytes, padding included, not 999."""
    script = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-celebi", flag_id=1010).ram_script
    assert len(script) == 289
    assert save_inject.build_ram_script_struct(script)[1] == 0xB2DC


EGG_CARDS = [(event.WISH_EGG_GIFT, event.WISH_EGGS), (event.POKEPARK_EGG_GIFT, event.POKEPARK_EGGS),
             (event.PC_JAPAN_EGG_GIFT, event.PC_JAPAN_EGGS)]


@pytest.mark.parametrize("gift, eggs, pick", [(g, e, i) for g, e in EGG_CARDS for i in range(len(e))])
def test_every_pick_gives_its_egg_with_the_official_moves_as_a_fateful_encounter(gift, eggs, pick):
    party = 3
    vm = ScriptVM(compile_definition(gift).ram_script, party_size=party, random_values=[pick])
    vm.run()
    species, moves = eggs[pick]
    assert vm.random_limits == [len(eggs)]
    assert vm.eggs == [species]
    assert vm.moves == [(PARTY_INDEX_LAST, slot, move) for slot, move in enumerate(moves)]
    assert vm.fateful == [party] and vm.met_locations == [(party, 0xFF)]
    assert FLAG_MYSTERY_GIFT_DONE in vm.flags


@pytest.mark.parametrize("gift, eggs", EGG_CARDS)
def test_a_full_party_draws_nothing_and_leaves_the_card_to_retry(gift, eggs):
    vm = ScriptVM(compile_definition(gift).ram_script, party_size=6)
    vm.run()
    assert vm.eggs == [] and vm.random_limits == []
    assert FLAG_MYSTERY_GIFT_DONE not in vm.flags


def _pkhex_available():
    from pokeldn import pokemon
    try:
        pokemon._command()
    except pokemon.BuilderError:
        return False
    return True


def _given(definition):
    """-> (Mystery Event status, the 100-byte party record `givepokemon` copies) on a 3-mon party."""
    from pokeldn.frlg.rom import mystery_event
    script = compile_definition(definition).mevent
    [(_op, name, (pointer,)), _end] = mystery_event.decode(script)
    assert name == "givepokemon"
    return mystery_event.run(script, party_count=3).status, script[pointer:pointer + 100]


def test_the_event_card_gives_the_record_with_its_pid_ivs_and_trainer():
    from pokeldn.frlg.save.mon import Mon, decode_mon
    status, raw = _given(event.EVENT_POKEMON_GIFT)
    assert status == 2                                   # givepokemon's success
    assert raw[85] == 0xFF                               # MAIL_NONE: GiveMailToMon2 sets it
    sent, stored = decode_mon(raw), decode_mon(Mon.from_pk3(event.WISHMKR_JIRACHI_PK3).party_bytes())
    assert sent == stored
    assert (sent["species_name"], sent["otName"], sent["otid"] & 0xFFFF) == ("JIRACHI", "WISHMKR", 20043)


@pytest.mark.skipif(not _pkhex_available(), reason="needs services/pkhex built")
def test_the_stored_jirachi_and_every_preset_event_are_legal_distributions():
    from pokeldn import pokemon
    from pokeldn.frlg.gift import builder
    from pokeldn.frlg.save.mon import decode_mon
    assert pokemon.SERVICE.check_bytes("frlg", event.WISHMKR_JIRACHI_PK3)["legal"]
    names = [p.args[3] for p in builder.PRESETS if "--event-pokemon" in p.args]
    assert len(names) == 28
    for name in names:
        pk3, _summary = pokemon.SERVICE.event(name, 3)
        assert pokemon.SERVICE.check_bytes("frlg", pk3)["legal"], name
        status, raw = _given(event.build_event_pokemon_gift(pk3, name=name))
        assert status == 2 and decode_mon(raw)["otName"] == name.rsplit(" ", 1)[0], name
