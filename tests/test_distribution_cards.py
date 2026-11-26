"""The JPAJ distribution eggs (docs/frlg_gift.md, Distribution cards), and the RAM script
checksum a save injection must write."""

import pytest

from pokeldn.frlg.gift import gift_registry, wonder_card_events as event
from pokeldn.frlg.gift.gift_composer import FRLG_RULES, compile_definition
from pokeldn.rse.constants import EMERALD_RULES
from pokeldn.frlg.save import save_inject
from test_gift_composer import ScriptVM

PARTY_INDEX_LAST = 7            # setmonmove's "the last party mon" [decomp:src/scrcmd.c:1773]


def test_the_ram_script_checksum_is_the_one_the_game_writes():
    """An emulated English FireRed stored 0xB2DC through InitRamScript for this exact script: the
    CRC runs over sizeof(RamScriptData) = 1000 bytes, padding included, not 999."""
    script = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-celebi", flag_id=1010).ram_script
    assert len(script) == 289
    assert save_inject.build_ram_script_struct(script)[1] == 0xB2DC


RULES = pytest.mark.parametrize("rules", [FRLG_RULES, EMERALD_RULES], ids=lambda r: r.game)
EGG_CARDS = [(event.WISH_EGG_GIFT, event.WISH_EGGS), (event.POKEPARK_EGG_GIFT, event.POKEPARK_EGGS),
             (event.PC_JAPAN_EGG_GIFT, event.PC_JAPAN_EGGS)]


@RULES
@pytest.mark.parametrize("gift, eggs, pick", [(g, e, i) for g, e in EGG_CARDS for i in range(len(e))])
def test_every_pick_gives_its_egg_with_the_official_moves_as_a_fateful_encounter(gift, eggs, pick, rules):
    party = 3
    vm = ScriptVM(compile_definition(gift, rules=rules).ram_script, party_size=party, random_values=[pick])
    vm.run()
    species, moves = eggs[pick]
    assert vm.random_limits == [len(eggs)]
    assert vm.eggs == [species]
    assert vm.moves == [(PARTY_INDEX_LAST, slot, move) for slot, move in enumerate(moves)]
    assert vm.fateful == [party] and vm.met_locations == [(party, 0xFF)]
    assert rules.flag_done in vm.flags


@RULES
@pytest.mark.parametrize("gift, eggs", EGG_CARDS)
def test_a_full_party_draws_nothing_and_leaves_the_card_to_retry(gift, eggs, rules):
    vm = ScriptVM(compile_definition(gift, rules=rules).ram_script, party_size=6)
    vm.run()
    assert vm.eggs == [] and vm.random_limits == []
    assert rules.flag_done not in vm.flags


@RULES
@pytest.mark.parametrize("gift, species, moves", [
    ("box-swablu", 358, (64, 45, 206)), ("box-zigzagoon", 288, (33, 45, 39, 245)),
    ("box-skitty", 315, (45, 33, 39, 6)), ("surf-pichu", 172, (84, 204, 57))])
def test_a_pokemon_box_egg_has_its_official_moves_as_a_fateful_encounter(gift, species, moves, rules):
    """The four Pokemon Box Ruby & Sapphire bonus eggs, moves as PKHeX's EncountersWC3 lists them."""
    party = 3
    vm = ScriptVM(compile_definition(event.gba_cards(rules)[gift], rules=rules).ram_script, party_size=party)
    vm.run()
    assert vm.eggs == [species]
    assert vm.moves == [(PARTY_INDEX_LAST, slot, move) for slot, move in enumerate(moves)]
    assert vm.fateful == [party] and vm.met_locations == [(party, 0xFF)]
    assert rules.flag_done in vm.flags


def test_every_shared_card_has_one_app_preset():
    """A card added to gba_cards without a preset would be offered by neither game's app."""
    from pokeldn.frlg.gift import builder
    assert sorted(p.key for p in builder.GBA_CARDS) == sorted(event.gba_cards())


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
    """Every event preset FireRed and Emerald share, made by PKHeX and given by `givepokemon`."""
    from pokeldn import pokemon
    from pokeldn.frlg.gift import builder
    from pokeldn.frlg.save.mon import decode_mon
    assert pokemon.SERVICE.check_bytes("frlg", event.WISHMKR_JIRACHI_PK3)["legal"]
    assert len(builder.EVENT_PRESETS) == 39
    for preset in builder.EVENT_PRESETS:
        name = preset.args[3]
        pk3, _summary = pokemon.SERVICE.event(name, 3)
        for game in ("frlg", "rse"):
            verdict = pokemon.SERVICE.check_bytes(game, pk3)
            assert verdict["legal"], f"{name} in {game}: {verdict.get('report')}"
        assert verdict["shiny"] == preset.shiny, name
        status, raw = _given(event.build_event_pokemon_gift(pk3, name=name))
        assert status == 2 and builder.national_species(decode_mon(raw)["species"]) == preset.species_id, name
    for name in ("MATTLE Ho-Oh", "DUKING Plusle", "XD Lugia"):
        for language in (1, 3):
            pk3, _ = pokemon.SERVICE.event(name, language)
            assert pokemon.SERVICE.check_bytes("frlg", pk3)["legal"], (name, language)


@RULES
def test_the_national_dex_card_enables_it_once_and_only_where_it_is_off(rules):
    script = compile_definition(event.national_dex_gift(rules), rules=rules).ram_script
    off = ScriptVM(script)
    off.run()
    assert rules.special_enable_national_dex in off.specials
    on = ScriptVM(script, flags={rules.flag_national_dex})
    on.run()
    assert rules.special_enable_national_dex not in on.specials


def test_the_rare_berries_card_gives_all_three_and_retries_a_full_pocket():
    script = compile_definition(event.RARE_BERRIES_GIFT).ram_script
    full = ScriptVM(script, bag_space=[True, False])
    full.run()
    assert full.items == [(event.ITEM_ENIGMA_BERRY, 1)] and FRLG_RULES.flag_done not in full.flags
    rest = ScriptVM(script, variables=full.vars, flags=full.flags)
    rest.run()
    assert rest.items == [(event.ITEM_LANSAT_BERRY, 1), (event.ITEM_STARF_BERRY, 1)]


@pytest.mark.parametrize("pick", range(len(event.STARTERS)))
def test_the_starter_egg_card_draws_one_of_nine_and_keeps_its_own_moves(pick):
    vm = ScriptVM(compile_definition(event.STARTER_EGG_GIFT).ram_script, random_values=[pick])
    vm.run()
    assert vm.random_limits == [9] and vm.eggs == [event.STARTERS[pick]] and vm.moves == []
