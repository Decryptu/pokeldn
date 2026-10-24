"""The shiny hook, installed and run frame by frame under unicorn against a Python model of FireRed."""

import pytest

from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom import lcg
from pokeldn.frlg.rom import native_script as ns

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")

VBLANK_INTR = 0x0800071C
SOUND_MAIN = 0x081DF53C
INTR_CHECK = 0x030022EC
GMAIN = 0x030022D0
CB1_OVERWORLD = 0x08059E49
CB2_OVERWORLD = 0x08059EC9
SCRIPT_CONTEXT = 0x03000FB0
WAIT_BUTTON = 0x0806F159                    # WaitForAorBPress, French
OFFSET = bs.SHINY_PRESS_OFFSETS["mewtwo"]
RNG = 0x03004220
SB2_PTR = 0x0300422C
SB2 = 0x02024584
STATE = 0x0203FF80
VCOUNT = 0x04000006
REG_IF = 0x04000202
STOP = 0x02030000
COUNTERS = 0x02030100


def _counting_stub(counter):
    """THUMB: *counter += 1; bx lr."""
    return bytes.fromhex("024801680131016070470000") + counter.to_bytes(4, "little")


def wild(seed, method=0):
    """-> (personality, nature) for a roll whose first call is the one after `seed`
    [src/wild_encounter.c:233, src/pokemon.c:1864]; method 1 is CreateMon's own Random32."""
    if method == 0:
        seed = lcg.step(seed)
        nature = (seed >> 16) % 25
    while True:
        seed = lcg.step(seed)
        low = seed >> 16
        seed = lcg.step(seed)
        pid = low | (seed >> 16) << 16
        if method or pid % 25 == nature:
            return pid, pid % 25


def first_shiny(seed, tid, sid, method=0, limit=100000):
    for index in range(limit):
        pid, nature = wild(seed, method)
        if tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF) < 8:
            return index, nature
        seed = lcg.step(seed)
    raise AssertionError("no shiny in range")


class Console:
    """One installed hook and the memory it reads; frame() enters it the way IntrMain does."""

    def __init__(self, seed, tid, sid, name="shiny", mode=2, **params):
        self.machine = bs._Machine(bs.build_install_resident(name, **params), memory={
            ns.GINTRTABLE_VBLANK: (VBLANK_INTR | 1).to_bytes(4, "little"),
            VBLANK_INTR: _counting_stub(COUNTERS),
            SOUND_MAIN: _counting_stub(COUNTERS + 4),
            SB2_PTR: SB2.to_bytes(4, "little"),
            SB2 + 0x0A: tid.to_bytes(2, "little") + sid.to_bytes(2, "little"),
            GMAIN: CB1_OVERWORLD.to_bytes(4, "little") + CB2_OVERWORLD.to_bytes(4, "little"),
            CB1_OVERWORLD & ~1: _counting_stub(COUNTERS + 8),
            SCRIPT_CONTEXT: bytes((0, mode, 0, 0)) + WAIT_BUTTON.to_bytes(4, "little"),
            RNG: seed.to_bytes(4, "little"),
            VCOUNT: (160).to_bytes(2, "little")})
        assert self.machine.call().param == VBLANK_INTR | 1
        self.uc = self.machine.uc
        self.entry = self.read(ns.GINTRTABLE_VBLANK)

    def read(self, at, size=4):
        return int.from_bytes(self.uc.mem_read(at, size), "little")

    def write(self, at, value, size=4):
        self.uc.mem_write(at, value.to_bytes(size, "little"))

    def frame(self, lag=False, held=0, hooks=()):
        from unicorn import arm_const as a
        self.write(INTR_CHECK, int(lag), 2)
        self.write(GMAIN + 0x2C, held, 2)
        self.uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        self.uc.reg_write(a.UC_ARM_REG_LR, STOP)
        handles = [self.uc.hook_add(kind, fn) for kind, fn in hooks]
        try:
            self.uc.emu_start(self.entry, STOP, count=2_000_000)
        finally:
            for h in handles:
                self.uc.hook_del(h)
        from unicorn import arm_const as a2
        assert self.uc.reg_read(a2.UC_ARM_REG_PC) == STOP

    def shown(self):
        return self.read(STATE + 24)

    def main_loop(self):
        """ReadKeys, then callback1, as AgbMain runs them after a V-blank [main.c:81, 97]."""
        from unicorn import arm_const as a
        self.write(GMAIN + 0x2E, 0, 2)
        self.uc.reg_write(a.UC_ARM_REG_SP, 0x03007D00)
        self.uc.reg_write(a.UC_ARM_REG_LR, STOP)
        self.uc.emu_start(self.read(GMAIN), STOP, count=100_000)
        return self.read(GMAIN + 0x2E, 2)


