import json
from pathlib import Path
import sys

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

import pytest

from frlg_rng_assist_core.live import (
    DEFAULT_STATE, RESIDENT_BASE, decode_state, resident_addresses, validate_state_address,
    version_args,
)


def test_build_mapping_and_state_decode_are_stable():
    assert version_args("BPRE") == ("firered", "firered")
    assert version_args("BPGE") == ("leafgreen", "leafgreen")
    with pytest.raises(ValueError):
        version_args("AGB")
    values = list(range(16))
    values[13] = 3
    data = b"".join(value.to_bytes(4, "little") for value in values)
    state = decode_state(data)
    assert state["current_seed"] == 0
    assert state["display_bottom"] == 15
    assert state["flags_names"] == ["initialized", "pending_a"]


def test_resident_addresses_use_generated_stub_symbols():
    addresses = resident_addresses()
    from pokeldn.frlg.rom.resident_stubs import STUBS
    symbols = STUBS["rng-assist"][2]
    assert addresses["p_state"] == RESIDENT_BASE + symbols["p_state"]
    assert addresses["p_auto_a"] == RESIDENT_BASE + symbols["p_auto_a"]
    assert validate_state_address(DEFAULT_STATE) == DEFAULT_STATE
    with pytest.raises(ValueError, match="overlaps"):
        validate_state_address(RESIDENT_BASE)


def test_trace_tool_parses_host_capture_without_radio(tmp_path, monkeypatch, capsys):
    import trace as trace_tool

    capture = tmp_path / "trace.bin"

    def fake_host(argv, *, radio=None):
        assert "--buffer-script" in argv and "rng-trace" in argv
        assert "--trace-call" in argv and argv[argv.index("--trace-call") + 1] == "0x0"
        output = Path(argv[argv.index("--dump-file") + 1])
        words = [1, 2, 0x030042D0, 0, 0x6073, 0xE97E, 0xE97E, 0x1234]
        output.write_bytes(b"".join(value.to_bytes(4, "little") for value in words))
        return 0

    monkeypatch.setattr(trace_tool, "run_host", fake_host)
    assert trace_tool.main(["--build", "BPRE", "--samples", "2", "--output", str(capture)]) == 0
    assert capture.is_file()
    report = json.loads(Path(str(capture) + ".json").read_text(encoding="utf-8"))
    assert report["kind"] == "live_rng_trace"
    assert report["mutates_rng"] is False
    assert report["taken"] == 2
    assert "Raw capture" in capsys.readouterr().out


def test_install_tool_is_observer_only_by_default(tmp_path, monkeypatch):
    import install as install_tool

    seen = {}

    def fake_host(argv, *, radio=None):
        seen["argv"] = list(argv)
        return 0

    monkeypatch.setattr(install_tool, "run_host", fake_host)
    assert install_tool.main(["--build", "BPRE", "--output", str(tmp_path / "install.bin")]) == 0
    args = seen["argv"]
    assert "--write-unsafe" in args
    assert "--resident" in args and args[args.index("--resident") + 1] == "rng-assist"
    assert "auto_a=0x0" in args


def test_arm_tool_writes_runtime_parameters_in_one_chain(tmp_path, monkeypatch):
    import arm as arm_tool

    seen = {}

    def fake_host(argv, *, radio=None):
        seen["argv"] = list(argv)
        output = Path(argv[argv.index("--dump-file") + 1])
        output.write_bytes(b"\x00" * 80)
        return 0

    monkeypatch.setattr(arm_tool, "run_host", fake_host)
    assert arm_tool.main(["--build", "BPRE", "--trigger-index", "12", "--offset", "4",
                          "--target-pid", "0x12345678", "--target-nature", "3",
                          "--enable-auto-a", "--output", str(tmp_path / "arm.bin")]) == 0
    args = seen["argv"]
    assert "--write-unsafe" in args
    steps = [args[i + 1] for i, value in enumerate(args[:-1]) if value == "--chain-step"]
    assert len(steps) == 11
    assert any("0x00000001" in step for step in steps)
    assert any("0x0000000C" in step for step in steps)
