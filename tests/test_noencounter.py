"""The noencounter hook, and the flag it holds, checked against the cartridge's own code.

How it could fail. The hook skips the game's VBlankIntr or returns anywhere but where IntrMain
called it; the flag address is not the byte StandardWildEncounter tests, so encounters go on.
"""

import pathlib

import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import native_script as ns

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

VBLANK_INTR = 0x0800071C
FLAG = 0x020386D8
STANDARD_WILD_ENCOUNTER = 0x08086528
GET_HEADER_ID = 0x080861A0               # GetCurrentMapWildMonHeaderId, its first call
STOP = 0x02030000
ROM = pathlib.Path("scratchpad/FireRed_f.gba")


def test_every_frame_sets_the_flag_and_runs_the_game_handler_once():
    from unicorn import arm_const as a
    counter = 0x02030100
    stub = bytes.fromhex("024801680131016070470000") + counter.to_bytes(4, "little")
    machine = bs._Machine(bs.build_install_resident("noencounter"), memory={
        ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little"), VBLANK_INTR: stub})
    assert machine.call().param == VBLANK_INTR | 1
    uc = machine.uc
    for _ in range(2):
        uc.mem_write(FLAG, b"\x00")                     # the quest log's DisableWildEncounters(FALSE)
        uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        uc.reg_write(a.UC_ARM_REG_LR, STOP)
        uc.emu_start(int.from_bytes(uc.mem_read(ns.GINTRTABLE_VBLANK, 4), "little"), STOP,
                     count=1000)
        assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
        assert uc.mem_read(FLAG, 1)[0] == 1
    assert int.from_bytes(uc.mem_read(counter, 4), "little") == 2


@pytest.mark.parametrize("cartridge, encounter, header", [
    ("scratchpad/FireRed_f.gba", STANDARD_WILD_ENCOUNTER, GET_HEADER_ID),
    ("scratchpad/LeafGreen_f.gba", 0x080864FC, 0x08086174)])
@pytest.mark.parametrize("flag, reaches_header", [(1, False), (0, True)])
def test_the_cartridge_standardwildencounter_stops_on_this_flag(flag, reaches_header, cartridge,
                                                                encounter, header):
    """The real StandardWildEncounter, on either cartridge: with the byte at 1 it returns FALSE
    before looking at the map; at 0 it goes on to GetCurrentMapWildMonHeaderId."""
    rom = pathlib.Path(cartridge)
    if not rom.exists():
        pytest.skip("no cartridge image on this machine")
    from unicorn import UC_HOOK_CODE
    from unicorn import arm_const as a
    machine = bs._Machine(b"\x00" * 4, memory={0x08000000: rom.read_bytes(),
                                                FLAG: bytes([flag])})
    uc = machine.uc
    seen = []

    def reached(uc, address, size, user):
        seen.append(address)
        uc.emu_stop()                                   # past here it reads the save; enough

    uc.hook_add(UC_HOOK_CODE, reached, begin=header, end=header)
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
    uc.reg_write(a.UC_ARM_REG_R0, 0)
    uc.reg_write(a.UC_ARM_REG_R1, 0)
    uc.reg_write(a.UC_ARM_REG_CPSR, uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
    uc.emu_start(encounter | 1, STOP, count=40)
    assert bool(seen) == reaches_header
    if not reaches_header:
        assert uc.reg_read(a.UC_ARM_REG_PC) == STOP and uc.reg_read(a.UC_ARM_REG_R0) == 0
