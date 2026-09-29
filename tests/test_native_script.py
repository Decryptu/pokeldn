"""RAM scripts that stage a THUMB stub and `callnative` it; stubs run under unicorn against rng_countdown."""

import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import lcg, native_script, rng_countdown, rng_script, rom_map  # noqa: E402
from pokeldn.frlg.rom.field_stubs import STUBS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import unicorn  # noqa: F401
    _HAVE_UNICORN = True
except ImportError:
    _HAVE_UNICORN = False
needs_unicorn = pytest.mark.skipif(not _HAVE_UNICORN,
                                   reason="offline execution needs unicorn")

# Read off the console: trainer-id-probe returned 0xE5BBDF65; the trainer card shows 57189.
CONSOLE_TID = 0xDF65
CONSOLE_SID = 0xE5BB
_SAV2 = 0x02030000


def _run(state, *, cap=1 << 18):
    """The stub, run on a memory model that carries a SaveBlock2 it has to find for itself."""
    save = bytearray(0x10)
    save[0x0A:0x0C] = CONSOLE_TID.to_bytes(2, "little")
    save[0x0C:0x0E] = CONSOLE_SID.to_bytes(2, "little")
    code = native_script.stub("shiny-seek", rng=rom_map.GRNG_VALUE,
                              sav2ptr=rom_map.GSAVEBLOCK2PTR, cap=cap)
    return native_script.emulate(code, memory={
        rom_map.GRNG_VALUE: int(state).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    })


def test_callnative_sets_bit_zero_because_the_stubs_are_thumb():
    """`callnative` calls through a pointer; bit 0 selects THUMB."""
    assert native_script.callnative_at(0x0201C000) == bytes.fromhex("2301c00102")
    assert native_script.callnative_at(0x0201C000, thumb=False)[1] == 0x00
    with pytest.raises(native_script.NativeScriptError):
        native_script.callnative_at(0x0201C001)         # the caller passes the address, not the bit


def test_staging_is_six_script_bytes_per_payload_byte():
    staged = native_script.stage(b"\xAA\xBB", 0x0201C000)
    assert len(staged) == 2 * native_script.SETPTR_SIZE
    assert staged[:6] == rng_script.setptr(0xAA, 0x0201C000)
    assert staged[6:] == rng_script.setptr(0xBB, 0x0201C001)
    with pytest.raises(native_script.NativeScriptError):
        native_script.stage(b"")


def test_the_budget_is_computed_from_the_two_sizes_and_not_written_down():
    plan = native_script.budget(72, other=7)
    assert plan["staged_bytes"] == 72 * 6
    assert plan["total"] == 72 * 6 + native_script.CALLNATIVE_SIZE + 7
    assert plan["limit"] == rng_script.MAX_RAM_SCRIPT_SIZE == 995
    assert plan["fits"] and plan["max_code_size"] == (995 - 5 - 7) // 6


def test_a_stub_too_big_to_stage_is_refused_offline(monkeypatch):
    """995 bytes of RAM script at six a byte is ~163 bytes of code."""
    assert not native_script.budget(200)["fits"]
    oversized = dict(STUBS)
    code, digest, symbols = oversized["shiny-seek"]
    oversized["shiny-seek"] = (code + b"\x00" * 128, digest, symbols)
    monkeypatch.setattr(native_script, "STUBS", oversized)
    with pytest.raises(native_script.NativeScriptError, match="will not fit"):
        native_script.build_shiny_hunt_script(132, 50)


def test_the_pool_offsets_come_from_the_assembler():
    """A parameter that moves in the .s must be a KeyError here, never a silently wrong word."""
    _code, _digest, symbols = STUBS["shiny-seek"]
    assert {"p_rng", "p_mult", "p_add", "p_sav2ptr", "p_cap"} <= set(symbols)
    with pytest.raises(native_script.NativeScriptError):
        native_script.stub("shiny-seek", nonesuch=1)
    with pytest.raises(native_script.NativeScriptError):
        native_script.stub("no-such-stub")


def test_patching_writes_the_word_where_the_symbol_says():
    code = native_script.stub("shiny-seek", rng=0x03004220, sav2ptr=0x0300422C, cap=99)
    _raw, _digest, symbols = STUBS["shiny-seek"]
    for key, value in (("rng", 0x03004220), ("sav2ptr", 0x0300422C), ("cap", 99)):
        offset = symbols[f"p_{key}"]
        assert int.from_bytes(code[offset:offset + 4], "little") == value
    # The LCG constants are the decomp's [include/random.h].
    assert int.from_bytes(code[symbols["p_mult"]:symbols["p_mult"] + 4], "little") == lcg.RAND_MULT
    assert int.from_bytes(code[symbols["p_add"]:symbols["p_add"] + 4], "little") == lcg.RAND_ADD


