"""Run with a supported PokeLDN checkout on sys.path; core tests also run on the old checkout."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from frlg_rng_assist_core.compat import backend, predict
from frlg_rng_assist_core.model import Criteria, calibrate, search
from frlg_rng_assist_core.reporting import save_report


def reference(seed, method):
    """Independent draw/bit-packing oracle in display order, not a call to the host predictor."""
    draws = []
    for _ in range(5):
        seed = (0x41C64E6D * seed + 0x6073) & 0xFFFFFFFF
        draws.append(seed >> 16)
    pid = draws[0] | draws[1] << 16
    first, second = {1: (draws[2], draws[3]), 2: (draws[3], draws[4]),
                     4: (draws[2], draws[4])}[method]
    return pid, (first & 31, first >> 5 & 31, first >> 10 & 31,
                 second >> 5 & 31, second >> 10 & 31, second & 31)


@pytest.mark.parametrize("method", [1, 2, 4])
@pytest.mark.parametrize("seed", [0, 0x12345678, 0xFFFFFFFF, 0xDEADBEEF])
def test_prediction_matches_independent_draws_and_iv_order(seed, method):
    mon = predict(seed, 50425, 50923, method)
    pid, ivs = reference(seed, method)
    assert (mon["personality"], mon["ivs"]) == (pid, ivs)
    assert mon["nature"] == pid % 25
    assert mon["shiny"] == ((50425 ^ 50923 ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8)


def test_search_counts_each_advance_and_does_not_claim_live_timing():
    # The first shiny from this known seed is at an ODD advance; a two-per-frame scan misses it.
    result = search(0x12345678, 50425, 50923, advances=26000, max_results=1)
    hit = result["targets"][0]
    assert hit["predicted_generation_index"] == 25105
    assert hit["pid"] == 1655857312
    assert hit["ivs"] == (31, 19, 7, 20, 11, 12)
    assert hit["trigger_seed"] is None
    assert hit["trigger_status"] == "offset_missing"
    assert result["candidates_tested"] == 25106
    assert not result["live_synchronized"] and not result["profile_verified"]
    assert not result["auto_a_available"]


def test_exact_pid_nature_iv_floors_and_measured_offset():
    lcg, _ = backend()
    pid, ivs = reference(lcg.advance(0x12345678, 10), 1)
    result = search(0x12345678, 1, 2, advances=20, criteria=Criteria(False, pid % 25, pid, ivs), offset=6)
    hit, = result["targets"]
    assert hit["predicted_generation_index"] == 10
    assert hit["trigger_index"] == 4
    assert lcg.advance(hit["trigger_seed"], 6) == hit["predicted_generation_seed"]
    assert hit["trigger_status"] == "predicted_only"


def test_offset_already_passed_is_not_wrapped_to_a_future_target():
    result = search(0, 0, 0, advances=1, criteria=Criteria(False), offset=10)
    hit, = result["targets"]
    assert hit["trigger_index"] is None and hit["trigger_status"] == "already_passed"


@pytest.mark.parametrize("changes", [dict(tid=65536), dict(sid=-1), dict(seed=-1), dict(method=True),
                                     dict(method=3), dict(advances=0), dict(offset=-1),
                                     dict(start=0xFFFFFFFF, advances=2), dict(build="UNKNOWN")])
def test_invalid_parameters_are_rejected(changes):
    args = dict(seed=0, tid=0, sid=0)
    args.update(changes)
    with pytest.raises(ValueError):
        search(**args)


@pytest.mark.parametrize("method", [1, 2, 4])
def test_calibration_recovers_pre_pid_seed_and_advance_distance(method):
    lcg, _ = backend()
    hit_seed = 0x12345678
    target_seed = lcg.advance(hit_seed, 6)
    pid, ivs = reference(target_seed, method)
    result = calibrate(hit_seed, pid, ivs, max_offset=32, hit_boundary="post-vblank")
    assert {"generation_seed": target_seed, "method": method, "offset_advances": 6} in result["candidates"]
    assert not result["profile_verified"]
    assert not result["auto_a_available"]
    assert result["hit_boundary"] == "post-vblank"
    assert calibrate(hit_seed, pid, ivs, max_offset=5)["result"] == "no_match"


def test_calibration_does_not_label_manual_readings_as_vblank_hits():
    pid, ivs = reference(0, 1)
    result = calibrate(0, pid, ivs, max_offset=0)
    assert result["hit_boundary"] == "unspecified"


def test_report_uses_exclusive_files_and_preserves_previous_records(tmp_path):
    path = tmp_path / "sample.json"
    result = search(0, 0, 0, advances=1)
    assert save_report(result, path) == path
    before = path.read_bytes()
    assert json.loads(before)["plugin_version"] == "0.1.0"
    with pytest.raises(FileExistsError):
        save_report(result, path)
    assert path.read_bytes() == before


def test_backend_failures_stop_before_search(monkeypatch):
    lcg, _ = backend()
    backend.cache_clear()
    monkeypatch.setattr(lcg, "step", lambda value: 123)
    try:
        with pytest.raises(RuntimeError, match="incompatible"):
            search(0, 0, 0, advances=1)
    finally:
        backend.cache_clear()


def test_registered_tools_use_real_plugin_api_and_pack_successfully(tmp_path, monkeypatch):
    plugins = pytest.importorskip("pokeldn.plugins")
    from pokeldn.app import paths, plugin_store
    monkeypatch.setenv("POKELDN_PLUGINS", str(PLUGIN))
    monkeypatch.setattr(paths, "DATA", tmp_path / "app-data")
    plugins._reset()
    try:
        loaded = next(p for p in plugins.load() if p.id == "frlg-rng-assist")
        assert loaded.loaded and not loaded.error
        assert {tool.key for game, tool in loaded.tools if game == "frlg"} == {
            "frlg-rng-assist-search", "frlg-rng-assist-calibrate"}
        for _, tool in loaded.tools:
            spec = importlib.util.spec_from_file_location("rng_script_under_test", tool.script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            parser = module.build_parser()
            options = {option for action in parser._actions for option in action.option_strings}
            assert all(field.flag in options for field in tool.fields)
        package = plugin_store.pack(str(PLUGIN), str(tmp_path / "rng.pokeplugin"))
        assert (package.id, package.api) == ("frlg-rng-assist", (1, 8))
        assert not any(".s" == Path(member).suffix for member in package.members)
        assert not any("tests/" in member.replace("\\", "/") for member in package.members)
    finally:
        plugins._reset()


def test_public_progress_and_panels_accept_a_report(capsys):
    pytest.importorskip("pokeldn.panel")
    from frlg_rng_assist_core.reporting import show_progress, show_report
    show_progress(5, 10)
    show_report(search(0, 0, 0, advances=1))
    output = capsys.readouterr().out
    assert "[progress]" in output and "[panel]" in output


def test_real_host_launcher_runs_plugin_without_network(tmp_path):
    pytest.importorskip("pokeldn.plugins")
    import pokeldn
    host = Path(pokeldn.__file__).resolve().parents[1]
    env = dict(os.environ, POKELDN_DATA=str(tmp_path / "app-data"), POKELDN_PLUGINS=str(PLUGIN),
               PYTHONPATH=str(host))
    report = tmp_path / "report.json"
    run = subprocess.run([sys.executable, "-m", "pokeldn", "frlg-rng-assist-search", "--",
                          "--seed", "12345678", "--tid", "50425", "--sid", "50923",
                          "--advances", "8", "--output", str(report)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(report.read_text())["candidates_tested"] == 8
