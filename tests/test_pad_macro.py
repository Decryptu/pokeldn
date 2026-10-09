import json
import struct

import pytest

from pokeldn.pad import macro
from pokeldn.pad.link import CHUNK, DATA, LOAD, parse_status, program_writes


def test_reports_match_the_bytes_the_board_sent():
    # Read off the board's USB side on the Mac; RIGHT moved a retail Switch Lite's HOME cursor.
    assert macro.state(["A"]).hex() == "0400088080808000"
    assert macro.state(["B", "UP"]).hex() == "0200008080808000"
    assert macro.state(["RIGHT"]).hex() == "0000028080808000"
    assert macro.state(left=(-1, 0)).hex() == "0000080080808000"


def test_up_on_the_stick_is_the_low_end_of_the_axis():
    r = macro.state(left=(0, 1), right=(1, -1))
    assert (r[3], r[4], r[5], r[6]) == (128, 0, 255, 255)


@pytest.mark.parametrize("keys, hat", [
    (["UP", "RIGHT"], 1), (["DOWN", "LEFT"], 5), (["UP", "DOWN"], 8), (["LEFT", "RIGHT", "UP"], 0),
])
def test_dpad_combinations(keys, hat):
    assert macro.state(keys)[2] == hat


def program(text):
    return macro.compile_macro(macro.loads(json.dumps({"format": macro.FORMAT, "version": 1, **text})))


def test_setup_runs_once_and_the_loop_repeats():
    p = program({"press_ms": 80, "gap_ms": 20, "setup": [{"press": "B"}],
                 "loop": [{"press": "A", "ms": 50, "after": 0}, {"wait": 1000}], "loops": 0})
    assert p.loop_start == 2 and p.loops == 0
    assert p.entries == [(macro.state(["B"]), 80), (macro.NEUTRAL, 20),
                         (macro.state(["A"]), 50), (macro.NEUTRAL, 1000)]


def test_two_presses_of_a_button_keep_their_release():
    p = program({"loop": [{"repeat": 3, "steps": [{"press": "A", "ms": 50, "after": 50}]}]})
    assert [ms for _, ms in p.entries] == [50, 50] * 3
    assert p.loop_ms == 300


def test_a_hold_longer_than_one_entry_is_split():
    p = program({"loop": [{"press": "B", "ms": 200_000, "after": 0}]})
    assert [ms for _, ms in p.entries] == [65535, 65535, 65535, 3395, 1]
    assert sum(ms for _, ms in p.entries) == 200_001


def test_a_macro_longer_than_the_board_is_refused():
    with pytest.raises(macro.MacroError, match="8192"):
        program({"loop": [{"repeat": 5000, "steps": [{"press": "A"}]}]})


@pytest.mark.parametrize("bad, message", [
    ({"loop": [{"press": "Q"}]}, "unknown button"),
    ({"loop": [{"press": "A", "left": [2, 0]}]}, "from -1 to 1"),
    ({"loop": [{"press": "A", "hold": 3}]}, "unknown field"),
    ({"loop": [{"press": "A", "wait": 3}]}, "exactly one"),
    ({"loop": [{"wait": -1}]}, "milliseconds"),
    ({"loop": [{"press": "A", "ms": 0}]}, "milliseconds"),
    ({"loop": [{"repeat": 0, "steps": []}]}, "repeat"),
    ({"loop": [{"press": "A"}], "loops": -1}, "loops"),
    ({"version": 99}, "newer version"),
    ({"format": "something-else"}, "not a macro file"),
    ({}, "no steps"),
])
def test_bad_macros_name_the_problem(bad, message):
    with pytest.raises(macro.MacroError, match=message):
        program(bad)


def test_a_file_survives_export_and_import():
    m = macro.Macro(name="Réinitialisation", author="POKELDN", loops=0,
                    setup=[{"press": ["HOME"], "note": "leave"}],
                    loop=[{"repeat": 2, "steps": [{"press": "A", "left": [0.5, -0.5]}]}, {"wait": 3000}])
    again = macro.loads(m.dumps())
    assert again == m
    assert macro.compile_macro(again) == macro.compile_macro(m)


def test_load_writes_fit_one_att_packet_and_cover_every_entry():
    p = program({"loop": [{"repeat": 100, "steps": [{"press": "A", "ms": 30, "after": 40},
                                                     {"press": "B", "ms": 30, "after": 40}]}]})
    writes = program_writes(p)
    op, count, loop_start, loops = struct.unpack("<BHHI", writes[0])
    assert (op, count, loop_start, loops, len(writes[0])) == (LOAD, len(p.entries), 0, 1, 9)
    got = b""
    for n, w in enumerate(writes[1:]):
        assert w[0] == DATA and len(w) <= 3 + CHUNK * 10 <= 185
        assert struct.unpack_from("<H", w, 1)[0] == n * CHUNK
        got += w[3:]
    assert got == b"".join(r + struct.pack("<H", ms) for r, ms in p.entries)


def test_status_from_firmware_before_and_after_the_player():
    assert parse_status(bytes([1, 3, 0, 0, 0])).writes == 3
    s = parse_status(bytes([1, 0, 0, 0, 0, 1, 9, 0, 0, 0, 5, 0, 6, 0]) + b"1.0.0")
    assert (s.playing, s.loops_done, s.index, s.count, s.version) == (True, 9, 5, 6, "1.0.0")
    s = parse_status(bytes([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]) + b"1.0.1\0" + bytes([3, 8, 2, 0]))
    assert (s.version, s.reset_reason, s.stage_before, s.boots) == ("1.0.1", 3, 8, 2)