def test_the_committed_stub_bytes_are_what_the_source_assembles_to():
    if shutil.which("arm-none-eabi-as") is None:
        pytest.skip("no GBA toolchain")
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "gen_field_stubs.py"), "--check"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_hunt_script_stages_calls_and_then_battles_in_that_order():
    script = native_script.build_shiny_hunt_script(132, 50)
    lines = native_script.describe(script)
    assert "UNKNOWN" not in "".join(lines)
    assert lines[0].startswith("  setptr x80")
    assert lines[1] == "  callnative 0x0201C001 (THUMB)"
    assert lines[2].startswith("  setwildbattle species 132 Lv50")
    assert lines[3].startswith("  setvar 0x8000")
    assert lines[4].startswith("  goto 0x020370B4")
    assert len(script) <= rng_script.MAX_RAM_SCRIPT_SIZE


def test_nothing_between_the_call_and_the_generation_can_yield():
    """`setptr`, `callnative` and `setwildbattle` return FALSE [decomp:src/scrcmd.c]: one frame,
    nothing yields."""
    script = native_script.build_shiny_hunt_script(132, 50)
    code_size = len(native_script.stub("shiny-seek", rng=rom_map.GRNG_VALUE,
                                       sav2ptr=rom_map.GSAVEBLOCK2PTR, cap=1 << 18))
    call = code_size * native_script.SETPTR_SIZE          # the staged run ends, callnative begins
    assert script[call] == native_script.SCR_CALLNATIVE
    assert script[call:] == (native_script.callnative_at(native_script.SCRATCH)
                             + rng_script.battle_and_exit(132, 50))


def test_the_species_and_level_are_checked_before_a_console_ever_sees_them():
    for bad in ({"species": 0}, {"species": 999}, {"level": 0}, {"level": 200}, {"cap": 0}):
        kwargs = {"species": 132, "level": 50, **bad}
        with pytest.raises(native_script.NativeScriptError):
            native_script.build_shiny_hunt_script(**kwargs)
    with pytest.raises(native_script.NativeScriptError):
        native_script.build_shiny_hunt_script(132, 50, item=0x10000)


@needs_unicorn
@pytest.mark.parametrize("state", [
    0x52E6B438, 0xF2A74DE4, 0x269E0D37, 0x6513270E, 0xA6A3A450, 0x0C5C7FD0,
    0x128B2F33, 0xD23F0824, 0x892F902B, 0x1818E811, 0x5D9DC9F8, 0x9531985D,
])
def test_the_stub_lands_on_a_state_whose_encounter_is_shiny(state):
    """The stub's landing state is shiny by `rng_countdown`, written from the other direction."""
    landed = int.from_bytes(_run(state)["memory"][rom_map.GRNG_VALUE], "little")
    mon = rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID)
    assert mon["shiny"], f"0x{state:08X} -> 0x{landed:08X} is not shiny"
    assert mon["shiny_value"] < native_script.SHINY_ODDS
    # 1 state in 8192 is shiny.
    assert lcg.distance(state, landed) < 1 << 17


@needs_unicorn
def test_the_trainer_id_is_read_off_the_console_and_actually_used():
    """The stub reads gSaveBlock2Ptr; a different trainer id sends the search elsewhere."""
    state = 0x52E6B438
    other_tid, other_sid = 0x1234, 0x5678
    save = bytearray(0x10)
    save[0x0A:0x0C] = other_tid.to_bytes(2, "little")
    save[0x0C:0x0E] = other_sid.to_bytes(2, "little")
    code = native_script.stub("shiny-seek", rng=rom_map.GRNG_VALUE,
                              sav2ptr=rom_map.GSAVEBLOCK2PTR, cap=1 << 18)
    result = native_script.emulate(code, memory={
        rom_map.GRNG_VALUE: state.to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    })
    theirs = int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little")
    ours = int.from_bytes(_run(state)["memory"][rom_map.GRNG_VALUE], "little")
    assert theirs != ours
    assert rng_countdown._mon_from(theirs, other_tid, other_sid)["shiny"]
    assert not rng_countdown._mon_from(theirs, CONSOLE_TID, CONSOLE_SID)["shiny"]
    assert rng_countdown._mon_from(ours, CONSOLE_TID, CONSOLE_SID)["shiny"]


@needs_unicorn
def test_the_stub_leaves_the_rng_untouched_when_the_cap_runs_out():
    state = 0x12345678
    assert not rng_countdown._mon_from(state, CONSOLE_TID, CONSOLE_SID)["shiny"]
    result = _run(state, cap=4)
    assert int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little") == state


@needs_unicorn
def test_the_stub_returns_and_the_run_says_how_long_it_blocked_for():
    """A stub that does not return freezes the overworld; `emulate` refuses one."""
    result = _run(0x52E6B438)
    assert result["instructions"] > 0
    # An estimate from the GBA's clock, not a hardware measurement.
    assert native_script.frames_for(result["instructions"]) < 60


