"""Where scripts/build_client.py puts the Flet client that takes file drops (gui/drop.py).
No Flet import: the packer and the build script read it without the GUI dependencies."""
import sys
from pathlib import Path

CLIENT = Path(__file__).resolve().parent / "client"
MARKER = "pokeldn-drop"


def platform_key() -> str:
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def view_path() -> Path | None:
    """The built client's folder as flet_desktop takes it in FLET_VIEW_PATH, or None if it is not built."""
    out = CLIENT / platform_key()
    if not (out / MARKER).is_file():
        return None
    return out if platform_key() == "macos" else out / "flet"
