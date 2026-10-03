"""The field script that seeds the RNG, checked byte for byte against the decomp's command table."""
import pytest

from pokeldn.frlg.gift import gift_composer
from pokeldn.frlg.rom import lcg, rng_script, rom_map


def test_the_opcodes_are_the_ones_the_command_table_names():
    # data/script_cmd_table.inc, read out of the decomp rather than remembered.
    assert (rng_script.SCR_END, rng_script.SCR_SETPTR) == (0x02, 0x11)
    assert (rng_script.SCR_PLAYSE, rng_script.SCR_WAITSE) == (0x2F, 0x30)


def test_setptr_is_an_immediate_byte_and_an_absolute_address():
    assert rng_script.setptr(0xDE, 0x03004220) == bytes.fromhex("11de20420003")
    with pytest.raises(rng_script.RngScriptError):
        rng_script.setptr(0x100, 0x03004220)        # setptr writes ONE byte


def test_the_seed_script_writes_grngvalue_little_endian_and_ends_without_clearing():
    script = rng_script.build_seed_script(0xC0DE)
    assert len(script) == 29
    for index, byte in enumerate((0xDE, 0xC0, 0x00, 0x00)):
        assert script[6 * index:6 * index + 6] == \
            rng_script.setptr(byte, rom_map.GRNG_VALUE + index)
    assert script[-1] == rng_script.SCR_END, "endram (0x0d) would clear the binding"
    assert rng_script.SCR_ENDRAM not in script, "0x0d anywhere would clear the binding"


def test_the_script_decodes_back_to_the_word_it_was_asked_for():
    for value in (0, 1, 0xC0DE, 0x41C64E6D, 0xFFFFFFFF):
        lines = rng_script.describe_seed_script(rng_script.build_seed_script(value))
        assert any(f"= 0x{value:08X}" in line for line in lines), lines
        assert any("gRngValue" in line for line in lines)


def test_it_targets_the_address_bs14_read_out_of_random_s_literal_pool():
    """gRngValue is a link-time IWRAM global; it does not move."""
    assert rom_map.GRNG_VALUE == 0x03004220
    assert rng_script.build_seed_script(0).find((0x03004220).to_bytes(4, "little")) == 2


def test_a_silent_script_is_shorter_and_still_writes_the_word():
    quiet = rng_script.build_seed_script(0xC0DE, sound=None)
    assert len(quiet) == 25
    assert any("= 0x0000C0DE" in line for line in rng_script.describe_seed_script(quiet))


def test_it_refuses_a_misaligned_target():
    with pytest.raises(rng_script.RngScriptError):
        rng_script.build_seed_script(0, address=rom_map.GRNG_VALUE + 1)


def test_it_fits_the_ram_script_the_save_actually_has_room_for():
    assert rng_script.MAX_RAM_SCRIPT_SIZE == 995     # sizeof(RamScriptData.script)
    assert len(rng_script.build_seed_script(0xFFFFFFFF)) < rng_script.MAX_RAM_SCRIPT_SIZE


def test_the_wild_battle_script_is_the_seed_then_the_battle_out_of_the_save_block():
    script = rng_script.build_wild_battle_script(0x81F6816D, 132, 50)
    assert script[:24] == rng_script.build_seed_script(0x81F6816D, sound=None)[:24]
    assert script[24] == rng_script.SCR_SETWILDBATTLE == 0xB6
    assert int.from_bytes(script[25:27], "little") == 132       # DITTO
    assert script[27] == 50                                     # level
    assert int.from_bytes(script[28:30], "little") == 0         # no held item
    # No `dowildbattle` in the save block: a battle relocates gSaveBlock1
    # [decomp:src/battle_main.c:614, src/overworld.c:1337], so the battle starts from
    # gSpecialVar_0x8000.
    assert script[30:] == (bytes([rng_script.SCR_SETVAR]) + b"\x00\x80"
                           + rng_script.TRAMPOLINE_WORD.to_bytes(2, "little")
                           + bytes([rng_script.SCR_GOTO])
                           + rng_script.TRAMPOLINE_ADDRESS.to_bytes(4, "little"))
    assert rng_script.TRAMPOLINE_WORD.to_bytes(2, "little") == bytes(
        [rng_script.SCR_DOWILDBATTLE, rng_script.SCR_END])


