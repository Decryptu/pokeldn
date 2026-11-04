#!/usr/bin/env python3
"""How much of this Mac the repository's working folders take, against their budgets.

    python3 scripts/storage_budget.py          # sizes, largest folders; exit 1 when over budget
    --hook session | --hook bash               # the Claude Code hooks in .claude/settings.json

CLAUDE.md, Storage budget. Standard library only: /usr/bin/python3 runs it as a hook.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIB = 1 << 30
BUDGETS = {"scratchpad": 20 * GIB, "captures": 2 * GIB}
MIN_FREE = 30 * GIB
WARN_AT = 0.8
CACHE = Path.home() / ".cache/pokeldn/storage_budget.json"
CACHE_SECONDS = 300
# What an agent may still run when over budget: look, delete, move out, commit.
CLEANUP = {"cd", "du", "df", "ls", "rm", "rmdir", "mv", "find", "stat", "cat", "head", "tail", "grep",
           "git", "true", "sort", "wc"}


def on_disk(stat):
    """Bytes a file takes; Windows reports no blocks, only its length."""
    return stat.st_blocks * 512 if hasattr(stat, "st_blocks") else stat.st_size


def folder_size(path):
    """Bytes on disk under `path`; a symlink counts as itself, so a link to a dump costs nothing."""
    total, stack = 0, [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        total += on_disk(entry.stat(follow_symlinks=False))
        except OSError:
            continue
    return total


def measure(root=ROOT, budgets=BUDGETS):
    used = {name: folder_size(Path(root) / name) for name in budgets}
    return {"used": used, "free": shutil.disk_usage(root).free, "at": time.time()}


def cached(root=ROOT, cache=CACHE, budgets=BUDGETS):
    """A measurement at most CACHE_SECONDS old: the Bash hook runs before every command."""
    try:
        state = json.loads(Path(cache).read_text())
        if time.time() - state["at"] < CACHE_SECONDS:
            return state
    except (OSError, ValueError, KeyError):
        pass
    state = measure(root, budgets)
    Path(cache).parent.mkdir(parents=True, exist_ok=True)
    Path(cache).write_text(json.dumps(state))
    return state


def problems(state, budgets=BUDGETS, min_free=MIN_FREE, warn_at=1.0):
    found = [f"{name}/ holds {state['used'][name] / GIB:.1f} GiB of its {limit / GIB:.0f} GiB budget"
             for name, limit in budgets.items() if state["used"].get(name, 0) >= limit * warn_at]
    if state["free"] < min_free / warn_at:
        found.append(f"the disk has {state['free'] / GIB:.1f} GiB free, the floor is {min_free / GIB:.0f} GiB")
    return found


def is_cleanup(command):
    """True when every step of a shell command only looks, deletes, moves or uses git."""
    steps = [s.strip() for s in re.split(r"[;\n|&]+", command) if s.strip()]
    return all(s.split()[0].rsplit("/", 1)[-1] in CLEANUP or "storage_budget.py" in s for s in steps)


def largest(root=ROOT, budgets=BUDGETS, count=10):
    folders = [p for name in budgets if (Path(root) / name).is_dir() for p in (Path(root) / name).iterdir()]
    sizes = [(folder_size(p) if p.is_dir() and not p.is_symlink() else on_disk(p.lstat()), p)
             for p in folders]
    return sorted(sizes, key=lambda item: -item[0])[:count]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hook", choices=("session", "bash"))
    args = ap.parse_args(argv)
    if args.hook == "session":
        found = problems(cached(), warn_at=WARN_AT)
        if found:
            print("Storage budget, CLAUDE.md: " + "; ".join(found)
                  + ". Run scripts/storage_budget.py and clean up before new work.")
        return 0
    if args.hook == "bash":
        found = problems(cached())
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
        if found and not is_cleanup(command):
            print("Refused by the storage budget (CLAUDE.md): " + "; ".join(found)
                  + ". Only du, ls, find, rm, mv and git run until it is back under. Run "
                  "scripts/storage_budget.py for the largest folders, delete what can be rebuilt, "
                  "and ask Decrypt about anything else.", file=sys.stderr)
            return 2
        return 0
    state = measure()
    for name, limit in BUDGETS.items():
        print(f"{name + '/':12} {state['used'][name] / GIB:7.2f} GiB of {limit / GIB:.0f}")
    print(f"{'disk free':12} {state['free'] / GIB:7.2f} GiB, floor {MIN_FREE / GIB:.0f}")
    for size, path in largest():
        print(f"{size / GIB:8.2f} GiB  {path.relative_to(ROOT)}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(state))
    return 1 if problems(state) else 0


if __name__ == "__main__":
    sys.exit(main())