def _bcd(nature, count):
    return int(f"{nature:02d}{count:06d}", 16)


@pytest.mark.parametrize("seed, tid, sid, method", [
    (0x12345678, 50425, 50923, 0),          # the emulated save's IDs
    (0xDEADBEEF, 12345, 2791, 0),          # the retail FireRed's
    (0x00C0FFEE, 50425, 50923, 1),
])
def test_the_target_and_countdown_match_the_model_while_the_game_advances_two_calls_a_frame(
        seed, tid, sid, method):
    target, nature = first_shiny(seed, tid, sid, method)
    console = Console(seed, tid, sid, method=method, search=64)
    frames = target // 64 + 3
    rng = seed
    for f in range(frames):
        console.frame()
        rng = lcg.step(lcg.step(rng))                  # VBlankIntr's call and one more, as walking
        console.write(RNG, rng)
    console.frame()
    followed = 2 * frames
    assert console.read(STATE + 4) == followed
    if target - followed >= 4:
        assert console.read(STATE + 20) == nature + 1
        assert console.read(STATE + 16) == target
        assert console.shown() == _bcd(nature, target - followed - 4)
    else:
        assert console.read(STATE + 20) in (0, nature + 1)


def test_the_search_shows_ff_and_how_far_it_has_looked():
    seed, tid, sid = 0x12345678, 50425, 50923
    target, _ = first_shiny(seed, tid, sid)
    assert target > 32
    console = Console(seed, tid, sid, search=16)
    console.frame()
    assert console.shown() == 0xFF000016               # 16 tried, none shiny
    console.frame(lag=True)                            # a lag frame searches nothing
    assert console.read(STATE + 12) == 16


def test_a_reseed_starts_the_count_over():
    console = Console(0x12345678, 1, 2, search=4)
    console.frame()
    console.write(RNG, 0x0BADF00D)                     # not reachable in 64 steps
    console.frame()
    assert (console.read(STATE), console.read(STATE + 4)) == (0x0BADF00D, 0)


