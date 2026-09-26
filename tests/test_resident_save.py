"""A resident hook kept in the save: the loader MOM runs, the head, the installer, the hook, end to end.

How it could fail. The loader branches into a blob that is not whole (a save-write that landed short,
or the older PKLD payload still in filler_B20); the head misreads its own base from the loader's
+5 and sums the wrong span; the ARM installer is entered from THUMB and returns into the wrong
state; a second visit to MOM chains the hook to itself. The blob must also fit one save-write.
"""

import pytest

from pokeldn.frlg.gift import wonder_card_events as wce
from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import native_script as ns
from pokeldn.frlg.rom import rom_map

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

VBLANK_INTR = 0x0800071C
SB2 = 0x02024584
LOADER_AT = ns.SCRATCH
STOP = 0x02030000
COUNTER = 0x02030100
NOENCOUNTER_FLAG = 0x020386D8


def _loader():
    return ns.stub("save-loader", sav2ptr=rom_map.GSAVEBLOCK2PTR, offset=ns.SAVE_PAYLOAD_OFFSET,
                   dest=bs.RESIDENT_SAVE_STAGING, words=bs.RESIDENT_SAVE_SIZE // 4,
                   magic=bs.RESIDENT_SAVE_MAGIC)


def _console(filler):
    filler = bytes(filler) + bytes(bs.RESIDENT_SAVE_SIZE - len(filler))
    stub = bytes.fromhex("024801680131016070470000") + COUNTER.to_bytes(4, "little")
    machine = bs._Machine(b"\x00" * 4, memory={
        rom_map.GSAVEBLOCK2PTR: SB2.to_bytes(4, "little"),
        SB2 + ns.SAVE_PAYLOAD_OFFSET: filler,
        LOADER_AT: _loader(),
        ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little"),
        VBLANK_INTR: stub,
        0x04000208: (1).to_bytes(2, "little")})
    return machine.uc


def _talk_to_mom(uc):
    """ScrCmd_callnative: a THUMB call into the staged loader, returning to its caller."""
    from unicorn import arm_const as a
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
    uc.reg_write(a.UC_ARM_REG_CPSR, uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
    uc.emu_start(LOADER_AT | 1, STOP, count=200000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP
    assert uc.reg_read(a.UC_ARM_REG_CPSR) & (1 << 5)          # back in THUMB, as it was called


def _frame(uc):
    from unicorn import arm_const as a
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, STOP)
    uc.emu_start(_read(uc, ns.GINTRTABLE_VBLANK), STOP, count=100000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == STOP


def _read(uc, at):
    return int.from_bytes(uc.mem_read(at, 4), "little")


@pytest.mark.parametrize("name, params", [("noencounter", {}), ("ivs", {}),
                                          ("turbo", {"field": 1, "hold": 0x100, "budget": 228})])
def test_mom_installs_the_hook_from_the_save_and_it_runs(name, params):
    blob = bs.build_resident_save_blob(name, **params)
    uc = _console(blob)
    _talk_to_mom(uc)
    hook, entry, original = bs.resident_blob(name, **params)
    assert _read(uc, ns.GINTRTABLE_VBLANK) == ns.RESIDENT_BASE + entry + 1
    installed = bytearray(uc.mem_read(ns.RESIDENT_BASE, len(hook)))
    assert _read(uc, ns.RESIDENT_BASE + original) == VBLANK_INTR | 1
    installed[original:original + 4] = hook[original:original + 4]
    assert bytes(installed) == hook
    assert _read(uc, ns.RESIDENT_BASE - 4) == VBLANK_INTR | 1  # the game's handler, kept
    if name == "noencounter":
        _frame(uc)
        assert uc.mem_read(NOENCOUNTER_FLAG, 1)[0] == 1 and _read(uc, COUNTER) == 1


def test_a_second_visit_still_chains_to_the_game():
    uc = _console(bs.build_resident_save_blob("noencounter"))
    _talk_to_mom(uc)
    _talk_to_mom(uc)
    _, entry, original = bs.resident_blob("noencounter")
    assert _read(uc, ns.RESIDENT_BASE + original) == VBLANK_INTR | 1
    _frame(uc)
    assert _read(uc, COUNTER) == 1


@pytest.mark.parametrize("damage", ["byte", "short", "old-payload"])
def test_a_blob_that_did_not_all_arrive_installs_nothing(damage):
    blob = bytearray(bs.build_resident_save_blob("noencounter"))
    if damage == "byte":
        blob[100] ^= 0x40
    elif damage == "short":
        blob = blob[:len(blob) // 2]                           # the tail never written
    else:
        blob = bytearray(ns.build_save_payload())              # PKLD, the older payload
    uc = _console(blob)
    _talk_to_mom(uc)
    assert _read(uc, ns.GINTRTABLE_VBLANK) == VBLANK_INTR | 1


def test_every_hook_that_fits_one_save_write_and_the_one_that_does_not():
    for name in ("turbo", "ivs", "noencounter"):
        assert len(bs.build_resident_save_blob(name)) <= bs.MAX_SAVE_WRITE_BYTES
    with pytest.raises(bs.BufferScriptError, match="one save-write carries"):
        bs.build_resident_save_blob("shiny")


def test_the_card_binds_this_loader():
    assert _loader() in wce.build_resident_save_script() or \
        ns.stage(_loader(), ns.SCRATCH) in wce.build_resident_save_script()