@needs_unicorn
def test_a_stub_that_never_returns_is_refused_rather_than_run():
    forever = bytes.fromhex("fee7")                      # b .   (Thumb, branch to itself)
    with pytest.raises(native_script.NativeScriptError):
        native_script.emulate(forever, instruction_limit=1000)


def test_the_battle_never_starts_from_inside_the_save_block():
    """MoveSaveBlocks_ResetHeap re-rolls gSaveBlock1 after a battle [decomp:src/battle_main.c:614,
    src/load_save.c:75] and the RAM script is held by a pointer into it: the battle starts from
    gSpecialVar_0x8000, never from a `dowildbattle` in the body."""
    cases = ((native_script.build_shiny_hunt_script(132, 50), 132, 50),
             (native_script.build_mon_hunt_script(129, 5), 129, 5),
             (rng_script.build_wild_battle_script(0xC0DE, 132, 50), 132, 50))
    for script, species, level in cases:
        # setwildbattle, the trampoline and the jump out of the save block. 0xB7 still occurs in the
        # body as data.
        assert script.endswith(rng_script.battle_and_exit(species, level))
        assert script.endswith(bytes([rng_script.SCR_GOTO])
                               + rng_script.TRAMPOLINE_ADDRESS.to_bytes(4, "little"))
    assert rng_script.TRAMPOLINE_WORD == (native_script.SCR_DOWILDBATTLE
                                          | (rng_script.SCR_END << 8))
    for script, _species, _level in cases[:2]:
        lines = native_script.describe(script)
        assert not any(line.strip().startswith("dowildbattle") for line in lines), lines
        assert "UNKNOWN" not in "".join(lines)


def test_the_opcode_sweep_runs_all_three_and_the_order_is_the_experiment():
    """`setstatus` and every opcode write ctx->data[2] [decomp:src/mystery_event_script.c];
    setenigmaberry runs last."""
    from pokeldn.frlg.gift import wonder_card_events as w
    from pokeldn.frlg.rom import mystery_event
    script = w.MEVENT_SWEEP_GIFT.mevent
    result = mystery_event.run(script)
    assert result.status == mystery_event.STATUS_SUCCESS
    kinds = [effect[0] for effect in result.effects]
    assert kinds.index("addrareword") < kinds.index("addtrainer") < kinds.index("setenigmaberry")


def test_the_sweep_berry_validates_and_keeps_the_cartridge_own_description_pointers():
    """IsEnigmaBerryValid needs stageDuration and maxYield nonzero [decomp:src/berry.c:984]; the ROM
    pointers come from the save."""
    from pokeldn.frlg.gift import wonder_card_events as w
    berry = w.build_sweep_berry()
    assert len(berry) == 28
    assert berry[10] != 0 and berry[20] != 0, "maxYield and stageDuration decide validity"
    assert int.from_bytes(berry[12:16], "little") == w.MEVENT_SWEEP_BERRY_DESC1
    assert int.from_bytes(berry[16:20], "little") == w.MEVENT_SWEEP_BERRY_DESC2


def _mon_run(state, criteria, *, cap=None, tid=CONSOLE_TID, sid=CONSOLE_SID,
             instruction_limit=1 << 26):
    save = bytearray(0x10)
    save[0x0A:0x0C] = tid.to_bytes(2, "little")
    save[0x0C:0x0E] = sid.to_bytes(2, "little")
    code = native_script.stub(
        "mon-seek", rng=rom_map.GRNG_VALUE, sav2ptr=rom_map.GSAVEBLOCK2PTR,
        cap=native_script.cap_for(criteria) if cap is None else cap,
        nature=criteria.nature_mask, ivmin=criteria.iv_word)
    result = native_script.emulate(code, memory={
        rom_map.GRNG_VALUE: int(state).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    }, instruction_limit=instruction_limit)
    return (int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little"),
            result["instructions"])


def _accepts(mon, criteria):
    """The criteria read against `rng_countdown`'s mon, which is written from the other side."""
    return (mon["shiny"]
            and (not criteria.natures or mon["nature"] in criteria.natures)
            and all(iv >= floor for iv, floor in zip(mon["ivs"], criteria.iv_minimums)))


def test_the_packed_words_are_what_the_stub_reads():
    """Without bit 30 in p_ivmin the IV loop in asm/field/mon-seek.s never ends."""
    criteria = native_script.MonCriteria(natures=(0, 24), iv_minimums=(1, 2, 3, 4, 5, 6))
    assert criteria.nature_mask == (1 << 0) | (1 << 24)
    assert native_script.MonCriteria().nature_mask == native_script.ANY_NATURE == (1 << 25) - 1
    word = criteria.iv_word
    assert word & (1 << native_script.IV_TERMINATOR_BIT)
    assert [(word >> (5 * i)) & 31 for i in range(6)] == [1, 2, 3, 4, 5, 6]
    assert native_script.MonCriteria().iv_word == 1 << native_script.IV_TERMINATOR_BIT


