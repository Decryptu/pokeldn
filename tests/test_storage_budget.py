"""The storage guard: an over-budget folder stops new work and leaves the cleanup commands free."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import storage_budget  # noqa: E402

BUDGETS = {"scratchpad": 1 << 16, "captures": 1 << 16}


def filled(root, size):
    (root / "scratchpad/run").mkdir(parents=True)
    (root / "scratchpad/run/capture.bin").write_bytes(os.urandom(size))


def test_a_folder_over_budget_is_found_and_a_link_to_a_dump_costs_nothing(tmp_path):
    (tmp_path / "scratchpad").mkdir()
    dump = tmp_path / "elsewhere.bin"
    dump.write_bytes(os.urandom(1 << 18))
    (tmp_path / "scratchpad/game.xci").symlink_to(dump)
    state = storage_budget.measure(tmp_path, BUDGETS)
    assert not storage_budget.problems(state, BUDGETS, min_free=0)

    (tmp_path / "scratchpad/copy.xci").write_bytes(dump.read_bytes())
    state = storage_budget.measure(tmp_path, BUDGETS)
    found = storage_budget.problems(state, BUDGETS, min_free=0)
    assert len(found) == 1 and found[0].startswith("scratchpad/")


def test_a_full_disk_is_found_with_empty_folders(tmp_path):
    state = storage_budget.measure(tmp_path, BUDGETS)
    state["free"] = 1
    assert storage_budget.problems(state, BUDGETS, min_free=2)


def test_a_stale_measurement_is_taken_again(tmp_path):
    cache = tmp_path / "cache/state.json"
    assert storage_budget.cached(tmp_path, cache, BUDGETS)["used"]["scratchpad"] == 0
    filled(tmp_path, 1 << 17)
    assert storage_budget.cached(tmp_path, cache, BUDGETS)["used"]["scratchpad"] == 0

    state = json.loads(cache.read_text())
    state["at"] -= storage_budget.CACHE_SECONDS + 1
    cache.write_text(json.dumps(state))
    assert storage_budget.cached(tmp_path, cache, BUDGETS)["used"]["scratchpad"] >= 1 << 17


def test_only_cleanup_gets_past_the_guard():
    for command in ("du -sh scratchpad/*", "cd /repo; rm -rf scratchpad/old && du -sh scratchpad",
                    "ls -la captures | head", "git status", "python3 scripts/storage_budget.py"):
        assert storage_budget.is_cleanup(command), command
    for command in ("./scratchpad/run_swsh_board.sh sx1 6", "du -sh x; cp -R a scratchpad/b",
                    "./.venv/bin/python bin/swsh_host.py", "rm a && unzip dump.zip"):
        assert not storage_budget.is_cleanup(command), command


def test_the_hook_refuses_with_exit_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(storage_budget, "cached", lambda: {
        "used": {"scratchpad": 1 << 40, "captures": 0}, "free": 1 << 40, "at": 0})
    for command, code in (("cp a scratchpad/b", 2), ("du -sh scratchpad", 0)):
        stdin = tmp_path / "in.json"
        stdin.write_text(json.dumps({"tool_input": {"command": command}}))
        with stdin.open() as f:
            monkeypatch.setattr(sys, "stdin", f)
            assert storage_budget.main(["--hook", "bash"]) == code
    assert "storage budget" in capsys.readouterr().err
