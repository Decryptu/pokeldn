"""The GB-Link Team cards [pokeldn/frlg/gift/team_cards.py]: the French addresses they were built with
against the ones builds.py measured on its own, and each payload against the cartridge it names."""

import importlib.util
import json
import pathlib
import shutil

import pytest

from pokeldn.frlg.gift import team_cards
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
from pokeldn.frlg.rom import buffer_script as bs, builds

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


@pytest.mark.skipif(not bs.emulation_available(),
                    reason="needs unicorn")
def test_spanish_speed_four_installs_and_toggles_its_own_callbacks():
    """The shipped card's trampoline installs its handler; R toggles three extra callback pairs
    and four text runs per frame on the Spanish ROM [vendor/gblink-cards/speed.s]."""
    from unicorn import UC_HOOK_CODE, arm_const as a
    from tests.test_frlg_english_cartridges import BIOS_SIZE, STOP, _console, _image, _word
    build = builds.BPRS
    script = GIFT_REGISTRY.build_distribution("speed-4", build=build).ram_script
    machine = _console(b"\x00" * 4, build, _image("scratchpad/frlg_es/FireRed_s.gba"))
    uc = machine.uc
    uc.mem_map(0, BIOS_SIZE)
    script_at, context = 0x02038000, 0x03000FB0
    uc.mem_write(script_at, script)
    at = 43                         # setvaddress, lock, faceplayer, three header checks
    while script[at] == 0x0F:        # loadword -> ScriptContext.data[index]
        uc.mem_write(context + 0x64 + 4 * script[at + 1], script[at + 2:at + 6])
        at += 6
    assert script[at] == 0x23        # callnative -> the loaded trampoline
    target = int.from_bytes(script[at + 1:at + 5], "little")
    uc.reg_write(a.UC_ARM_REG_R2, script_at + at + 3)
    uc.reg_write(a.UC_ARM_REG_R3, context)
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
    uc.emu_start(target, STOP, count=100_000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
    assert _word(machine, build.intr_vblank) == 0x0203FC01
    assert _word(machine, 0x0203FBFC) == build.vblank_intr | 1

    entered = []
    callbacks = (build.cb1_overworld, build.cb2_overworld, build.run_text_printers)
    for function in callbacks:
        uc.mem_write(function, b"\x70\x47")       # bx lr, record each callback dispatch
    uc.hook_add(UC_HOOK_CODE, lambda _uc, address, _size, _user: entered.append(address)
                if address in (*callbacks, build.vblank_intr) else None)
    uc.mem_write(build.gmain, (build.cb1_overworld | 1).to_bytes(4, "little")
                 + (build.cb2_overworld | 1).to_bytes(4, "little"))
    for keys, pairs, text in [(0x02FF, 3, 4), (0x03FF, 3, 4), (0x02FF, 0, 0)]:
        entered.clear()
        uc.mem_write(0x04000130, keys.to_bytes(2, "little"))
        uc.mem_write(build.intr_check, b"\x00\x00")
        uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
        uc.emu_start(_word(machine, build.intr_vblank), STOP, count=1_000_000)
        assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
        assert [entered.count(f) for f in callbacks] == [pairs, pairs, text]
        assert entered.count(build.vblank_intr) == 1
