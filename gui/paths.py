import os
import sys
from pathlib import Path

# A PyInstaller bundle unpacks the repository's folders under sys._MEIPASS.
ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for folder in (ROOT, os.path.join(ROOT, "vendor", "LDN")):
    if folder not in sys.path:
        sys.path.insert(0, folder)


def _data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "pokeldn"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "pokeldn"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "pokeldn"


DATA = _data_dir()                              # settings, built Pokemon, session records
SESSION = DATA / "session"                      # the working directory of every run
POKEMON = DATA / "pokemon"
LOGS = DATA / "logs"
RECEIVED = (Path.home() / "Documents" if (Path.home() / "Documents").is_dir() else Path.home()) \
    / "pokeldn" / "Received"