def test_nothing_that_yields_sits_between_the_seed_and_the_generation():
    """setptr and setwildbattle both return FALSE: one frame, nothing yields between them."""
    script = rng_script.build_wild_battle_script(0x81F6816D, 132, 50)
    upto_generation = script[:script.index(bytes([rng_script.SCR_SETWILDBATTLE]))]
    assert rng_script.SCR_PLAYSE not in upto_generation
    assert rng_script.SCR_WAITSE not in upto_generation
    assert rng_script.SCR_END not in upto_generation


def test_the_chosen_seed_makes_a_shiny_ditto_for_this_console():
    from pokeldn.frlg.gift import wonder_card_events
    got = rng_script.predict_wild_mon(wonder_card_events.RNG_DITTO_SEED, 12345, 2791)
    assert got["shiny"] is True
    assert got["low_first"]["shiny_value"] == got["high_first"]["shiny_value"] == 3
    assert got["ivs"] == (31, 23, 27, 18, 30, 30)
    assert got["iv_total"] == 159


def test_shininess_and_ivs_do_not_depend_on_the_half_order_but_nature_does():
    """Random32 is `Random() | (Random() << 16)`; the shiny test XORs both halves and the IVs come after."""
    got = rng_script.predict_wild_mon(0x81F6816D, 12345, 2791)
    assert got["low_first"]["shiny"] == got["high_first"]["shiny"]
    assert got["low_first"]["personality"] != got["high_first"]["personality"]
    assert got["low_first"]["nature"] != got["high_first"]["nature"]


def test_it_refuses_a_species_or_level_the_operands_cannot_carry():
    for bad in ((0, 50), (9999, 50), (132, 0), (132, 101)):
        with pytest.raises(rng_script.RngScriptError):
            rng_script.build_wild_battle_script(0, *bad)


def test_the_gift_carries_that_script_and_binds_it_to_the_pallet_town_man():
    from pokeldn.frlg.gift import gift_registry, wonder_card_events
    assert wonder_card_events.GIFT_RNG_SHINY_DITTO in gift_registry.GIFT_REGISTRY.live_choices
    mevent = wonder_card_events.build_rng_shiny_ditto_script()
    inner = rng_script.build_wild_battle_script(
        wonder_card_events.RNG_DITTO_SEED, wonder_card_events.SPECIES_DITTO,
        wonder_card_events.RNG_DITTO_LEVEL)
    assert inner in mevent, "the field script must reach the console verbatim"


def test_a_field_script_and_lines_are_not_both_accepted():
    from pokeldn.frlg.gift import wonder_card_events
    with pytest.raises(ValueError):
        wonder_card_events.build_mevent_npc_script(lines=("hi",), field_script=b"\x02")


def test_mev07_the_console_built_exactly_what_was_predicted():
    """Measured: the console built the predicted mon; nature 17 (QUIET) shows `Random32()` takes its
    low half first."""
    from pokeldn.frlg.gift import wonder_card_events
    got = rng_script.predict_wild_mon(wonder_card_events.RNG_DITTO_SEED, 12345, 2791)
    assert got["low_first"]["personality"] == 0x026F38B2
    assert got["low_first"]["nature"] == 17
    assert got["ivs"] == (31, 23, 27, 18, 30, 30)
    assert got["shiny"] is True


# Reading gRngValue in the overworld: `copybyte` needs gSpecialVar_0x8000's absolute address.

_OP_SETVADDRESS = 0xB8
_OP_COPYBYTE = 0x15
_OP_BUFFERNUMBERSTRING = 0x83
_OP_VMESSAGE = 0xBD
_OP_LOCK, _OP_FACEPLAYER, _OP_RELEASE, _OP_END = 0x6A, 0x5A, 0x6C, 0x02
_OP_WAITMESSAGE, _OP_WAITBUTTONPRESS, _OP_CLOSEMESSAGE = 0x66, 0x6D, 0x68


def _walk(script):
    """-> [(offset, opcode, operand bytes)] for the fixed-width commands this script uses."""
    widths = {_OP_SETVADDRESS: 4, _OP_COPYBYTE: 8, _OP_BUFFERNUMBERSTRING: 3, _OP_VMESSAGE: 4,
              0x28: 2,                                  # delay, a u16 of frames
              0xB6: 5,                                  # setwildbattle
              0xB7: 0,                                  # dowildbattle
              _OP_LOCK: 0, _OP_FACEPLAYER: 0, _OP_RELEASE: 0, _OP_END: 0,
              _OP_WAITMESSAGE: 0, _OP_WAITBUTTONPRESS: 0, _OP_CLOSEMESSAGE: 0}
    out, i = [], 0
    while i < len(script):
        op = script[i]
        if op not in widths:
            break                                   # the text pool starts here
        width = widths[op]
        out.append((i, op, bytes(script[i + 1:i + 1 + width])))
        i += 1 + width
        if op == _OP_END:
            break
    return out


