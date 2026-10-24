"""Several resident hooks at once: laid out back to back, each calling the next as its original
handler, installed by the unchanged installers. Executed under unicorn."""

import pytest

from pokeldn.frlg.config import BufferScriptPayload
from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import native_script as ns
from tests.test_resident_save import (BUILD, COUNTER, NOENCOUNTER_FLAG, _booted_console, _frame, _read,
                                      _session, _talk_to_mom)
from tests.test_turbo import INTR_CHECK, REG_IME, RUN_TEXT_PRINTERS, VBLANK_INTR, _counting_stub

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")


def _enter(uc, stop=0x02030000):
    from unicorn import arm_const as a
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, stop)
    uc.reg_write(a.UC_ARM_REG_CPSR, uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
    uc.emu_start(_read(uc, ns.GINTRTABLE_VBLANK), stop, count=100000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == stop


@pytest.mark.parametrize("name", ["turbo+noencounter", "turbo-lite+noclip+noencounter"])
def test_one_frame_runs_every_hook_of_the_chain_and_the_game_once(name):
    counters = 0x02030100
    extra = {f"{name.split('+')[0]}.extra": 3}
    code = bs.build_install_resident(name, **extra)
    machine = bs._Machine(code, memory={ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little"),
                                        VBLANK_INTR: _counting_stub(counters),
                                        RUN_TEXT_PRINTERS: _counting_stub(counters + 4),
                                        INTR_CHECK: (0).to_bytes(2, "little"),
                                        REG_IME: (1).to_bytes(2, "little")})
    assert machine.call().param == VBLANK_INTR | 1
    uc = machine.uc
    blob, entry, original = bs.resident_blob(name, **extra)
    assert _read(uc, ns.GINTRTABLE_VBLANK) == ns.RESIDENT_BASE + entry + 1
    installed = bytes(uc.mem_read(ns.RESIDENT_BASE, len(blob)))
    _enter(uc)
    assert (_read(uc, counters), _read(uc, counters + 4)) == (1, 3)    # VBlankIntr once, three extras
    assert uc.mem_read(NOENCOUNTER_FLAG, 1)[0] == 1
    assert bytes(uc.mem_read(ns.RESIDENT_BASE, len(blob))) == installed   # data stays off the code


def test_a_chain_kept_in_the_save_is_written_and_installed_in_one_session():
    host, client = _session(None, payload=BufferScriptPayload(script=bs.SAVE_WRITE,
                                                              write_resident=("turbo+noclip", ())))
    blob = bs.build_resident_save_blob("turbo+noclip")
    assert len(client.buffer_scripts) == 3                      # two writes, then install-kept
    assert client.sav2[0xB20:0xB20 + len(blob)] == blob
    assert host.server.buffer_status == BUILD.vblank_intr | 1


def test_mom_installs_a_chain_and_a_frame_runs_both():
    uc, _ = _booted_console(bs.build_resident_save_blob("noencounter+noclip"))
    _talk_to_mom(uc)
    blob, entry, original = bs.resident_blob("noencounter+noclip")
    assert _read(uc, BUILD.intr_vblank) == ns.RESIDENT_BASE + entry + 1
    assert _read(uc, ns.RESIDENT_BASE + original) == BUILD.vblank_intr | 1
    _frame(uc)
    assert uc.mem_read(NOENCOUNTER_FLAG, 1)[0] == 1 and _read(uc, COUNTER) == 1


@pytest.mark.parametrize("name,refusal", [
    ("shiny+ivs", "both draw"),
    ("follower+turbo", "runs alone"),
    ("turbo+noclip+noencounter", "resident area holds 1024"),
    ("noclip+noclip", "twice"),
])
def test_a_chain_that_cannot_run_together_is_refused(name, refusal):
    with pytest.raises(bs.BufferScriptError, match=refusal):
        bs.build_resident_save_blob(name)


def test_a_chain_past_one_session_goes_through_the_save():
    with pytest.raises(bs.BufferScriptError, match="receive buffer"):
        bs.build_install_resident("turbo+noclip")
    assert len(bs.build_resident_save_blob("turbo+noclip")) <= bs.RESIDENT_SAVE_SIZE
