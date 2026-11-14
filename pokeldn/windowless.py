"""Keyword arguments that start a program with no console window on Windows.

pokeldn.exe and its runs are GUI-subsystem with no console (scripts/pack_app.py), so a console program
they start without CREATE_NO_WINDOW opens a window of its own. tests/test_windowless.py holds every launch to it.
"""

import subprocess
import sys

NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
