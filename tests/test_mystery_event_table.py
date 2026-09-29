"""gMysteryEventScriptCmdTable located through sMysteryEventScriptContext.

InitScriptContext stores the table and its end as adjacent words at +0x5C and +0x60
[decomp:src/mystery_event_script.c:52, include/script.h], 68 apart: a `table-scan` with
`--table-delta 0x44 --table-runlen 2` answers with the table address.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import buffer_script, rom_map  # noqa: E402

MYSTERY_EVENT_CMD_COUNT = 17            # [decomp:data/mystery_event_script_cmd_table.s]
MYSTERY_EVENT_TABLE_BYTES = MYSTERY_EVENT_CMD_COUNT * 4

# struct ScriptContext: stackDepth/mode/comparisonResult, pad, nativePtr, scriptPtr, stack[20],
# cmdTable, cmdTableEnd, data[4] [decomp:include/script.h].
CTX_CMD_TABLE = 0x5C
CTX_CMD_TABLE_END = 0x60

# The table is script_data's last member [ld_script_rev10.ld:318-328]: above the event scripts,
# below .rodata.
ANSWER_LOW = 0x081AB569                 # the last command of gStdScripts[8], read
ANSWER_HIGH = 0x0824CDC0 - MYSTERY_EVENT_TABLE_BYTES     # gSpeciesInfo


def _context(cmd_table):
    """A struct ScriptContext as InitScriptContext leaves it, as bytes."""
    context = bytearray(116)
    context[CTX_CMD_TABLE:CTX_CMD_TABLE + 4] = cmd_table.to_bytes(4, "little")
    context[CTX_CMD_TABLE_END:CTX_CMD_TABLE_END + 4] = (
        cmd_table + MYSTERY_EVENT_TABLE_BYTES).to_bytes(4, "little")
    return bytes(context)


def test_the_scan_finds_the_context_and_reads_the_table_address_out_of_it():
    """The hit's address is the context and its value gMysteryEventScriptCmdTable."""
    context_at, table_at = 0x0203A000, 0x08215A40
    low, high = context_at - 0x40, context_at + 0x200
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=MYSTERY_EVENT_TABLE_BYTES, runlen=2, start=low, end=high, blocks=64),
        memory={context_at: _context(table_at)})
    answer = buffer_script.read_table_scan(repeated.final.pending_send, low, high)

    assert repeated.done
    assert answer["hits"] == [(context_at + CTX_CMD_TABLE, table_at)]


def test_a_context_that_never_ran_a_script_answers_nothing():
    """The context is zero until a Mystery Event script runs; the scan must follow one in the same boot."""
    context_at = 0x0203A000
    low, high = context_at - 0x40, context_at + 0x200
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=MYSTERY_EVENT_TABLE_BYTES, runlen=2, start=low, end=high, blocks=64),
        memory={context_at: bytes(116)})
    answer = buffer_script.read_table_scan(repeated.final.pending_send, low, high)
    assert answer["hits"] == []


def test_the_field_script_context_is_the_control_and_its_answer_is_already_known():
    """Delta 856 finds the field script context, whose cmdTable is the measured gScriptCmdTable."""
    assert rom_map.G_SCRIPT_CMD_TABLE == 0x08163650
    field_table_bytes = 214 * 4
    assert field_table_bytes == 0x358
    context_at = 0x0201F000
    low, high = context_at - 0x40, context_at + 0x200
    context = bytearray(116)
    context[CTX_CMD_TABLE:CTX_CMD_TABLE + 4] = rom_map.G_SCRIPT_CMD_TABLE.to_bytes(4, "little")
    context[CTX_CMD_TABLE_END:CTX_CMD_TABLE_END + 4] = (
        rom_map.G_SCRIPT_CMD_TABLE + field_table_bytes).to_bytes(4, "little")
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=field_table_bytes, runlen=2, start=low, end=high, blocks=64),
        memory={context_at: bytes(context)})
    answer = buffer_script.read_table_scan(repeated.final.pending_send, low, high)
    assert answer["hits"] == [(context_at + CTX_CMD_TABLE, rom_map.G_SCRIPT_CMD_TABLE)]


def test_the_table_was_found_where_the_bracket_said_it_had_to_be():
    """One hit in all 256 KB of EWRAM."""
    assert rom_map.G_MYSTERY_EVENT_CMD_TABLE == 0x081DE144
    assert ANSWER_LOW < rom_map.G_MYSTERY_EVENT_CMD_TABLE < ANSWER_HIGH
    assert rom_map.S_MYSTERY_EVENT_SCRIPT_CONTEXT + CTX_CMD_TABLE == 0x0203AA94


