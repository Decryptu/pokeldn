"""Import paths for tests: bin/, the tools/ subdirectories and the repo root."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

for path in (os.path.join(ROOT, "tools", "frlg"), os.path.join(ROOT, "tools", "ldn"), os.path.join(ROOT, "tools", "switch"),
             os.path.join(ROOT, "bin"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