def test_a_passed_target_is_dropped_and_the_search_goes_on_past_it():
    seed, tid, sid = 0x12345678, 50425, 50923
    target, _ = first_shiny(seed, tid, sid)
    console = Console(seed, tid, sid, search=64)
    for _ in range(target // 64 + 2):
        console.frame()
    assert console.read(STATE + 16) == target
    followed = 0
    while followed < target - 3:                       # the game walks up to three calls short
        followed = min(followed + 60, target - 3)
        console.write(RNG, lcg.advance(seed, followed))
        console.frame()
    assert console.read(STATE + 4) == target - 3
    assert console.read(STATE + 20) == 0 or console.read(STATE + 16) > target
    assert console.read(STATE + 12) > target
    assert console.shown() >> 24 == 0xFF or console.read(STATE + 16) > target


def test_slow_motion_waits_out_the_frames_mixes_the_sound_for_each_and_clears_the_vblank():
    from unicorn import UC_HOOK_MEM_READ
    lines = {"v": 160}

    def vcount(uc, access, address, size, value, user):
        if address == VCOUNT:
            lines["v"] = (lines["v"] + 8) % 228        # the beam moves while the hook polls
            uc.mem_write(VCOUNT, lines["v"].to_bytes(2, "little"))

    console = Console(0x12345678, 1, 2, search=1, slow_frames=3)
    console.write(REG_IF, 0, 2)
    console.frame(held=0x100, hooks=((UC_HOOK_MEM_READ, vcount),))
    assert console.read(COUNTERS) == 1                 # the game's VBlankIntr, once
    assert console.read(COUNTERS + 4) == 3             # m4aSoundMain for each V-blank waited
    assert console.read(REG_IF, 2) == 1
    console.frame(held=0)                              # released: no waiting at all
    assert console.read(COUNTERS + 4) == 3


def test_r_is_kept_off_the_help_system():
    console = Console(0x12345678, 1, 2)
    console.frame()
    assert console.read(0x0203F171, 1) == 1


def _press_run(seed, tid, sid, frames, lag_at=None, held=0, **params):
    """-> [(index followed, newKeys after callback1)] a frame, the game advancing two calls a frame."""
    console = Console(seed, tid, sid, name="shiny-press", search=64, **params)
    out, rng = [], seed
    for f in range(frames):
        console.frame(lag=f == lag_at, held=held)
        out.append((console.read(STATE + 4), console.main_loop()))
        rng = lcg.step(lcg.step(rng))
        console.write(RNG, rng)
    return console, out


def _reachable(seed, tid, sid):
    """A seed whose first shiny CreateMon is an even number of calls past the offset."""
    while True:
        target, _ = first_shiny(seed, tid, sid, method=1)
        if target > 64 and (target - OFFSET) % 2 == 0:
            return seed, target
        seed = lcg.step(seed)


def test_the_press_is_one_a_at_the_waiting_script_on_the_frame_the_countdown_reaches_zero():
    seed, target = _reachable(0x00C0FFEE, 50425, 50923)
    console, frames = _press_run(seed, 50425, 50923, (target - OFFSET) // 2 + 4)
    pressed = [index for index, keys in frames if keys & 1]
    assert pressed == [target - OFFSET]
    assert console.read(GMAIN) == CB1_OVERWORLD          # the game's callback1 is back
    assert console.read(COUNTERS + 8) == len(frames)     # and CB1_Overworld ran every pass


@pytest.mark.parametrize("legendary, before, personality", [
    ("mewtwo", 0x8DEFC2AD, 0xF63E4E65), ("mewtwo", 0xFB34FA1C, 0x0CF1F63E), ("mewtwo", 0xA65852CF, 0x717DBAC6),
    ("birds", 0x7EBEF391, 0xBF74DA99), ("birds", 0x58AA4330, 0xE2E9BF74), ("birds", 0x39ABCAF2, 0x6577FD73)])
def test_the_offset_is_where_the_legendarys_personality_was_drawn_in_mgba(legendary, before, personality):
    """French FireRed in mGBA, A held for one frame at Mewtwo's last line or facing Zapdos: gRngValue
    at the frame boundary before it, and the personality setwildbattle gave gEnemyParty[0]. The hook's
    seed is one call later, VBlankIntr's [main.c:412]."""
    start = lcg.advance(lcg.step(before), bs.SHINY_PRESS_OFFSETS[legendary])
    assert wild(start, method=1)[0] == personality


@pytest.mark.parametrize("held, pressed", [(0x2, True), (0x2 | 0x100, True), (0x1, False), (0, False)])
def test_with_no_script_running_the_press_needs_b_held(held, pressed):
    """The talk press in front of a bird: script mode 0 (stopped), B (0x2) held."""
    seed, target = _reachable(0x00C0FFEE, 50425, 50923)
    _, frames = _press_run(seed, 50425, 50923, (target - OFFSET) // 2 + 4, held=held, mode=0)
    assert [index for index, keys in frames if keys & 1] == ([target - OFFSET] if pressed else [])


def test_no_press_without_a_waiting_script_or_on_a_lag_frame():
    seed, target = _reachable(0x00C0FFEE, 50425, 50923)
    count = (target - OFFSET) // 2 + 4
    console = Console(seed, 50425, 50923, name="shiny-press", mode=1, search=64)
    rng = seed
    for _ in range(count):
        console.frame()
        assert console.read(GMAIN) == CB1_OVERWORLD
        rng = lcg.step(lcg.step(rng))
        console.write(RNG, rng)
    _, frames = _press_run(seed, 50425, 50923, count, lag_at=(target - OFFSET) // 2)
    assert not any(keys & 1 for _, keys in frames)


def test_the_committed_resident_stubs_are_what_the_sources_assemble_to():
    import os
    import shutil
    import subprocess
    import sys
    if shutil.which("arm-none-eabi-as") is None:
        pytest.skip("no GBA toolchain")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run([sys.executable, os.path.join(root, "scripts", "gen_resident_stubs.py"),
                             "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("code, cartridge", [("BPRF", "scratchpad/FireRed_f.gba"),
                                              ("BPGF", "scratchpad/LeafGreen_f.gba"),
                                              ("BPRE", "scratchpad/frlg_en/FireRed_e.gba"),
                                              ("BPGE", "scratchpad/frlg_en/LeafGreen_e.gba")])
def test_the_sound_mixer_is_the_one_each_cartridges_vblankintr_calls(code, cartridge):
    """m4aSoundMain moves on French LeafGreen; the bl 0x56 bytes into VBlankIntr is decoded on the
    cartridge."""
    import pathlib
    import struct
    from pokeldn.frlg.rom import builds
    rom = pathlib.Path(cartridge)
    if not rom.exists():
        pytest.skip("no cartridge image on this machine")
    call = builds.BUILDS[code].vblank_intr + 0x56
    hi, lo = struct.unpack_from("<HH", rom.read_bytes(), call - 0x08000000)
    offset = ((hi & 0x7FF) << 12 | (lo & 0x7FF) << 1)
    offset -= (1 << 23) if offset & (1 << 22) else 0
    target = call + 4 + offset
    from pokeldn.frlg.rom.resident_stubs import STUBS
    blob, _, _ = bs.resident_blob("shiny", build=code)
    at = STUBS["shiny"][2]["p_sound_main"]
    assert int.from_bytes(blob[at:at + 4], "little") == target | 1


ROMS = {code: f"scratchpad/frlg_languages/{'FireRed' if b.version == 'firered' else 'LeafGreen'}_{code[3].lower()}.gba"
        for code, b in __import__("pokeldn.frlg.rom.builds", fromlist=["BUILDS"]).BUILDS.items()}


@pytest.mark.parametrize("code", sorted(ROMS))
def test_the_waiting_script_is_read_where_each_cartridge_keeps_it(code):
    """WaitForAorBPress is the literal ScrCmd_waitbuttonpress, gScriptCmdTable[0x6D]
    [data/script_cmd_table.inc:113], hands SetupNativeScript; sGlobalScriptContext is the first
    IWRAM literal of ScriptContext_SetupScript [script.c]."""
    import pathlib
    import struct
    from pokeldn.frlg.rom import builds
    path = pathlib.Path(ROMS[code])
    if not path.exists():
        pytest.skip("no cartridge image on this machine")
    rom, build = path.read_bytes(), builds.BUILDS[code]

    def words(function, count):
        """The literal-pool words of the first `count` ldr-pc instructions in a THUMB function."""
        out, at = [], function & ~1
        while len(out) < count:
            op = struct.unpack_from("<H", rom, at - 0x08000000)[0]
            if op >> 11 == 0b01001:
                out.append(struct.unpack_from("<I", rom, ((at + 4) & ~3) + (op & 0xFF) * 4 - 0x08000000)[0])
            at += 2
        return out

    context, table = words(build.setup_script, 2)
    command = struct.unpack_from("<I", rom, table + 0x6D * 4 - 0x08000000)[0]
    assert context == build.script_context
    assert build.wait_button | 1 in words(command, 4)
