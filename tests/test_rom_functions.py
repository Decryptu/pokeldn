"""Reading THUMB bodies out of a dump: where a function ends, what it calls, what it points at."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import rom_map, scrcmd, scrcmd_names, special_names, thumb  # noqa: E402
from pokeldn.frlg.text import charmap  # noqa: E402

# ScrCmd_special and its literal pool, dumped off the console; the pool words are gSpecials and
# gSpecialsEnd.
SPECIAL_BASE = 0x0806D7EC
SPECIAL_BYTES = bytes.fromhex(
    "00b5fff7fbfc0004800b054941180548814202d2086874f10ffd002002bc0847"
    "fc391608ec40160830b5041c"
)

# MEScrCmd_crc, dumped off the console. agbcc's epilogue: `pop {r4,r5,r6}; pop {r1}; bx r1`.
CRC_BASE = 0x080DE830
CRC_BYTES = bytes.fromhex(
    "70b5061c8ef7e4fc051c301c8ef7e0fc041cb06e241a706e2418301c8ef7d8fc"
    "011cb06e091a706e0918091b201c6af79ff80004000c854203d0002030670120"
    "f066012070bc02bc08470000f0b5474680b4061c0c1c15062d0e"
)

# The string Std_ObtainItem points at, off the French cartridge: a placeholder, then '!'.
OBTAINED_TEXT = bytes.fromhex("c9d6e8d9e2e9f000fd03ab")


def test_the_literal_pool_of_scrcmd_special_is_where_gspecials_came_from():
    """The pool words differ by 444 * 4, the table's length."""
    values = [value for _site, _pool, value
              in thumb.pc_literals(SPECIAL_BYTES, SPECIAL_BASE, SPECIAL_BASE,
                                   SPECIAL_BASE + len(SPECIAL_BYTES))]
    assert values == [rom_map.G_SPECIALS, rom_map.G_SPECIALS_END]
    assert rom_map.G_SPECIALS_END - rom_map.G_SPECIALS == len(special_names.SPECIALS) * 4


def test_scrcmd_special_calls_the_argument_reader_and_then_the_table():
    """ScrCmd_special reads a halfword, then `bx`es through the table."""
    targets = [target for _site, target
               in thumb.bl_targets(SPECIAL_BYTES, SPECIAL_BASE, SPECIAL_BASE,
                                   SPECIAL_BASE + len(SPECIAL_BYTES))]
    assert rom_map.SCRIPT_READ_HALFWORD in targets


def test_a_function_ends_on_the_agbcc_epilogue_not_only_on_pop_pc():
    """agbcc ends a THUMB function `pop {r4,r5,r6}; pop {r1}; bx r1`; looking only for 0xBDxx walks
    into the next one."""
    limit = CRC_BASE + len(CRC_BYTES)
    end = thumb.function_end(CRC_BYTES, CRC_BASE, CRC_BASE, limit)
    assert end < limit, "the epilogue was not found: bx Rn is not being treated as a return"
    # It ends after `bx r1`, before the padding and the next function's `push {r4-r7, lr}`.
    assert CRC_BYTES[end - CRC_BASE - 2:end - CRC_BASE] == bytes.fromhex("0847")
    assert end - CRC_BASE == 74


def test_the_crc_handler_makes_the_four_calls_the_decomp_gives_it():
    """Bounded to its body, crc reads three words and calls CalcCRC16 once."""
    end = thumb.function_end(CRC_BYTES, CRC_BASE, CRC_BASE, CRC_BASE + len(CRC_BYTES))
    targets = [t for _s, t in thumb.bl_targets(CRC_BYTES, CRC_BASE, CRC_BASE, end)]
    assert targets == [rom_map.SCRIPT_READ_WORD] * 3 + [rom_map.CALC_CRC16]


def test_every_table_entry_is_an_even_cartridge_address_the_thumb_bit_is_added_back():
    """Tables keep THUMB pointers stripped; `rom_map.thumb` puts the bit back for a `bx`."""
    for table in (rom_map.SPECIAL_ADDRESSES, scrcmd_names.HANDLERS):
        for address in table:
            assert not address & 1, f"0x{address:08X} still carries the THUMB bit"
            assert 0x08000000 <= address < 0x08800000
            assert rom_map.thumb(address) == address | 1


