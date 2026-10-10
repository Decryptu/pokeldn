"""The app's copy of the Scarlet/Violet raid events of Project Pokemon's EventsGallery: where it lives,
downloading it, checking for and taking its updates, and the index of its events. docs/gui.md (Raid
events).

The copy is GitHub's zip of the gallery unpacked to the four tables `pokeldn.sv.raid_event` reads of
each event's newest patch, as `<event>/Files/<table>`; `gallery.json` beside them names the newest
raid event change it holds.
"""
import json
import os
import re
import shutil
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from pokeldn.app import paths, update
from pokeldn.sv import raid_event

REPOSITORY = "projectpokemon/EventsGallery"
API = f"https://api.github.com/repos/{REPOSITORY}"
ZIP = f"https://codeload.github.com/{REPOSITORY}/zip/{{commit}}"
BRANCH = "master"
RAID_EVENTS = "Released/Gen 9/SV/Raid Events"
FOLDER = "EventsGallery"
MANIFEST = "gallery.json"
PLACEHOLDER = "000 Base Data"     # the game's own table, no delivery
TABLES = (raid_event.ENEMY, raid_event.FIXED, raid_event.LOTTERY, raid_event.PRIORITY)
TIMEOUT = 10.0

Progress = Callable[[str, int, int], None]   # what is happening, bytes done, bytes in all (0 unknown)


def location() -> Path:
    """The app's data folder's EventsGallery; `POKELDN_DATA` moves it with the rest."""
    return paths.DATA / FOLDER


def long_path(path) -> str:
    """-> the path as Windows opens it past 260 characters (the \\\\?\\ form); elsewhere as it is. An
    event's name reaches 152 characters."""
    text = os.path.abspath(str(path))
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    return "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text


def event_path(key: str, root: Path | None = None) -> str:
    """-> the folder of an event the index named, as `bin/sv_host.py --raid-event` takes it."""
    return long_path((location() if root is None else Path(root)) / key)


def present(root: Path | None = None) -> bool:
    return state(root).present


def holds(key: str, root: Path | None = None) -> bool:
    """Whether the copy holds the event an index entry named: none is downloaded, or an update can
    drop one."""
    return os.path.isdir(os.path.join(event_path(key, root), "Files"))


# --- What is there ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class State:
    present: bool
    commit: str = ""        # the newest raid event change the copy holds
    date: str = ""          # its date, ISO 8601


@dataclass(frozen=True)
class Check:
    available: bool
    commit: str             # the newest raid event change on master
    date: str


def state(root: Path | None = None) -> State:
    root = location() if root is None else Path(root)
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        return State(True, str(manifest["commit"]), str(manifest["date"]))
    except (OSError, ValueError, KeyError, TypeError):
        return State(False)


def date_of(date: str) -> datetime | None:
    """-> an ISO 8601 date as GitHub writes it, or None."""
    try:
        return datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest() -> tuple[str, str]:
    """-> (the newest commit of master that changed the raid events, its date)."""
    found = update.github_json(f"{API}/commits?sha={BRANCH}&per_page=1&path={urllib.parse.quote(RAID_EVENTS)}",
                               TIMEOUT, "commit")
    try:
        return found[0]["sha"], found[0]["commit"]["committer"]["date"]
    except (KeyError, IndexError, TypeError) as error:
        raise OSError("GitHub sent no commit") from error


def check(root: Path | None = None) -> Check:
    """Whether master has a raid event change the copy lacks; a change elsewhere in the gallery is none."""
    found = state(root)
    if not found.present:
        raise OSError("the event gallery is not downloaded")
    commit, date = _latest()
    return Check(commit != found.commit, commit, date)