def test_the_criteria_are_checked_before_a_console_ever_sees_them():
    for bad in ({"natures": (25,)}, {"natures": (-1,)}, {"iv_minimums": (0, 0, 0, 0, 0, 32)},
                {"iv_minimums": (0, 0, 0)}):
        with pytest.raises(native_script.NativeScriptError):
            native_script.MonCriteria(**bad)


def test_natures_and_iv_floors_are_parsed_by_the_names_the_game_uses():
    assert native_script.parse_natures("adamant, Jolly") == (3, 13)
    assert native_script.parse_natures("3 13") == (3, 13)
    assert native_script.parse_natures(None) == ()
    assert native_script.parse_iv_minimums(["speed=31", "atk>=20"]) == (0, 20, 0, 31, 0, 0)
    for bad in (["nonesuch=1"], ["speed=32"], ["speed=x"]):
        with pytest.raises(native_script.NativeScriptError):
            native_script.parse_iv_minimums(bad)
    with pytest.raises(native_script.NativeScriptError):
        native_script.parse_natures("brisk")


def test_what_a_criterion_costs_is_arithmetic_and_not_a_guess():
    plain = native_script.MonCriteria()
    assert plain.probability == pytest.approx(native_script.SHINY_ODDS / 65536)
    nature = native_script.MonCriteria(natures=(3,))
    assert nature.probability == pytest.approx(plain.probability / 25)
    floored = native_script.MonCriteria(iv_minimums=(0, 0, 0, 16, 0, 0))
    assert floored.probability == pytest.approx(plain.probability / 2)
    cap = native_script.cap_for(nature)
    assert native_script.search_cost(nature, cap)["found_within_cap"] >= 0.99
    assert native_script.search_cost(nature, cap - 1)["found_within_cap"] < 0.99


def test_a_search_that_would_freeze_the_overworld_too_long_is_refused():
    """The cap bounds the freeze the player sees."""
    greedy = native_script.MonCriteria(natures=(3,), iv_minimums=(0, 31, 0, 31, 0, 0))
    with pytest.raises(native_script.NativeScriptError, match="ceiling"):
        native_script.build_mon_hunt_script(132, 50, criteria=greedy)
    script = native_script.build_mon_hunt_script(132, 50, criteria=greedy,
                                                 max_freeze_frames=10 ** 9, cap=1 << 24)
    assert len(script) <= rng_script.MAX_RAM_SCRIPT_SIZE


def test_the_mon_hunt_script_stages_calls_and_then_battles_like_the_shiny_one():
    script = native_script.build_mon_hunt_script(132, 50)
    lines = native_script.describe(script)
    assert "UNKNOWN" not in "".join(lines)
    assert lines[0].startswith("  setptr x160")
    assert lines[1] == "  callnative 0x0201C001 (THUMB)"
    assert lines[2].startswith("  setwildbattle species 132 Lv50")
    assert lines[-1].startswith("  goto 0x020370B4")
    assert len(script) <= rng_script.MAX_RAM_SCRIPT_SIZE


def test_the_bigger_stub_still_fits_the_only_budget_that_binds():
    """160 bytes of the 163 a 995-byte RAM script allows."""
    code = native_script.stub("mon-seek")
    plan = native_script.budget(len(code), other=9)
    assert plan["fits"] and plan["spare"] >= 0
    _raw, _digest, symbols = STUBS["mon-seek"]
    assert {"p_rng", "p_mult", "p_add", "p_sav2ptr", "p_cap",
            "p_nature", "p_ivmin"} <= set(symbols)


@needs_unicorn
@pytest.mark.parametrize("state", [0x52E6B438, 0xF2A74DE4, 0x269E0D37, 0x6513270E])
@pytest.mark.parametrize("criteria", [
    native_script.MonCriteria(),
    native_script.MonCriteria(natures=(3,)),
    native_script.MonCriteria(natures=(3, 13), iv_minimums=(0, 0, 0, 20, 0, 0)),
    native_script.MonCriteria(iv_minimums=(24, 0, 0, 0, 0, 0)),
], ids=["shiny", "nature", "two-natures-and-speed", "hp-floor"])
def test_the_stub_lands_on_the_first_state_that_satisfies_everything_asked_for(state, criteria):
    """The landing state passes and no state before it does."""
    landed, _instructions = _mon_run(state, criteria)
    assert _accepts(rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID), criteria)
    walked = lcg.distance(state, landed)
    assert walked < native_script.cap_for(criteria)
    current = state
    for _ in range(walked):
        assert not _accepts(rng_countdown._mon_from(current, CONSOLE_TID, CONSOLE_SID), criteria)
        current = lcg.advance(current, 1)
    assert current == landed