def test_a_message_string_keeps_its_placeholders():
    """A script string is dialogue: 'Obtenu: {STR_VAR_2}!' keeps its placeholder."""
    assert charmap.decode_message(OBTAINED_TEXT) == "Obtenu: {STR_VAR_2}!"
    assert charmap.decode(OBTAINED_TEXT) == "Obtenu: .Â!"


def test_read_string_refuses_a_string_whose_end_the_dump_does_not_hold():
    """A truncated string comes back None."""
    memory = scrcmd.Memory([(0x081A79F0, OBTAINED_TEXT)])
    assert scrcmd.read_string(memory, 0x081A79F0) is None
    whole = scrcmd.Memory([(0x081A79F0, OBTAINED_TEXT + b"\xff")])
    assert scrcmd.read_string(whole, 0x081A79F0) == "Obtenu: {STR_VAR_2}!"


def test_data_pointers_reports_what_a_script_points_at_and_the_dump_holds():
    """A text operand already inside a dump is a string to print, not an address to want."""
    # `msgbox <0x081A79F0>, 4` then `end` - the shape of Std_ObtainItem's message.
    script = bytes.fromhex("67f0791a08") + bytes([0x04]) + bytes.fromhex("02")
    memory = scrcmd.Memory([(0x081A7600, script), (0x081A79F0, OBTAINED_TEXT + b"\xff")])
    reached, referenced = scrcmd.follow(memory, 0x081A7600)
    assert referenced == {}, "the string is held, so nothing should be wanted"
    held = scrcmd.data_pointers(memory, reached)
    assert 0x081A79F0 in held
    assert scrcmd.read_string(memory, 0x081A79F0) == "Obtenu: {STR_VAR_2}!"


def test_null_field_special_is_a_two_byte_bx_lr():
    """171 of the 444 indices point at it."""
    assert rom_map.NULL_FIELD_SPECIAL == 0x080CE8DC
    assert rom_map.SPECIAL_ADDRESSES.count(rom_map.NULL_FIELD_SPECIAL) == 171
    body = bytes.fromhex("7047")     # bx lr
    end = thumb.function_end(body, rom_map.NULL_FIELD_SPECIAL, rom_map.NULL_FIELD_SPECIAL,
                             rom_map.NULL_FIELD_SPECIAL + len(body))
    assert thumb.is_return(int.from_bytes(body, "little"))
    assert end == rom_map.NULL_FIELD_SPECIAL + 2


def test_get_battle_outcome_is_one_load_of_the_global_it_is_named_for():
    """`ldr r0, [pc, #4]; ldrb r0, [r0]; bx lr`; the pool word is gBattleOutcome."""
    base = 0x080CE268
    body = bytes.fromhex("0148007870470000") + rom_map.GBATTLE_OUTCOME.to_bytes(4, "little")
    literals = thumb.pc_literals(body, base, base, base + len(body))
    assert [value for _site, _pool, value in literals] == [rom_map.GBATTLE_OUTCOME]


def test_the_specials_table_names_its_own_entries():
    """ShowDiploma and ShowTownMap both call QuestLog_CutRecording, which is special 392."""
    quest_log_cut_recording = 0x08115E58
    assert rom_map.SPECIAL_ADDRESSES[392] == quest_log_cut_recording
    assert special_names.SPECIALS[392] == "QuestLog_CutRecording"


def test_get_lead_mon_index_is_the_body_four_lead_mon_specials_share():
    """CalculatePlayerPartyCount then GetMonData twice: the decomp's GetLeadMonIndex."""
    assert rom_map.GET_LEAD_MON_INDEX == 0x080CE818
    assert rom_map.SPECIAL_ADDRESSES[131] == rom_map.CALCULATE_PLAYER_PARTY_COUNT
    for index in (230, 292, 293, 294):
        assert special_names.SPECIALS[index] in (
            "GetLeadMonFriendship", "LeadMonHasEffortRibbon",
            "GiveLeadMonEffortRibbon", "AreLeadMonEVsMaxedOut")


def test_the_high_leafgreen_segment_reaches_down_to_the_m4a_tables():
    """The -0x12D8 segment includes paired literal-pool words in the m4a tables."""
    low, high, delta, _evidence = [seg for seg in rom_map.LEAFGREEN_DELTA_SEGMENTS
                                   if seg[2] == -0x12D8][0]
    assert (low, high) == (0x0845F000, 0x086803FC)
    for firered, leafgreen in ((0x0847DCF8, 0x0847CA20), (0x0847DDAC, 0x0847CAD4),
                               (0x0847DF10, 0x0847CC38), (0x0849758C, 0x084962B4),
                               (0x084975BC, 0x084962E4)):
        assert leafgreen - firered == delta
        assert rom_map.leafgreen_guess(firered) == leafgreen


