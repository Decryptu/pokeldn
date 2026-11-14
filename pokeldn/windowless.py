"""Starts other programs with no window on Windows (tests/test_windowless.py holds every launch to it).

pokeldn.exe is GUI-subsystem, and so are its runs, which start pokeldn.exe itself (scripts/pack_app.py,
pokeldn/app/runner.py): neither has a console. A console program either one starts without
CREATE_NO_WINDOW opens a console window of its own, which flashes open and shut.
"""

import subprocess
import sys

NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}