@needs_unicorn
@pytest.mark.parametrize("index", range(6))
def test_a_floor_lands_on_the_stat_it_names(index):
    """The IV draws pack 15 bits each with the seam between DEF and SPEED; checked per stat."""
    floors = [0] * 6
    floors[index] = 24
    criteria = native_script.MonCriteria(iv_minimums=tuple(floors))
    landed, _instructions = _mon_run(0x52E6B438, criteria)
    mon = rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID)
    assert mon["shiny"] and mon["ivs"][index] >= 24


@needs_unicorn
def test_the_iteration_cost_the_host_quotes_is_the_one_unicorn_counts():
    """INSTRUCTIONS_PER_ITERATION, measured: the count over the distance walked."""
    criteria = native_script.MonCriteria()
    for state in (0x52E6B438, 0x6513270E):
        landed, instructions = _mon_run(state, criteria)
        per_iteration = instructions / lcg.distance(state, landed)
        assert per_iteration == pytest.approx(native_script.INSTRUCTIONS_PER_ITERATION, abs=0.5)


@needs_unicorn
def test_the_trainer_id_still_comes_off_the_console_when_the_criteria_are_richer():
    criteria = native_script.MonCriteria(natures=(3, 13))
    ours, _ = _mon_run(0x52E6B438, criteria)
    theirs, _ = _mon_run(0x52E6B438, criteria, tid=0x1234, sid=0x5678)
    assert ours != theirs
    assert _accepts(rng_countdown._mon_from(theirs, 0x1234, 0x5678), criteria)
    assert not rng_countdown._mon_from(theirs, CONSOLE_TID, CONSOLE_SID)["shiny"]


@needs_unicorn
def test_the_richer_stub_also_leaves_the_rng_alone_when_the_cap_runs_out():
    state = 0x12345678
    landed, _instructions = _mon_run(state, native_script.MonCriteria(natures=(3,)), cap=4)
    assert landed == state


def test_the_hunt_card_carries_the_criteria_it_says_it_does():
    """Command-line criteria compose another card; the registry's default is untouched."""
    from pokeldn.frlg.gift import wonder_card_events as w
    default = w.RNG_MON_HUNT_GIFT.mevent
    assert len(default) <= 0x400                     # the console's receive buffer
    other = w.build_rng_mon_hunt_gift(native_script.MonCriteria(natures=(0,))).mevent
    assert other != default and len(other) == len(default)
    assert w.RNG_MON_HUNT_GIFT.card.default_flag_id == w.RNG_MON_HUNT_FLAG_ID
    differing = [i for i, (a, b) in enumerate(zip(default, other)) if a != b]
    assert 0 < len(differing) <= 4 * native_script.SETPTR_SIZE


@needs_unicorn
def test_the_bytes_the_console_will_actually_be_sent_search_for_what_the_card_says():
    """From the card's bytes: mystery_event.run, its `initramscript`, the staged `setptr` bytes,
    then unicorn."""
    from pokeldn.frlg.gift import wonder_card_events as w
    from pokeldn.frlg.rom import mystery_event

    effects = mystery_event.run(w.RNG_MON_HUNT_GIFT.mevent).effects
    kind, _group, _num, _object, field_script = effects[0]
    assert kind == "initramscript"

    staged, index = bytearray(), 0
    while index < len(field_script) and field_script[index] == native_script.SCR_SETPTR:
        address = int.from_bytes(field_script[index + 2:index + 6], "little")
        assert address == native_script.SCRATCH + len(staged), "the staging must be contiguous"
        staged.append(field_script[index + 1])
        index += native_script.SETPTR_SIZE
    assert field_script[index:index + native_script.CALLNATIVE_SIZE] == \
        native_script.callnative_at(native_script.SCRATCH)

    save = bytearray(0x10)
    save[0x0A:0x0C] = CONSOLE_TID.to_bytes(2, "little")
    save[0x0C:0x0E] = CONSOLE_SID.to_bytes(2, "little")
    state = 0x52E6B438
    result = native_script.emulate(bytes(staged), memory={
        rom_map.GRNG_VALUE: state.to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    }, instruction_limit=1 << 26)
    landed = int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little")
    assert _accepts(rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID),
                    w.RNG_MON_HUNT_CRITERIA)


