"""install-resident and the turbo-text hook, both executed under unicorn.

How it could fail. The installer: the blob lands short or shifted; the table is written before the
blob is whole; the hook chains to nothing or, installed twice, to itself (a spin inside the
interrupt that freezes the console); IME is left cleared. The hook: it skips the game's VBlankIntr;
it runs the text printers in a lag frame, where they would interleave with the main loop's own;
it returns anywhere but where IntrMain called it from.
"""

import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import native_script as ns

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

VBLANK_INTR = 0x0800071C            # the French cartridge's VBlankIntr, THUMB bit clear
RUN_TEXT_PRINTERS = 0x08002D50
INTR_CHECK = 0x030022EC
REG_IME = 0x04000208
TEXT_PRINTERS = 0x02020034             # sTextPrinters, 32 of 0x24 bytes
GMAIN = 0x030022D0
PALETTE_FADE = 0x02037AB4
CB1_OVERWORLD = 0x08059E48
CB2_OVERWORLD = 0x08059EC8


def _counting_stub(counter):
    """THUMB: *counter += 1; bx lr. Stands in for a ROM function the hook calls."""
    return (bytes.fromhex("024801680131016070470000") + counter.to_bytes(4, "little"))


def test_the_installer_puts_the_whole_hook_in_and_chains_it_to_the_old_handler():
    code = bs.build_install_resident("turbo", extra=6)
    blob, entry, original = bs.resident_blob("turbo", extra=6)
    machine = bs._Machine(code, memory={ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little"),
                                        REG_IME: (1).to_bytes(2, "little")})
    result = machine.call()
    assert result.done
    assert result.param == VBLANK_INTR | 1                      # the answer: what it replaced
    installed = bytes(machine.uc.mem_read(ns.RESIDENT_BASE, len(blob)))
    expected = bytearray(blob)
    expected[original:original + 4] = (VBLANK_INTR | 1).to_bytes(4, "little")
    assert installed == bytes(expected)
    table = int.from_bytes(machine.uc.mem_read(ns.GINTRTABLE_VBLANK, 4), "little")
    assert table == ns.RESIDENT_BASE + entry + 1
    assert int.from_bytes(machine.uc.mem_read(REG_IME, 2), "little") == 1