def test_the_seed_read_script_copies_the_four_bytes_of_grngvalue_into_the_two_vars():
    script = gift_composer.build_seed_read_script()
    copies = [(int.from_bytes(operand[:4], "little"), int.from_bytes(operand[4:], "little"))
              for _offset, op, operand in _walk(script) if op == _OP_COPYBYTE]

    assert len(copies) == 4
    for i, (dest, src) in enumerate(copies):
        assert src == rom_map.GRNG_VALUE + i, f"byte {i} does not come from gRngValue"
        assert dest == rom_map.G_SPECIAL_VAR_0X8000 + i, f"byte {i} does not land in the vars"
    # gSpecialVar_0x8000 and 0x8001 are adjacent u16s: the halves reassemble as a little-endian u32.
    assert [dest for dest, _ in copies] == list(
        range(rom_map.G_SPECIAL_VAR_0X8000, rom_map.G_SPECIAL_VAR_0X8000 + 4))


def test_nothing_that_yields_sits_inside_the_read():
    """copybyte and buffernumberstring return FALSE: the four copies share one frame and cannot tear."""
    walked = _walk(gift_composer.build_seed_read_script())
    opcodes = [op for _offset, op, _operand in walked]
    first = opcodes.index(_OP_COPYBYTE)
    last = len(opcodes) - 1 - opcodes[::-1].index(_OP_BUFFERNUMBERSTRING)

    assert set(opcodes[first:last + 1]) == {_OP_COPYBYTE, _OP_BUFFERNUMBERSTRING}
    assert opcodes[first:last + 1] == [_OP_COPYBYTE] * 4 + [_OP_BUFFERNUMBERSTRING] * 2


def test_the_script_writes_nothing_but_the_two_scratch_vars():
    """No setptr, setvar, givemon or battle; the destinations are the game's own scratch vars."""
    walked = _walk(gift_composer.build_seed_read_script())
    for _offset, op, operand in walked:
        assert op != 0x11, "setptr writes memory; this script must not"
        assert op not in (0xB6, 0xB7), "no wild battle in a read-only script"
        if op == _OP_COPYBYTE:
            dest = int.from_bytes(operand[:4], "little")
            assert (rom_map.G_SPECIAL_VAR_0X8000
                    <= dest < rom_map.G_SPECIAL_VAR_0X8000 + 4), f"writes 0x{dest:08X}"


def test_the_message_pointer_is_relative_to_the_script_not_absolute():
    """gSaveBlock1Ptr moves; setvaddress makes vmessage's operand relative to the script."""
    script = gift_composer.build_seed_read_script()
    walked = _walk(script)
    (_offset, first_op, base_operand) = walked[0]
    pointers = [int.from_bytes(operand, "little")
                for _o, op, operand in walked if op == _OP_VMESSAGE]

    assert first_op == _OP_SETVADDRESS, "setvaddress must come first: it uses its own address"
    virtual_base = int.from_bytes(base_operand, "little")
    assert len(pointers) == 1
    text_at = pointers[0] - virtual_base
    assert 0 < text_at < len(script)
    assert script[text_at:].endswith(b"\xFF")        # a field string, terminated
    assert b"\xFD\x02" in script[text_at:] and b"\xFD\x03" in script[text_at:]


def test_the_script_ends_with_end_so_the_npc_can_be_asked_again():
    """`endram` (0x0d) calls ClearRamScript; `end` (0x02) does not."""
    script = gift_composer.build_seed_read_script()
    opcodes = [op for _o, op, _operand in _walk(script)]

    assert opcodes[-1] == _OP_END
    assert 0x0D not in opcodes


def test_the_printed_halves_reassemble_into_grngvalue():
    assert rng_script.seed_from_printed(0x5678, 0x1234) == 0x12345678
    with pytest.raises(rng_script.RngScriptError):
        rng_script.seed_from_printed(0x10000, 0)


def test_two_readings_prove_the_address_without_any_clock():
    """A distance always exists; two readings seconds apart are thousands of turns, unrelated
    numbers ~2**31."""
    first = 0x12345678
    second = lcg.advance(first, 2400)

    good = rng_script.check_two_readings(first, second, seconds=20)
    bad = rng_script.check_two_readings(0xDEADBEEF, 0x0BADF00D)

    assert any("CONSISTENT" in line for line in good)
    assert any("2,400 turns" in line for line in good)
    assert any("NOT consistent" in line for line in bad)