def test_the_ramscript_offsets_are_the_decomps():
    """ramScript offsets from struct SaveBlock1 [decomp:include/global.h], checked against neighbours."""
    assert native_script.RAMSCRIPT_IN_SAVEBLOCK1 == 0x361C
    assert 0x348C + 400 == native_script.RAMSCRIPT_IN_SAVEBLOCK1
    assert native_script.RAMSCRIPT_MAGIC_OFFSET == 0x3620       # past the u32 checksum
    assert native_script.RAMSCRIPT_BODY_OFFSET == 0x3624        # past magic/mapGroup/mapNum/object
    size = 4 + 4 + native_script.MAX_RAM_SCRIPT_SIZE
    assert native_script.RAMSCRIPT_IN_SAVEBLOCK1 + size == 0x3A07        # 0x3A08 after alignment
    assert native_script.RAM_SCRIPT_MAGIC == 51                 # [decomp:src/script.c:12]


def test_the_payload_starts_word_aligned_and_not_merely_even():
    """Thumb `ldr [pc]` and `adr` use Align(PC, 4): an even but unaligned stub runs with garbage constants."""
    assert native_script.BODY_ALIGNMENT == 4
    for tail in range(0, 40):
        assert native_script.body_prefix_size(tail) % native_script.BODY_ALIGNMENT == 0
    with pytest.raises(native_script.NativeScriptError):
        native_script.ram_jump_stub(238)                 # even, and still wrong
    native_script.ram_jump_stub(240)


def test_the_body_carries_several_times_what_staging_ever_could():
    """The body costs one byte a payload byte; GetRamScript hands the engine the body
    [decomp:src/script.c:514]."""
    tail = rng_script.battle_and_exit(129, 5, 0)   # setwildbattle + setvar + goto
    assert len(tail) == 16
    room = native_script.body_capacity(len(tail))
    assert room["staged_equivalent"] == 162              # what the control card could hold
    assert room["payload"] == 755
    assert room["payload"] > 4 * room["staged_equivalent"]
    assert room["prefix"] + room["payload"] == native_script.MAX_RAM_SCRIPT_SIZE


def test_the_trampoline_is_the_only_thing_that_still_pays_six():
    """36 bytes staged, and everything after it is delivered at face value."""
    trampoline = native_script.stub(native_script.TRAMPOLINE_STUB)
    assert len(trampoline) == 36
    body = native_script.build_mon_hunt_far_script(129, 5)
    assert len(body) == native_script.MAX_RAM_SCRIPT_SIZE
    lines = native_script.describe(body)
    assert lines[0].startswith("  setptr x36")
    assert "callnative 0x0201C001 (THUMB)" in lines[1]


def _far(state, criteria, *, sb1_base=0x02025734, magic=native_script.RAM_SCRIPT_MAGIC,
         truncate=0, cap=None, tid=CONSOLE_TID, sid=CONSOLE_SID):
    """The script walked command by command, as the field engine would."""
    body = native_script.build_mon_hunt_far_script(
        129, 5, criteria=criteria, cap=cap)
    assert len(body) == native_script.MAX_RAM_SCRIPT_SIZE
    return native_script.emulate_body_script(
        body[:len(body) - truncate], sb1_base=sb1_base, magic=magic,
        rng_state=state, trainer_id=tid, secret_id=sid)


@needs_unicorn
def test_the_whole_script_finds_the_mon_it_was_asked_for_from_the_body():
    """The whole script: 36 `setptr`s, `callnative`, the trampoline into the body, and the search."""
    criteria = native_script.MonCriteria(natures=(13,), iv_minimums=(0, 0, 0, 20, 0, 0))
    for state in (0x12345678, 0x7041F74F, 1, 0xFFFFFFFF):
        result = _far(state, criteria)
        mon = rng_countdown._mon_from(result["rng"], CONSOLE_TID, CONSOLE_SID)
        assert _accepts(mon, criteria), (hex(state), mon)


@needs_unicorn
def test_a_short_body_leaves_the_rng_alone_instead_of_searching():
    """InitRamScript zero-fills what it was not given [ClearRamScript, script.c:495]; a short body
    sums low and the stub returns."""
    criteria = native_script.MonCriteria(natures=(13,))
    for truncate in (1, 2, 64, 500):
        result = _far(0x12345678, criteria, truncate=truncate)
        assert result["rng"] == 0x12345678, truncate


@needs_unicorn
def test_a_wrong_save_block_offset_bails_instead_of_executing_anything():
    """ramScript.data.magic other than 51 makes the trampoline return instead of branch."""
    result = _far(0x12345678, native_script.MonCriteria(), magic=0)
    assert result["rng"] == 0x12345678
    assert result["instructions"] < 20, "it should bail in single figures, not search"


@needs_unicorn
def test_it_follows_the_save_block_wherever_this_load_put_it():
    """The save block offset is re-rolled per battle and load [decomp:src/load_save.c:75]; the
    trampoline reads it at run time."""
    criteria = native_script.MonCriteria(natures=(13,))
    answers = {_far(0x12345678, criteria, sb1_base=0x02025734 + offset)["rng"]
               for offset in (0, 4, 76, 124)}
    assert len(answers) == 1 and 0x12345678 not in answers


