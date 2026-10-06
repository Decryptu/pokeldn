"""Where scripts/build_client.py puts the Flet client that takes file drops (gui/drop.py).
No Flet import: the packer and the build script read it without the GUI dependencies."""
import shutil
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


def prune_cache() -> list[Path]:
    """Removes the viewers earlier builds of the frozen app unpacked into ~/.flet/client: Flet unpacks
    one per build and never deletes any. Another Flet app's viewer carries no marker and stays."""
    import flet_desktop
    current = flet_desktop.ensure_client_cached()
    (current / MARKER).touch()
    removed = []
    for folder in current.parent.iterdir():
        # Builds before the marker are known on macOS by the bundle the packer renamed.
        if folder != current and folder.is_dir() and ((folder / MARKER).is_file() or (folder / "pokeldn.app").is_dir()):
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(folder)
    return removed
