import os
import sys
from pathlib import Path

# A PyInstaller bundle unpacks the repository's folders under sys._MEIPASS.
ROOT = getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parents[2]))
for folder in (ROOT, os.path.join(ROOT, "vendor", "LDN")):
    if folder not in sys.path:
        sys.path.insert(0, folder)

# The bundle's libstdc++ on LD_LIBRARY_PATH aborts the Flet viewer in libepoxy on Fedora 44; keep the
# bundled viewer instead of a downloaded one. docs/gui.md, Build a desktop app.
if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    if "LD_LIBRARY_PATH_ORIG" in os.environ:
        os.environ["LD_LIBRARY_PATH"] = os.environ.pop("LD_LIBRARY_PATH_ORIG")
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)
    for _client in Path(ROOT, "flet_desktop", "app").glob("flet-linux-*-light-*.tar.gz"):
        os.environ.setdefault("FLET_LINUX_DISTRO", _client.name.split("-")[2])


def _data_dir() -> Path:
    if os.environ.get("POKELDN_DATA"):
        return Path(os.environ["POKELDN_DATA"]).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "pokeldn"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "pokeldn"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "pokeldn"


DATA = _data_dir()                              # settings, built Pokemon, session records
SESSION = DATA / "session"                      # the working directory of every run
POKEMON = DATA / "pokemon"
LOGS = DATA / "logs"
_DOCUMENTS = (Path.home() / "Documents" if (Path.home() / "Documents").is_dir() else Path.home()) / "pokeldn"
RECEIVED = _DOCUMENTS / "Received"
# FireRed/LeafGreen saves (pokeldn.app.saves); an isolated POKELDN_DATA keeps its own.
SAVES = DATA / "Saves" if os.environ.get("POKELDN_DATA") else _DOCUMENTS / "Saves"
# Pokemon kept between games (pokeldn.app.bank); an isolated POKELDN_DATA keeps its own.
BANK = DATA / "Bank" if os.environ.get("POKELDN_DATA") else _DOCUMENTS / "Bank"
# Controller macros (pokeldn.app.macros); an isolated POKELDN_DATA keeps its own.
MACROS = DATA / "Macros" if os.environ.get("POKELDN_DATA") else _DOCUMENTS / "Macros"
# GTS listings and offers with their keys and records (pokeldn.app.gts); an isolated POKELDN_DATA keeps its own.
GTS = DATA / "GTS" if os.environ.get("POKELDN_DATA") else _DOCUMENTS / "GTS"
