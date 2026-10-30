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
             "POKELDN_ESP32_AP_FLAGS2", "POKELDN_L2", "POKELDN_MANAGED_RUN", "POKELDN_POPUPS", "POKELDN_DATA"):
    os.environ.pop(name, None)


import pytest  # noqa: E402


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    # Windows unicorn commits its code buffer from a vectored handler on each access violation;
    # faulthandler's handler runs first and walks every thread's frames without the GIL
    # (unicorn-engine/unicorn#2264), which now and then faults inside a uc_mem_map call.
    if sys.platform == "win32":
        import faulthandler
        faulthandler.disable()


@pytest.fixture(autouse=True)
def _fresh_run_state():
    """A run is one process; each test starts with no completed trade (pokeldn.ldn.trades_done) and no
    trainer already printed (pokeldn.console_trainer.show prints each once per process)."""
    import pokeldn.ldn
    from pokeldn import console_trainer
    pokeldn.ldn._done.clear()
    pokeldn.ldn._done_at = None
    console_trainer._shown.clear()
    yield