def test_the_two_sound_tables_are_four_music_players_apart():
    """struct MusicPlayer is 12 bytes and there are four: gSongTable sits 0x30 above gMPlayTable on
    both cartridges."""
    assert rom_map.G_SONG_TABLE - rom_map.G_MPLAY_TABLE == 4 * 12
    assert (rom_map.leafgreen_guess(rom_map.G_SONG_TABLE)
            - rom_map.leafgreen_guess(rom_map.G_MPLAY_TABLE)) == 4 * 12


def test_the_field_command_table_is_closed():
    """Every one of the 213 handler bodies has been read off the cartridge."""
    assert len(scrcmd_names.HANDLERS) == 214      # 214 opcodes, two of them the same ScrCmd_nop
    assert len(set(scrcmd_names.HANDLERS)) == 213


def test_the_easy_chat_segment_reaches_out_both_ways_after_bs120_lg191():
    """27 paired literal-pool words moved both ends of the -0x1C4 segment."""
    low, high, delta, _e = [seg for seg in rom_map.LEAFGREEN_DELTA_SEGMENTS if seg[2] == -0x1C4][0]
    assert (low, high) == (0x083B8000, 0x0843AFFF)
    assert rom_map.leafgreen_guess(0x083BEE74) == 0x083BEE74 - 0x1C4
    assert rom_map.leafgreen_guess(0x0841463E) == 0x0841463E - 0x1C4
    # Control: 0x082370FC is inside the measured -0x24 segment.
    assert rom_map.leafgreen_guess(0x082370FC) == 0x082370FC - 0x24


def test_no_boundary_is_wider_than_the_evidence_that_brackets_it():
    """Every gap is refused end to end."""
    for _before, _after, low, high, _evidence in rom_map.LEAFGREEN_DELTA_BOUNDARIES:
        for inside in (low + 1, (low + high) // 2, high - 1):
            try:
                rom_map.leafgreen_guess(inside)
            except ValueError:
                continue
            raise AssertionError(f"0x{inside:08X} is inside a boundary and was guessed at")


def test_there_is_a_minus_0x20_segment_between_the_species_table_and_easy_chat():
    """The delta sits at -0x20 for 1256 KB between -0x24 and -0x1C4."""
    low, high, delta, _e = [seg for seg in rom_map.LEAFGREEN_DELTA_SEGMENTS if seg[2] == -0x20][0]
    assert (low, high) == (0x08251DAD, 0x083B7B47)
    assert high - low > 1024 * 1024, "one point pretending to be a segment"
    assert rom_map.leafgreen_guess(0x08265950) == 0x08265950 - 0x20
    assert rom_map.leafgreen_guess(0x0839F83C) == 0x0839F83C - 0x20
    assert rom_map.leafgreen_guess(0x08251DAD) == 0x08251DAD - 0x20
    assert rom_map.leafgreen_guess(0x083B7B47) == 0x083B7B47 - 0x20
    # Both controls came out of the SAME pairing, on either side of the new segment.
    assert rom_map.leafgreen_guess(0x0823E514) == 0x0823E514 - 0x24
    assert rom_map.leafgreen_guess(0x083D6BDC) == 0x083D6BDC - 0x1C4


def test_the_four_low_segments_step_by_exactly_four_bytes():
    """The four low segments are -0x2C, -0x28, -0x24 and -0x20."""
    low = [d for _lo, _hi, d, _e in rom_map.LEAFGREEN_DELTA_SEGMENTS if -0x2C <= d < 0]
    assert low == [-0x2C, -0x28, -0x24, -0x20]
    assert all(b - a == 4 for a, b in zip(low, low[1:]))


def test_the_segments_are_in_address_order_and_never_overlap():
    """Overlapping segments would make leafgreen_guess answer with whichever came first."""
    bounds = [(lo, hi) for lo, hi, _d, _e in rom_map.LEAFGREEN_DELTA_SEGMENTS]
    assert bounds == sorted(bounds), "segments must be in address order"
    for (_lo, hi), (nlo, _nhi) in zip(bounds, bounds[1:]):
        assert hi < nlo, "two segments overlap: one of them is measured wrong"
