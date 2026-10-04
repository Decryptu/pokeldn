"""Import paths for tests: bin/, the tools/ subdirectories and the repo root."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

for path in (os.path.join(ROOT, "tools", "frlg"), os.path.join(ROOT, "tools", "ldn"), os.path.join(ROOT, "tools", "switch"),
             os.path.join(ROOT, "bin"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

# A live run's variables left in the shell send the host runtime down the board path (and hang it);
# pokeldn.app.paths reads POKELDN_DATA at import, so they go before any test module loads.
for name in ("POKELDN_RADIO", "POKELDN_ESP32_TRACE", "POKELDN_ESP32_BAUD", "POKELDN_ESP32_AP_FLAGS",
             "POKELDN_ESP32_AP_FLAGS2", "POKELDN_L2", "POKELDN_MANAGED_RUN", "POKELDN_DATA"):
    os.environ.pop(name, None)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_trade_count():
    """A run is one process; each test starts with no completed trade (pokeldn.ldn.trades_done)."""
    import pokeldn.ldn
    pokeldn.ldn._done.clear()
    yield