def test_a_second_install_keeps_chaining_to_the_game_not_to_itself():
    code = bs.build_install_resident("turbo")
    blob, entry, original = bs.resident_blob("turbo")
    machine = bs._Machine(code, memory={ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little")})
    machine.call()
    machine.call()                                               # the same payload, run again
    chained = int.from_bytes(machine.uc.mem_read(ns.RESIDENT_BASE + original, 4), "little")
    assert chained == VBLANK_INTR | 1


def _run_hook(intr_check, extra, printers=b"", field=0, callbacks=None, cb1_stub=None,
              battle=0, cb_addresses=None, fade=b"", overlay=0, watched=None, vblank=None):
    """Install, then enter the hook the way IntrMain does, with lr at a stop address."""
    from unicorn import UC_HOOK_CODE
    from unicorn import arm_const as a
    counters = 0x0203FFA0
    code = bs.build_install_resident("turbo", extra=extra, field=field, battle=battle,
                                     overlay=overlay)
    memory = {ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little"),
              VBLANK_INTR: vblank or _counting_stub(counters),
              RUN_TEXT_PRINTERS: _counting_stub(counters + 4),
              INTR_CHECK: intr_check.to_bytes(2, "little")}
    if printers:
        memory[TEXT_PRINTERS] = printers
    if fade:
        memory[PALETTE_FADE] = fade
    if watched is not None:
        memory[overlay] = watched.to_bytes(4, "little")
    if callbacks is not None:
        cb1, cb2, new_keys = callbacks
        memory[GMAIN] = cb1.to_bytes(4, "little") + cb2.to_bytes(4, "little")
        memory[GMAIN + 0x2E] = new_keys.to_bytes(2, "little") * 2
        stub1, stub2 = cb_addresses or (CB1_OVERWORLD, CB2_OVERWORLD)
        memory[stub1] = cb1_stub or _counting_stub(counters + 8)
        memory[stub2] = _counting_stub(counters + 12)
    machine = bs._Machine(code, memory=memory)
    machine.call()
    uc = machine.uc
    stop = 0x0203FF80
    uc.mem_write(stop, b"\x00\x00\x00\x00")
    entry = int.from_bytes(uc.mem_read(ns.GINTRTABLE_VBLANK, 4), "little")
    uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
    uc.reg_write(a.UC_ARM_REG_LR, stop)                         # intr_return is ARM code
    uc.reg_write(a.UC_ARM_REG_CPSR, uc.reg_read(a.UC_ARM_REG_CPSR) | (1 << 5))
    uc.emu_start(entry, stop, count=100000)
    assert uc.reg_read(a.UC_ARM_REG_PC) == stop
    read = lambda at: int.from_bytes(uc.mem_read(at, 4), "little")
    machine.read = read
    _run_hook.last = machine
    return read(counters), read(counters + 4), read(0x0203FF00), read(0x0203FF04)


def test_an_idle_frame_runs_the_game_then_the_extra_printers():
    vblank, printers, frames, idle = _run_hook(intr_check=0, extra=5)
    assert (vblank, printers, frames, idle) == (1, 5, 1, 1)


def test_a_lag_frame_runs_only_the_game():
    vblank, printers, frames, idle = _run_hook(intr_check=1, extra=5)
    assert (vblank, printers, frames, idle) == (1, 0, 1, 0)


def test_a_hook_that_does_not_fit_or_does_not_exist_is_refused():
    with pytest.raises(bs.BufferScriptError, match="unknown resident hook"):
        bs.build_install_resident("no-such-hook")
    with pytest.raises(bs.BufferScriptError, match="takes"):
        bs.build_install_resident("turbo", speed=3)


def _printer(x, y, current_x, current_y, active=1):
    """One struct TextPrinter [include/text.h:94]: the fields the hook reads, the rest zero."""
    p = bytearray(0x24)
    p[6], p[7], p[8], p[9], p[0x1B] = x, y, current_x, current_y, active
    return bytes(p)


def test_a_printer_the_game_has_not_started_holds_every_extra_call():
    """The field box adds its printer before drawing the box; printing it early drew the speaker's
    name and the start of the line into a window the box then cleared."""
    started = _printer(8, 1, 40, 1)
    fresh = _printer(8, 1, 8, 1)
    _, printers, _, idle = _run_hook(0, 5, started + fresh)
    assert (printers, idle) == (0, 0)
    _, printers, _, idle = _run_hook(0, 5, started + _printer(8, 1, 8, 1, active=0))
    assert (printers, idle) == (5, 1)
    _, printers, _, _ = _run_hook(0, 5, _printer(8, 1, 8, 17))     # a second line counts as started
    assert printers == 5


def test_a_reinstall_over_a_different_hook_still_chains_to_the_game():
    """The second install finds the table pointing into the resident area, at a hook whose layout
    differs from the new one's; it must chain to the handler kept at dest - 4, not to a stale
    offset of the old blob."""
    code = bs.build_install_resident("turbo")
    blob, entry, original = bs.resident_blob("turbo")
    machine = bs._Machine(code, memory={
        ns.GINTRTABLE_VBLANK: (ns.RESIDENT_BASE + 1).to_bytes(4, "little"),   # an older hook
        ns.RESIDENT_BASE: b"\xAA" * 0x80,                                     # its bytes
        ns.RESIDENT_BASE - 4: (VBLANK_INTR | 1).to_bytes(4, "little")})       # the kept handler
    machine.call()
    chained = int.from_bytes(machine.uc.mem_read(ns.RESIDENT_BASE + original, 4), "little")
    assert chained == VBLANK_INTR | 1


def test_a_resident_hook_with_no_kept_handler_is_left_alone():
    """An older installer kept nothing at dest - 4. Chaining to that zero would jump to address 0
    inside the interrupt, so nothing is written and the answer says so."""
    code = bs.build_install_resident("turbo")
    old = b"\xAA" * 0x80
    machine = bs._Machine(code, memory={
        ns.GINTRTABLE_VBLANK: (ns.RESIDENT_BASE + 1).to_bytes(4, "little"),
        ns.RESIDENT_BASE: old, REG_IME: (1).to_bytes(2, "little")})
    result = machine.call()
    assert result.done and result.param == 0xBAD0BAD0
    assert bytes(machine.uc.mem_read(ns.RESIDENT_BASE, 0x80)) == old
    assert int.from_bytes(machine.uc.mem_read(ns.GINTRTABLE_VBLANK, 4), "little") == ns.RESIDENT_BASE + 1
    assert int.from_bytes(machine.uc.mem_read(REG_IME, 2), "little") == 1


def test_the_field_pass_runs_both_overworld_callbacks_with_the_new_presses_cleared():
    _run_hook(0, 0, field=2, callbacks=(CB1_OVERWORLD | 1, CB2_OVERWORLD | 1, 0x0001))
    m = _run_hook.last
    counters = 0x0203FFA0
    assert (m.read(counters + 8), m.read(counters + 12), m.read(0x0203FF08)) == (2, 2, 2)
    keys = bytes(m.uc.mem_read(GMAIN + 0x2E, 4))
    assert keys == b"\x00\x00\x00\x00"                        # newKeys, newAndRepeatedKeys


def test_no_field_pass_outside_the_overworld():
    _run_hook(0, 0, field=2, callbacks=(CB1_OVERWORLD | 1, 0x08011001, 0x0001))   # a battle CB2
    m = _run_hook.last
    assert (m.read(0x0203FFA8), m.read(0x0203FFAC)) == (0, 0)
    assert bytes(m.uc.mem_read(GMAIN + 0x2E, 2)) == b"\x01\x00"                # presses untouched


def test_a_pass_whose_cb1_leaves_the_overworld_does_not_run_cb2():
    """CB1 bumps callback2 the way a warp's SetMainCallback2 replaces it: CB2_Overworld must not
    run after it, and no further pass starts."""
    leave = _counting_stub(GMAIN + 4)                            # callback2 += 1
    _run_hook(0, 0, field=2, callbacks=(CB1_OVERWORLD | 1, CB2_OVERWORLD | 1, 0), cb1_stub=leave)
    m = _run_hook.last
    assert m.read(0x0203FFAC) == 0
    assert m.read(GMAIN + 4) == (CB2_OVERWORLD | 1) + 1


def test_the_battle_pass_runs_the_battle_callbacks_and_not_the_field_ones():
    battle = (0x08015B6C, 0x08014888)
    _run_hook(0, 0, field=3, battle=1, callbacks=(battle[0] | 1, battle[1] | 1, 0x0002),
              cb_addresses=battle)
    m = _run_hook.last
    assert (m.read(0x0203FFA8), m.read(0x0203FFAC), m.read(0x0203FF08)) == (1, 1, 1)


def test_no_callback_pass_while_a_palette_fade_runs():
    """The stuck bag: gPaletteFade read off the console after closing it, a hardware fade that
    never finished. A second UpdatePaletteFade a frame wraps its one-bit hardwareFadeFinishing."""
    stuck = bytes.fromhex("0000000000000080400210000000000000000000")
    battle = (0x08015B6C, 0x08014888)
    _run_hook(0, 0, battle=1, callbacks=(battle[0] | 1, battle[1] | 1, 0), cb_addresses=battle,
              fade=stuck)
    m = _run_hook.last
    assert (m.read(0x0203FFA8), m.read(0x0203FFAC)) == (0, 0)
    idle = bytearray(stuck)
    idle[7] = 0                                                  # active cleared
    _run_hook(0, 0, battle=1, callbacks=(battle[0] | 1, battle[1] | 1, 0), cb_addresses=battle,
              fade=bytes(idle))
    assert _run_hook.last.read(0x0203FFAC) == 1


OAM_120 = 0x030026C8                    # gMain.oamBuffer[120]
PLTT_OBJ15 = 0x020379D6                 # gPlttBufferFaded, OBJ palette 15 colour 1
TILE_1008 = 0x06017E00


def _tile_picture(machine, tile):
    """Decode one 4bpp OBJ tile back into rows of '#' (colour 1) and '.' (anything else)."""
    data = bytes(machine.uc.mem_read(TILE_1008 + 32 * tile, 32))
    return ["".join("#" if (data[4 * y + x // 2] >> (4 * (x & 1))) & 0xF == 1 else "."
                    for x in range(8)) for y in range(8)]


def test_the_overlay_spells_the_watched_word_in_the_overworld():
    watched_at = 0x03004220                                      # gRngValue
    _run_hook(1, 0, overlay=watched_at, watched=0x1234ABCD,       # a lag frame: still drawn
              callbacks=(CB1_OVERWORLD | 1, CB2_OVERWORLD | 1, 0))
    m = _run_hook.last
    entries = [bytes(m.uc.mem_read(OAM_120 + 8 * i, 6)) for i in range(8)]
    tiles = [int.from_bytes(e[4:6], "little") for e in entries]
    assert [t & 0x3FF for t in tiles] == [0x3F0 + n for n in (1, 2, 3, 4, 0xA, 0xB, 0xC, 0xD)]
    assert all(t >> 12 == 15 for t in tiles)                     # OBJ palette 15
    assert [int.from_bytes(e[2:4], "little") for e in entries] == [174 + 8 * i for i in range(8)]
    assert _tile_picture(m, 1) == ["........", "...#....", "..##....", "...#....",
                                   "...#....", "...#....", "...#....", "..###..."]
    assert int.from_bytes(m.uc.mem_read(PLTT_OBJ15, 2), "little") == 0x7FFF
    assert int.from_bytes(m.uc.mem_read(PLTT_OBJ15 - 0x400, 2), "little") == 0x7FFF


def test_no_overlay_outside_the_overworld_or_when_off():
    _run_hook(0, 0, overlay=0x03004220, watched=0x1234ABCD, callbacks=(0, 0x08011001, 0))
    assert bytes(_run_hook.last.uc.mem_read(OAM_120, 8)) == bytes(8)
    _run_hook(0, 0, overlay=0, callbacks=(CB1_OVERWORLD | 1, CB2_OVERWORLD | 1, 0))
    assert bytes(_run_hook.last.uc.mem_read(OAM_120, 8)) == bytes(8)


def test_the_overlay_is_in_the_oam_buffer_before_the_game_copies_it():
    """Written after VBlankIntr, the entries reached OAM once the screen had begun drawing and the
    digits' top rows showed the previous frame. A VBlankIntr that records attr2 of entry 120 when it
    runs must see the overlay's tile already there."""
    probe = 0x0203FFC0
    snapshot = (bytes.fromhex("0248018802480180704700 00".replace(" ", ""))
                + (OAM_120 + 4).to_bytes(4, "little") + probe.to_bytes(4, "little"))
    _run_hook(0, 0, overlay=0x03004220, watched=0x70000000, vblank=snapshot,
              callbacks=(CB1_OVERWORLD | 1, CB2_OVERWORLD | 1, 0))
    assert int.from_bytes(_run_hook.last.uc.mem_read(probe, 2), "little") == 0xF3F0 + 7


def test_the_expanded_font_matches_the_sentinels_the_skip_compares():
    """A frame skips the ~9000-instruction upload when two words of the tiles already hold what the
    upload writes. If the constants disagreed with the expansion, the font would be rewritten every
    frame (a sentinel never matching) or never refreshed after the game overwrote it."""
    from unicorn import arm_const as a
    _run_hook(1, 0, overlay=0x03004220, watched=0, callbacks=(CB1_OVERWORLD | 1, CB2_OVERWORLD | 1, 0))
    m = _run_hook.last
    assert _tile_picture(m, 0xF)[7] == ".#......"
    assert int.from_bytes(m.uc.mem_read(TILE_1008 + 4, 4), "little") == 0x22211122
    assert int.from_bytes(m.uc.mem_read(TILE_1008 + 15 * 32 + 28, 4), "little") == 0x22222212