# Read off the console after the hunt; the fixture for asm/field/mon-seek-both.s.

MEV20_PID = 0xCCCFF615                      # party slot 5, caught after the hunt
MEV20_IVS = (25, 7, 14, 10, 10, 30)         # hp atk def spe spa spd, off the Misc substructure
MEV20_STATE = 0x429D2189                    # the unique state whose draws 1,2 are that PID


def _ivs_from(first, second):
    """The two IV draws unpacked the way CreateBoxMon does [decomp:src/pokemon.c:1836]."""
    return ((first & 31), (first >> 5) & 31, (first >> 10) & 31,
            (second & 31), (second >> 5) & 31, (second >> 10) & 31)


def test_mev20_needed_one_extra_draw_between_the_personality_and_the_ivs():
    """Measured: the console built from draws 4,5 where the criteria held at 3,4, one extra Random()
    (docs/frlg_rng.md)."""
    assert lcg.nature_of(MEV20_PID) == 13                       # Jolly
    draws, _ = lcg.draws(MEV20_STATE, 5)
    assert (draws[0], draws[1]) == (MEV20_PID & 0xFFFF, MEV20_PID >> 16), "low half first"
    tested = _ivs_from(draws[2], draws[3])                      # what the stub checked
    happened = _ivs_from(draws[3], draws[4])                    # what the console made
    assert happened == MEV20_IVS
    assert tested[3] >= 20 and happened[3] == 10, (tested, happened)


def test_mev20_is_the_only_state_that_could_have_produced_that_pid():
    """S1's low half is the PID's low half: 2**16 candidates, one survives S2."""
    lo, hi = MEV20_PID & 0xFFFF, MEV20_PID >> 16
    found = [lcg.unstep((lo << 16) | top) for top in range(1 << 16)
             if lcg.draw(lcg.unstep((lo << 16) | top))[0] == lo
             and (lcg.step((lo << 16) | top) >> 16) == hi]
    assert found == [MEV20_STATE]


def test_two_words_cover_all_three_methods_docs_rng_records():
    """Words A (d3, d4) and B (d4, d5) cover Method 4 (d3, d5) too [asm/field/mon-seek-both.s]."""
    criteria = native_script.MonCriteria(natures=(13,), iv_minimums=(0, 0, 0, 20, 0, 0))
    body = native_script.build_mon_hunt_both_script(129, 5, criteria=criteria)
    result = native_script.emulate_body_script(
        body, rng_state=0x12345678, trainer_id=CONSOLE_TID, secret_id=CONSOLE_SID)
    d, _ = lcg.draws(result["rng"], 5)
    methods = {"1 (clean)": _ivs_from(d[2], d[3]),
               "2": _ivs_from(d[3], d[4]),
               "4": _ivs_from(d[2], d[4])}
    mon = rng_countdown._mon_from(result["rng"], CONSOLE_TID, CONSOLE_SID)
    assert mon["shiny"] and mon["nature"] == 13
    for name, ivs in methods.items():
        assert all(iv >= floor for iv, floor in zip(ivs, criteria.iv_minimums)), (name, ivs)


@needs_unicorn
def test_the_two_placement_search_refuses_what_the_one_placement_search_accepts():
    """`both` never answers before `far`, and on some seed strictly later."""
    criteria = native_script.MonCriteria(natures=(13,), iv_minimums=(0, 0, 0, 20, 0, 0))
    strictly_later = 0
    for state in (0x12345678, 0x7041F74F, 0xDEADBEEF, 1):
        far = native_script.emulate_body_script(
            native_script.build_mon_hunt_far_script(129, 5, criteria=criteria),
            rng_state=state, trainer_id=CONSOLE_TID, secret_id=CONSOLE_SID)["rng"]
        both = native_script.emulate_body_script(
            native_script.build_mon_hunt_both_script(129, 5, criteria=criteria),
            rng_state=state, trainer_id=CONSOLE_TID, secret_id=CONSOLE_SID)["rng"]
        d, _ = lcg.draws(far, 5)
        if not all(iv >= f for iv, f in zip(_ivs_from(d[3], d[4]), criteria.iv_minimums)):
            strictly_later += 1
            assert far != both, hex(state)
    assert strictly_later, "no seed exercised the difference; the test proves nothing"


def test_the_second_placement_squares_the_iv_term_and_nothing_else():
    """The personality precedes the stray draw, so only the IV term is raised."""
    criteria = native_script.MonCriteria(natures=(13,), iv_minimums=(0, 0, 0, 20, 0, 0))
    one = native_script.probability_for(criteria, 1)
    two = native_script.probability_for(criteria, 2)
    assert one == criteria.probability
    assert two == pytest.approx(one * (12 / 32))
    cap = native_script.cap_for(criteria, native_script.BOTH_CONFIDENCE, 2)
    cost = native_script.search_cost(criteria, cap, 2)
    assert cost["worst_frames"] <= native_script.MAX_FREEZE_FRAMES
    assert cost["expected_seconds"] < 6