def test_the_seventeen_entries_are_seventeen_functions():
    """Seventeen distinct odd .text addresses within about a kilobyte: one object file."""
    addresses = [address for _name, address in rom_map.MYSTERY_EVENT_HANDLERS]
    assert len(addresses) == MYSTERY_EVENT_CMD_COUNT
    assert len(set(addresses)) == MYSTERY_EVENT_CMD_COUNT
    assert all(address & 1 for address in addresses), "a ScrCmdFunc pointer is THUMB"
    assert all(0x08000000 < address < rom_map.G_SCRIPT_CMD_TABLE for address in addresses)
    assert max(addresses) - min(addresses) < 0x800


def test_the_table_order_is_the_vms_own_opcode_order():
    """rom_map's decomp order agrees with mystery_event.OPCODE_NAMES, written from the console's VM."""
    from pokeldn.frlg.rom import mystery_event
    assert [name for name, _address in rom_map.MYSTERY_EVENT_HANDLERS] == [
        mystery_event.OPCODE_NAMES[opcode] for opcode in range(MYSTERY_EVENT_CMD_COUNT)]


def test_the_end_of_the_table_is_the_end_of_script_data():
    """lib_text follows script_data [ld_script_rev10.ld:318-330]; 0x4C41B510 (`push {r4, lr}`) was
    read there."""
    assert rom_map.SCRIPT_DATA_END == 0x081DE188
    assert rom_map.LIB_TEXT_START == rom_map.SCRIPT_DATA_END
    assert rom_map.SCRIPT_DATA_END == (rom_map.G_MYSTERY_EVENT_CMD_TABLE
                                       + 4 * MYSTERY_EVENT_CMD_COUNT)
    for address in (rom_map.G_SCRIPT_CMD_TABLE, rom_map.G_SPECIALS, rom_map.G_STD_SCRIPTS):
        assert rom_map.G_SCRIPT_CMD_TABLE <= address < rom_map.SCRIPT_DATA_END


def test_the_vms_workers_were_read_by_position():
    """Both dead opcodes make one call, to SetIncompatible [decomp:src/mystery_event_script.c]."""
    assert rom_map.ME_SET_INCOMPATIBLE == 0x080DE330
    assert rom_map.ME_CHECK_COMPATIBILITY < rom_map.ME_SET_INCOMPATIBLE
    # the two statics sit BELOW the handlers, which is where a C file's helpers go
    assert rom_map.ME_SET_INCOMPATIBLE < min(
        address & ~1 for _name, address in rom_map.MYSTERY_EVENT_HANDLERS)


def test_memcpy_lands_inside_lib_text_and_checks_the_boundary():
    """addtrainer's second call is memcpy [decomp:src/mystery_event_script.c], from libgcc in lib_text."""
    assert rom_map.MEMCPY > rom_map.LIB_TEXT_START
    assert rom_map.STRING_EXPAND_PLACEHOLDERS < rom_map.G_SCRIPT_CMD_TABLE   # ordinary .text
    assert rom_map.INIT_RAM_SCRIPT < rom_map.G_SCRIPT_CMD_TABLE


def test_varset_was_reachable_only_through_the_vm():
    """No ScrCmd calls VarSet; setenigmaberry does. VarGet's body is 0x1C [decomp:src/event_data.c:235]."""
    assert rom_map.GET_VAR_POINTER < rom_map.VAR_GET < rom_map.VAR_SET
    assert rom_map.VAR_SET - rom_map.VAR_GET == 0x1C
    assert rom_map.callable_function("VarSet") == rom_map.VAR_SET | 1, "a call needs the THUMB bit"


def test_every_worker_read_off_the_vm_is_a_rom_address():
    for name in ("STRING_COPY_N", "STRING_COMPARE", "SET_ENIGMA_BERRY", "ITEM_IS_MAIL",
                 "GIVE_MAIL_TO_MON2", "COMPACT_PARTY_SLOTS", "GET_SET_POKEDEX_FLAG",
                 "SPECIES_TO_NATIONAL_POKEDEX_NUM", "CALC_CRC16", "VAR_SET"):
        address = getattr(rom_map, name)
        assert 0x08000000 < address < rom_map.G_SCRIPT_CMD_TABLE, f"{name} is not in .text"
        assert address % 2 == 0, f"{name} is stored even; the THUMB bit goes on at the call"
