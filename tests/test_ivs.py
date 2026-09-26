"""The ivs hook, installed and run under unicorn.

How it could fail. The IVs unpacked in the wrong order or width; a two-digit BCD wrong at 10, 20 or
30; the nature taken from the wrong half of the personality; GetMonData called in a lag frame, where
the main loop may be inside the same Pokemon, or outside the overworld. With the cartridge on disk,
the real GetMonData runs on a Pokemon this project encrypted, and must leave it as it found it.
"""

import pathlib

import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import native_script as ns
from pokeldn.frlg.save import mevent_pokemon

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

VBLANK_INTR = 0x0800071C
GET_MON_DATA = 0x080432E4
INTR_CHECK = 0x030022EC
GMAIN = 0x030022D0
CB2_OVERWORLD = 0x08059EC9
PARTY = 0x02024280
WORDS = 0x0203FF80
STOP = 0x02030000
PACKED = 0x02030100
ROM = pathlib.Path("scratchpad/FireRed_f.gba")


def _packed(ivs):
    return sum((v & 31) << (5 * i) for i, v in enumerate(ivs))


def _rows(ivs, nature):
    hp, atk, de, spe, spa, spd = ivs
    return (int(f"{hp:02d}{atk:02d}{de:02d}{spe:02d}", 16),
            int(f"{spa:02d}{spd:02d}{nature:02d}00", 16))


def _run(memory, lag=False, cb2=CB2_OVERWORLD):
    from unicorn import arm_const as a
    memory = {ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little"),
              VBLANK_INTR: bytes.fromhex("70470000"),                       # bx lr
              INTR_CHECK: int(lag).to_bytes(2, "little"),
              GMAIN: (0).to_bytes(4, "little") + cb2.to_bytes(4, "little"), **memory}
    machine = bs._Machine(bs.build_install_resident("ivs"), memory=memory)
    machine.call()
    uc = machine.uc
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP)
    uc.emu_start(int.from_bytes(uc.mem_read(ns.GINTRTABLE_VBLANK, 4), "little"), STOP,
                 count=2_000_000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
    read = lambda at, n=4: int.from_bytes(uc.mem_read(at, n), "little")
    return uc, read


def _stub_memory(ivs, personality):
    stub = bytes.fromhex("0148006870470000") + PACKED.to_bytes(4, "little")   # return *PACKED
    return {GET_MON_DATA: stub, PACKED: _packed(ivs).to_bytes(4, "little"),
            PARTY: personality.to_bytes(4, "little")}


@pytest.mark.parametrize("ivs, personality", [
    ((31, 30, 20, 19, 10, 9), 0xA437A624),
    ((0, 1, 29, 31, 15, 5), 0x00000018),
])
def test_the_rows_are_the_ivs_in_game_order_and_the_nature(ivs, personality):
    _, read = _run(_stub_memory(ivs, personality))
    assert (read(WORDS), read(WORDS + 4)) == _rows(ivs, personality % 25)
    assert read(WORDS + 8) == 1


@pytest.mark.parametrize("lag, cb2", [(True, CB2_OVERWORLD), (False, 0x08011001)])
def test_no_read_in_a_lag_frame_or_outside_the_overworld(lag, cb2):
    _, read = _run(_stub_memory((31,) * 6, 5), lag=lag, cb2=cb2)
    assert (read(WORDS), read(WORDS + 8)) == (0, 0)


def test_the_cartridge_getmondata_reads_a_mon_this_project_encrypted_and_leaves_it_intact():
    if not ROM.exists():
        pytest.skip("no cartridge image on this machine")
    ivs = (31, 30, 20, 19, 10, 9)
    mon = mevent_pokemon.build_party_mon(25, 50, nickname="PIKA", ivs=ivs,
                                         personality=0xA437A624).raw
    rom = bytearray(ROM.read_bytes())
    at = VBLANK_INTR - 0x08000000
    rom[at:at + 4] = bytes.fromhex("70470000")          # VBlankIntr's sound needs a live mixer
    uc, read = _run({0x08000000: bytes(rom), PARTY: mon})
    assert (read(WORDS), read(WORDS + 4)) == _rows(ivs, 0xA437A624 % 25)
    assert bytes(uc.mem_read(PARTY, 100)) == mon