def test_the_log_region_is_the_decomps_unused_block():
    """Measured: all 400 bytes of `unused_348C` read zero on the console before any write."""
    assert native_script.HUNT_LOG_OFFSET == 0x348C
    assert (native_script.HUNT_LOG_OFFSET + 400
            == native_script.RAMSCRIPT_IN_SAVEBLOCK1), "unused_348C ends where ramScript starts"
    assert native_script.HUNT_LOG_SIZE <= 400, "the record must fit inside the unused block"


def test_an_untouched_region_is_not_read_as_a_report():
    """An exhausted search writes `found` 0; the marker tells it from a stub that never ran."""
    assert native_script.decode_hunt_log(bytes(native_script.HUNT_LOG_SIZE)) is None
    record = native_script.HUNT_LOG_MAGIC.to_bytes(4, "little") + bytes(16)
    assert native_script.decode_hunt_log(record)["exhausted"] is True


@needs_unicorn
def test_the_hunt_writes_down_the_state_it_found_and_what_it_cost():
    criteria = native_script.MonCriteria(natures=(13,), iv_minimums=(0, 0, 0, 20, 0, 0))
    body = native_script.build_mon_hunt_log_script(129, 5, criteria=criteria)
    result = native_script.emulate_body_script(
        body, rng_state=0x12345678, trainer_id=CONSOLE_TID, secret_id=CONSOLE_SID)
    log = result["log"]
    assert log is not None and log["magic"] == native_script.HUNT_LOG_MAGIC
    assert log["start"] == 0x12345678
    assert log["found"] == result["rng"], "the log and gRngValue must not be able to disagree"
    assert log["found_one"] and 0 < log["iterations"] <= log["cap"]
    mon = rng_countdown._mon_from(log["found"], CONSOLE_TID, CONSOLE_SID)
    assert mon["shiny"] and mon["nature"] == 13
    # The stub's count and the host model are computed from opposite ends.
    assert log["frames"] == pytest.approx(
        native_script.frames_for_iterations(log["iterations"]))


@needs_unicorn
def test_an_exhausted_search_still_says_what_it_spent():
    criteria = native_script.MonCriteria(natures=(13,), iv_minimums=(0, 0, 0, 20, 0, 0))
    body = native_script.build_mon_hunt_log_script(129, 5, criteria=criteria, cap=1)
    result = native_script.emulate_body_script(
        body, rng_state=0x12345678, trainer_id=CONSOLE_TID, secret_id=CONSOLE_SID)
    log = result["log"]
    assert log["exhausted"] and log["found"] == 0
    assert log["cap"] == 1
    assert result["rng"] == 0x12345678, "a miss must leave gRngValue exactly as it was"


MEV22_FOUND = 0x4FB97B07                    # written into the save by the stub itself
MEV22_ITERATIONS = 603745                   # counted by the console
MEV22_START = 0x91D7F204
MEV22_PID = 0x590263DF                      # party slot 3
MEV22_IVS = (25, 10, 30, 21, 3, 1)


def test_the_consoles_own_counter_agrees_with_the_lcg_from_the_other_end():
    """The stub's loop count and `lcg.distance` between its logged states agree."""
    assert lcg.distance(MEV22_START, MEV22_FOUND) == MEV22_ITERATIONS


def test_the_logged_state_predicts_the_caught_mon_with_no_recovery_at_all():
    draws, _ = lcg.draws(MEV22_FOUND, 5)
    assert (draws[1] << 16) | draws[0] == MEV22_PID
    assert lcg.nature_of(MEV22_PID) == 13                       # Jolly


def test_mev22_fired_method_4_and_the_two_placement_search_still_held():
    """Method 4 (d3, d5) passes as a consequence of the floors on d3/d4 and d4/d5, measured on hardware."""
    criteria = native_script.MonCriteria(natures=(13,), iv_minimums=(0, 0, 0, 20, 0, 0))
    draws, _ = lcg.draws(MEV22_FOUND, 5)
    placements = {"1": _ivs_from(draws[2], draws[3]),
                  "2": _ivs_from(draws[3], draws[4]),
                  "4": _ivs_from(draws[2], draws[4])}
    assert placements["4"] == MEV22_IVS, "the console used Method 4"
    assert placements["1"] != MEV22_IVS and placements["2"] != MEV22_IVS
    for name, ivs in placements.items():
        assert all(iv >= f for iv, f in zip(ivs, criteria.iv_minimums)), name
    assert MEV22_IVS[3] >= 20
