"""Opt-in, local file gate for controlled P0 phase-delay tests."""

from pathlib import Path
import time

from pokeldn.frlg.remote.protocol import PHASE_ORDER


class FilePhaseGate:
    """Hold delivery of one peer block until a local release file is created."""

    def __init__(self, phase, release_file):
        if phase not in PHASE_ORDER:
            raise ValueError(f"phase must be one of {', '.join(PHASE_ORDER)}")
        self.phase = phase
        self.release_file = Path(release_file).expanduser().resolve()
        if self.release_file.exists():
            raise ValueError("phase gate release file already exists; choose a fresh path")
        self.release_file.parent.mkdir(parents=True, exist_ok=True)
        self._held = False
        self._released = False
        self._next_check = 0.0

    @property
    def held(self):
        return self._held

    @property
    def released(self):
        return self._released

    def poll(self, phase):
        """Return open, held, or released without blocking the RFU owner thread."""
        if phase != self.phase or self._released:
            return "open"
        self._held = True
        now = time.monotonic()
        if now < self._next_check:
            return "held"
        self._next_check = now + 0.1
        if self.release_file.exists():
            self._released = True
            return "released"
        return "held"
