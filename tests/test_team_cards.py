"""The GB-Link Team cards [pokeldn/frlg/gift/team_cards.py]: the French addresses they were built with
against the ones builds.py measured on its own, and each payload against the cartridge it names."""

import importlib.util
import json
import pathlib
import shutil

import pytest

from pokeldn.frlg.gift import team_cards
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
from pokeldn.frlg.rom import builds

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("gen_team_cards", ROOT / "scripts/gen_team_cards.py")
gen_team_cards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_team_cards)
SYMBOLS = json.loads((pathlib.Path(__file__).resolve().parents[1] / "vendor/gblink-cards/symbols.json").read_text())

# card symbol -> what builds.py holds for it (functions without the Thumb bit)
SAME = {
    "MAIN": lambda b: b.gmain, "INTR_VBLANK": lambda b: b.intr_vblank, "SB1_PTR": lambda b: b.sb1ptr,
    "SB2_PTR": lambda b: b.sb2ptr, "SELECTED_OBJECT": lambda b: b.selected_object,
    "VBLANK_INTR": lambda b: b.vblank_intr, "RUN_TEXT_PRINTERS": lambda b: b.run_text_printers,
    "CB1_OVERWORLD": lambda b: b.cb1_overworld, "CB2_OVERWORLD": lambda b: b.cb2_overworld,
    "BATTLE_CB1": lambda b: b.battle_cb1, "BATTLE_CB2": lambda b: b.battle_cb2,
    "GET_MON_DATA": lambda b: b.get_mon_data, "CREATE_MON": lambda b: b.create_mon,
    "RANDOM": lambda b: b.random, "SETUP_SCRIPT": lambda b: b.setup_script,
    "SPAWN_OBJECT": lambda b: b.spawn_object, "SET_HELD_MOVEMENT": lambda b: b.set_held_movement,
    "CLEAR_HELD_MOVEMENT": lambda b: b.clear_held_movement, "MOVE_OBJECT_TO": lambda b: b.move_object_to,
    "REMOVE_OBJECT": lambda b: b.remove_object,
    "FLAG_GET": lambda b: b.callable["FlagGet"], "FLAG_CLEAR": lambda b: b.callable["FlagClear"],
    "ADD_BAG_ITEM": lambda b: b.callable["AddBagItem"],
    "SPECIES_TO_NATIONAL": lambda b: b.callable["SpeciesToNationalPokedexNum"],
    "GET_SET_POKEDEX_FLAG": lambda b: b.callable["GetSetPokedexFlag"],
}


@pytest.mark.parametrize("code", builds.GAME_CODES)
def test_the_card_addresses_match_the_ones_measured_for_each_cartridge(code):
    build, symbols = builds.BUILDS[code], SYMBOLS[code]["symbols"]
    for name, field in SAME.items():
        assert symbols[name] & ~1 == field(build), name


@pytest.mark.parametrize("code", builds.GAME_CODES)
def test_every_card_checks_the_header_of_the_cartridge_it_was_built_for(code):
    letter, language = code[2], code[3]
    for card in team_cards.cards().values():
        script = GIFT_REGISTRY.build_distribution(card.slug, build=code).ram_script
        assert len(script) <= 995
        # setvaddress, lock, faceplayer, then compare_addr_to_value on the game letter and the language
        assert script[7:13] == bytes([0x1F, 0xAE, 0, 0, 8, ord(letter)]), card.slug
        assert script[19:25] == bytes([0x1F, 0xAF, 0, 0, 8, ord(language)]), card.slug


def test_a_requested_flag_id_lands_on_the_card_and_nowhere_else():
    plain = GIFT_REGISTRY.build_distribution("nature-mint")
    flagged = GIFT_REGISTRY.build_distribution("nature-mint", flag_id=1017)
    assert flagged.card[:2] == (1017).to_bytes(2, "little") and flagged.card[4:8] == (17).to_bytes(4, "little")
    assert flagged.card[2:4] == plain.card[2:4] and flagged.card[8:] == plain.card[8:]
    assert flagged.ram_script == plain.ram_script


@pytest.mark.skipif(shutil.which("arm-none-eabi-as") is None, reason="needs the GNU Arm binutils")
@pytest.mark.parametrize("slug", ["nature-mint", "pc-anywhere", "no-encounters", "speed-0-5"])
def test_the_shipped_payloads_are_what_the_vendored_sources_build(slug, tmp_path):
    card_def = next(c for c in gen_team_cards.CARDS if c["id"] == team_cards.PREFIX + slug)
    for code in builds.GAME_CODES:
        assert gen_team_cards.build_script(card_def, code, tmp_path) == team_cards.cards()[slug].scripts[code]