def newest_tables(names) -> dict[str, str]:
    """-> {path under the copy: path in the gallery} of every event's newest tables among the
    gallery's file paths."""
    events: dict[str, set] = {}
    for name in names:
        key, files, table = name.partition(RAID_EVENTS + "/")[2].rpartition("/Files/")
        if files and key.split("/")[0] != PLACEHOLDER and ".." not in key.split("/"):
            events.setdefault(key, set()).add(table)
    out = {}
    for key, tables in events.items():
        patch = next((p for p in raid_event.PATCHES if raid_event.ENEMY + p in tables), None)
        for table in TABLES if patch is not None else ():
            if table + patch in tables:
                out[f"{key}/Files/{table}{patch}"] = f"{RAID_EVENTS}/{key}/Files/{table}{patch}"
    return out


def extract(archive: Path, folder: Path) -> int:
    """Unpacks every event's newest tables from GitHub's zip of the gallery (whose entries sit under
    one top folder); -> how many files."""
    with zipfile.ZipFile(archive) as z:
        inside = {info.filename.partition("/")[2]: info for info in z.infolist() if not info.is_dir()}
        wanted = newest_tables(inside)
        for path, name in wanted.items():
            target = long_path(folder / path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(inside[name]) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
    if not wanted:
        raise OSError("the download holds no raid events")
    return len(wanted)


# --- Downloading and updating ----------------------------------------------------------------------

def download(root: Path | None = None, progress: Progress = lambda text, done, total: None,
             cancelled: Callable[[], bool] = lambda: False) -> State:
    """Puts master's raid events at `root`, a first copy or an update; a copy there is replaced only
    once the new one is complete."""
    root = location() if root is None else Path(root)
    progress("Asking GitHub for the latest raid events...", 0, 0)
    commit, date = _latest()
    work = root.parent / f".{root.name}.download"
    shutil.rmtree(long_path(work), ignore_errors=True)
    fresh = work / root.name
    fresh.mkdir(parents=True)
    try:
        archive = work / "gallery.zip"
        update.fetch(ZIP.format(commit=commit), archive,
                     lambda done, total: progress("Downloading the event gallery...", done, total), cancelled)
        progress("Unpacking the raid events...", 0, 0)
        extract(archive, fresh)
        (fresh / MANIFEST).write_text(json.dumps({"commit": commit, "date": date}), encoding="utf-8")
        old = root.parent / f".{root.name}.old"
        shutil.rmtree(long_path(old), ignore_errors=True)
        if root.exists():
            os.rename(root, old)
        os.rename(fresh, root)
        shutil.rmtree(long_path(old), ignore_errors=True)
    finally:
        shutil.rmtree(long_path(work), ignore_errors=True)
    forget()
    return state(root)


# --- The raid events -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    key: str                # its folder, with "/"
    title: str              # the folder's name without its number; a round, "Event · Round"
    number: int
    species: tuple          # boss names, table order
    catch_once: tuple       # the bosses a save catches once
    identifier: int


_INDEX: dict = {}
_EVENTS: dict = {}


def forget() -> None:
    """Drops what was read of the copy, after it changed."""
    _INDEX.clear()
    _EVENTS.clear()


def title(key: str) -> str:
    return " · ".join(re.sub(r"^\d+\s*", "", part) for part in key.split("/"))


def index(root: Path | None = None) -> list[Entry]:
    """-> the copy's raid events, oldest first."""
    root = location() if root is None else Path(root)
    base = long_path(root)
    if base in _INDEX:
        return _INDEX[base]
    found = []
    for folder in raid_event.deliveries(base):
        key = os.path.relpath(folder, base).replace(os.sep, "/")
        try:
            event = load(key, root)
        except (OSError, ValueError):
            continue        # a folder that holds no readable delivery
        number = re.match(r"\d+", key)
        found.append(Entry(key, title(key), int(number.group()) if number else -1,
                           tuple(raid_event.bosses(r for r in event.rows if r["rate"])),
                           tuple(raid_event.catch_once(event)), event.identifier))
    found.sort(key=lambda e: (e.number, e.key))
    _INDEX[base] = found
    return found


def load(key: str, root: Path | None = None) -> raid_event.Event:
    """-> the event an index entry names, read once."""
    folder = event_path(key, root)
    if folder not in _EVENTS:
        _EVENTS[folder] = raid_event.load(folder)
    return _EVENTS[folder]
