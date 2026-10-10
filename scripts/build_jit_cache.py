#!/usr/bin/env python3
"""Compile the raid finder's numba scan (pokeldn.sv.raid_kernel) into a folder the packed app ships:
the app copies it where numba looks and its first search starts at once. Run by scripts/pack_app.py
with the Python and numba the app bundles; the code is for a generic CPU, so it loads on any machine
of the runner's OS and architecture."""
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder.resolve()
    shutil.rmtree(folder, ignore_errors=True)
    os.environ["POKELDN_JIT_CACHE"] = str(folder)       # before the kernel's import: its cache's place
    sys.path.insert(0, str(ROOT))
    from pokeldn.sv import raid_kernel
    if not raid_kernel.available():
        raise SystemExit("numba is missing: python -m pip install -r gui/requirements.txt")
    raid_kernel.warm()
    files = sorted(folder.iterdir())
    if not any(f.suffix == ".nbi" for f in files):
        raise SystemExit(f"numba wrote no cache in {folder}")
    print(f"Raid finder cache: {len(files)} files, {sum(f.stat().st_size for f in files) // 1024} KB in {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