# `delay` waits an exact number of frames [decomp:src/scrcmd.c:651], so the rate is two exact
# numbers.

_OP_DELAY = 0x28


def test_the_rate_probe_reads_twice_into_different_vars_with_the_delay_between():
    script = gift_composer.build_seed_rate_script(frames=600)
    walked = _walk(script)
    opcodes = [op for _o, op, _operand in walked]
    copies = [(int.from_bytes(operand[:4], "little"), int.from_bytes(operand[4:], "little"))
              for _o, op, operand in walked if op == _OP_COPYBYTE]

    assert len(copies) == 8, "two readings of four bytes each"
    assert all(src == rom_map.GRNG_VALUE + (i % 4) for i, (_dest, src) in enumerate(copies))
    base = rom_map.G_SPECIAL_VAR_0X8000
    assert [dest for dest, _src in copies] == list(range(base, base + 8)), \
        "the two readings must not land on top of each other"
    # The delay is the only yielding command in the measured interval.
    assert opcodes.count(_OP_DELAY) == 1
    delay_at = opcodes.index(_OP_DELAY)
    assert opcodes[delay_at - 4:delay_at] == [_OP_COPYBYTE] * 4
    assert opcodes[delay_at + 1:delay_at + 5] == [_OP_COPYBYTE] * 4


def test_the_delay_operand_is_the_frame_count_asked_for():
    for frames in (1, 600, 0xFFFF):
        walked = _walk(gift_composer.build_seed_rate_script(frames=frames))
        operand = next(o for _off, op, o in walked if op == _OP_DELAY)
        assert int.from_bytes(operand, "little") == frames
    with pytest.raises(gift_composer.GiftValidationError):
        gift_composer.build_seed_rate_script(frames=0x10000)


def test_the_rate_is_two_exact_numbers_divided():
    """No clock anywhere: distance is exact arithmetic and frames is what delay was told."""
    before = 0x124D683F
    after = lcg.advance(before, 1200)

    lines = rng_script.measure_rate(before, after, 600)

    assert any("1,200" in line for line in lines)
    assert any("EXACTLY 2 per frame" in line for line in lines)
    assert any("2.000000 turns/frame" in line for line in lines)


def test_a_rate_that_is_not_two_is_reported_as_such_rather_than_rounded():
    before = 0x124D683F
    after = lcg.advance(before, 1307)

    lines = rng_script.measure_rate(before, after, 600)

    assert any("2.178333" in line for line in lines)
    assert any("+107" in line for line in lines)
    assert not any("EXACTLY" in line for line in lines)
    with pytest.raises(rng_script.RngScriptError):
        rng_script.measure_rate(before, after, 0)


def test_the_two_rate_models_are_told_apart_by_the_frame_count_and_only_that():
    """1,202 turns over 600 frames fits `2N+2` and `2.003333N`; only the frame count separates them."""
    from pokeldn.frlg.gift import wonder_card_events as events

    short = gift_composer.build_seed_rate_script(frames=600)
    long = gift_composer.build_seed_rate_script(frames=events.RNG_RATE_PROBE_LONG_FRAMES)

    def without_delay(script):
        return [(op, operand) for _o, op, operand in _walk(script) if op != _OP_DELAY]

    assert without_delay(short) == without_delay(long), \
        "only the delay's operand may differ between the two probes"
    assert events.RNG_RATE_PROBE_LONG_PREDICTIONS["constant overhead (2N+2)"] == 6002
    assert (events.RNG_RATE_PROBE_LONG_PREDICTIONS["rate above 2 (2.003333N)"]
            != events.RNG_RATE_PROBE_LONG_PREDICTIONS["constant overhead (2N+2)"]), \
        "a run that cannot come out two ways is not a test"


def test_the_generation_is_bracketed_by_two_reads_with_no_yield_between():
    """copybyte and setwildbattle return FALSE: the nine commands run in one frame."""
    script = gift_composer.build_draw_count_script(species=132, level=50)
    opcodes = [op for _o, op, _operand in _walk(script)]
    first = opcodes.index(_OP_COPYBYTE)
    last = len(opcodes) - 1 - opcodes[::-1].index(_OP_COPYBYTE)

    assert opcodes[first:last + 1] == [_OP_COPYBYTE] * 4 + [0xB6] + [_OP_COPYBYTE] * 4
    assert opcodes[-1] == 0xB7, "dowildbattle calls ScriptContext_Stop, so it must come last"
    assert 0xB7 not in opcodes[:-1]
