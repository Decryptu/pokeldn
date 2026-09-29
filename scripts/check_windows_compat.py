#!/usr/bin/env python3
"""Flags source lines that assume a POSIX host, for review after pulling upstream changes.

None of these are wrong by themselves - much of pokeldn's Linux Wi-Fi-card and Pi code is
POSIX-only on purpose, guarded right there by a `board_radio()` or `sys.platform` check a human
reviewer can see. This only saves the search: it prints every match with its line and file, so a
merge that adds a NEW unguarded use is easy to spot instead of hiding in a large diff. It always
exits 0; it is a worklist, not a gate.

    ./.venv/bin/python scripts/check_windows_compat.py                  # every tracked .py file
    ./.venv/bin/python scripts/check_windows_compat.py --since 672e690  # lines added since a ref
    ./.venv/bin/python scripts/check_windows_compat.py --since A --until B  # lines added in A..B
    ./.venv/bin/python scripts/check_windows_compat.py bin/new_thing.py # specific files, in full
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (pattern, what to check). A hit is a place to read, not necessarily a bug - see pokeldn's own
# guarded uses of several of these (transport.py's AF_PACKET path, esp32_wlan.py's SERIAL_PORT_GLOBS).
PATTERNS = [
    (re.compile(r"^\s*import fcntl\b"),
     "fcntl is POSIX-only; import it inside the one function that needs it, not at module scope "
     "(vendor/LDN/ldn/wlan.py's create_tap does this)"),
    (re.compile(r"^\s*import termios\b"), "termios is POSIX-only"),
    (re.compile(r"^\s*import pwd\b"),
     "pwd is POSIX-only; guard it (host_support.resolve_keys wraps its use in try/except ImportError)"),
    (re.compile(r"^\s*import grp\b"), "grp is POSIX-only"),
    (re.compile(r"\bos\.pipe\("),
     "os.pipe()'s read end cannot be passed to select()/wait_readable() on Windows "
     "(userspace_ip._Readable branches to socket.socketpair() there instead)"),
    (re.compile(r"\bAF_PACKET\b"), "AF_PACKET is a Linux-only socket family; needs a platform guard"),
    (re.compile(r"\bSO_BINDTODEVICE\b"), "SO_BINDTODEVICE is a Linux-only sockopt"),
    (re.compile(r"/dev/(?!null)\S*"), "a /dev/... path; will not exist on Windows"),
    (re.compile(r"/sys/class/\S*"), "a /sys/class/... path; will not exist on Windows"),
    (re.compile(r"\bsubprocess\.\w+\(\s*\[?[\"'](?:iw|ip|nmcli|sysctl|modprobe)\b"),
     "shells out to a Linux network tool"),
    (re.compile(r"\bos\.geteuid\(\)"),
     "os.geteuid(): fine as-is - pokeldn/__init__.py shims it to 0 when absent (Windows)"),
]


def scan(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, note in PATTERNS:
            if pattern.search(line):
                hits.append((lineno, line.strip(), note))
    return hits


def scan_added_lines(ref: str, until: str = None):
    """Only the lines a merge/rebase since `ref` actually ADDS, keyed by their new line number -
    not every pre-existing hit in a file the merge happened to touch. `--unified=0` keeps each hunk
    to just its changed lines, so the running new-line counter from `@@ -a,b +c,d @@` stays exact.
    `until` defaults to the working tree; pass it to check a specific range instead (e.g. someone
    else's commits, excluding your own on top)."""
    range_args = [ref, until] if until else [ref]
    out = subprocess.run(["git", "diff", "--unified=0", "--diff-filter=ACM", *range_args, "--", "*.py"],
                          cwd=ROOT, capture_output=True, text=True, check=True)
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    results = {}
    path = None
    lineno = None
    for line in out.stdout.splitlines():
        if line.startswith("+++ "):
            p = line[4:]
            path = None if p == "/dev/null" else ROOT / p[2:]  # strip git's "b/" prefix
        elif line.startswith("@@ "):
            m = hunk_re.match(line)
            lineno = int(m.group(1)) if m else None
        elif line.startswith("+") and not line.startswith("+++") and path is not None and lineno is not None:
            text = line[1:]
            for pattern, note in PATTERNS:
                if pattern.search(text):
                    results.setdefault(path, []).append((lineno, text.strip(), note))
            lineno += 1
    return results


def all_tracked():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / p for p in out.stdout.splitlines() if p]


def report(results):
    total = 0
    for path, hits in results.items():
        rel = path.relative_to(ROOT) if path.is_absolute() else path
        print(f"\n{rel}")
        for lineno, line, note in hits:
            print(f"  {lineno}: {line}")
            print(f"      -> {note}")
        total += len(hits)
    print(f"\n{total} line(s) flagged for a Windows read-through." if total else "\nNothing flagged.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="specific files to scan whole (every hit, not just new ones)")
    ap.add_argument("--since", metavar="REF",
                    help="merge-review mode: only lines `git diff` shows ADDED since REF, not every "
                         "pre-existing hit in a file the merge happened to touch")
    ap.add_argument("--until", metavar="REF", help="with --since: check REF..UNTIL instead of REF..working tree")
    args = ap.parse_args(argv)

    if args.since:
        report(scan_added_lines(args.since, args.until))
        return 0

    paths = [Path(f) for f in args.files] if args.files else all_tracked()
    results = {}
    for path in paths:
        if path.suffix != ".py" or not path.exists():
            continue
        hits = scan(path)
        if hits:
            results[path] = hits
    report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
