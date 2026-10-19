"""The app's copies of the raid events of Project Pokemon's EventsGallery, one per game: where each
lives, downloading it, checking for and taking its updates, and the index of its events. docs/gui.md
(Raid events).

A copy is GitHub's zip of the gallery unpacked to what the game's reader takes: for Scarlet/Violet
(`sv`) the four tables `pokeldn.sv.raid_event` reads of each event's newest patch, as
`<event>/Files/<table>`; for Sword/Shield (`swsh`) the files `pokeldn.swsh.raid_event` reads of each
Wild Area Event index, as `Index NNN/<file>`, and the gallery's `readme.md` naming the indexes.
`gallery.json` beside them names the newest raid event change the copy holds.
"""
import json
import os
import re
import shutil
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from pokeldn.app import archives, paths, update
from pokeldn.sv import raid_event
from pokeldn.swsh import raid_event as swsh_event

REPOSITORY = "projectpokemon/EventsGallery"
API = f"https://api.github.com/repos/{REPOSITORY}"
ZIP = f"https://codeload.github.com/{REPOSITORY}/zip/{{commit}}"
BRANCH = "master"
RAID_EVENTS = "Released/Gen 9/SV/Raid Events"
FOLDER = "EventsGallery"
SWSH_EVENTS = "Released/Gen 8/SwSh/Wild Area Events"
SWSH_FOLDER = "EventsGallery SwSh"
README = "readme.md"
MANIFEST = "gallery.json"
PLACEHOLDER = "000 Base Data"     # the game's own table, no delivery
TABLES = (raid_event.ENEMY, raid_event.FIXED, raid_event.LOTTERY, raid_event.PRIORITY)
TIMEOUT = 10.0
MAX_FILES = 100_000
MAX_TABLE = 8 << 20
MAX_UNPACKED = 256 << 20

Progress = Callable[[str, int, int], None]   # what is happening, bytes done, bytes in all (0 unknown)


@dataclass(frozen=True)
class Game:
    events: str             # the gallery's folder of the game's raid events
    folder: str             # the copy's folder in the app's data folder
    wanted: Callable        # the gallery's file paths -> {path under the copy: path in the gallery}
    marker: str             # what an event's folder holds


def location(game: str = "sv") -> Path:
    """The app's data folder's copy for `game`; `POKELDN_DATA` moves it with the rest."""
    return paths.DATA / GAMES[game].folder


def _home(game: str) -> Path:
    # As _event, for location.
    return location() if game == "sv" else location(game)


def long_path(path) -> str:
    """-> the path as Windows opens it past 260 characters (the \\\\?\\ form); elsewhere as it is. An
    event's name reaches 152 characters."""
    text = os.path.abspath(str(path))
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    return "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text


def event_path(key: str, root: Path | None = None, game: str = "sv") -> str:
    """-> the folder of an event the index named, as `bin/sv_host.py --raid-event` and
    `bin/swsh_host.py --raid-event` take it."""
    return long_path((_home(game) if root is None else Path(root)) / key)


def _event(key: str, root: Path | None, game: str) -> str:
    # Scarlet/Violet calls keep the two-argument form the app's views and tests replace.
    return event_path(key, root) if game == "sv" else event_path(key, root, game)


def present(root: Path | None = None, game: str = "sv") -> bool:
    return state(root, game).present


def holds(key: str, root: Path | None = None, game: str = "sv") -> bool:
    """Whether the copy holds the event an index entry named: none is downloaded, or an update can
    drop one."""
    return os.path.exists(os.path.join(_event(key, root, game), GAMES[game].marker))


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


def state(root: Path | None = None, game: str = "sv") -> State:
    root = _home(game) if root is None else Path(root)
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


def _latest(game: str = "sv") -> tuple[str, str]:
    """-> (the newest commit of master that changed the game's raid events, its date)."""
    events = urllib.parse.quote(GAMES[game].events)
    found = update.github_json(f"{API}/commits?sha={BRANCH}&per_page=1&path={events}", TIMEOUT, "commit")
    try:
        return found[0]["sha"], found[0]["commit"]["committer"]["date"]
    except (KeyError, IndexError, TypeError) as error:
        raise OSError("GitHub sent no commit") from error


def _newest(game: str) -> tuple[str, str]:
    # As _event, for _latest.
    return _latest() if game == "sv" else _latest(game)


def check(root: Path | None = None, game: str = "sv") -> Check:
    """Whether master has a raid event change the copy lacks; a change elsewhere in the gallery is none."""
    found = state(root, game)
    if not found.present:
        raise OSError("the event gallery is not downloaded")
    commit, date = _newest(game)
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


def swsh_files(names) -> dict[str, str]:
    """-> {path under the copy: path in the gallery} of every Wild Area Event index's files and the
    readme naming the indexes, among the gallery's file paths."""
    out = {}
    for name in names:
        rest = name.partition(SWSH_EVENTS + "/")[2]
        key, _, file = rest.rpartition("/")
        if rest == README:
            out[README] = name
        elif key and "/" not in key and key not in ("..", ".") and file in swsh_event.FILES:
            out[f"{key}/{file}"] = name
    return out if any(path != README for path in out) else {}


def extract(archive: Path, folder: Path, game: str = "sv") -> int:
    """Unpacks every event's files the game reads from GitHub's zip of the gallery (whose entries sit
    under one top folder); -> how many files."""
    with archives.open_zip(archive, MAX_FILES) as z:
        if len(z.infolist()) > MAX_FILES:
            raise OSError("the gallery holds too many files")
        for info in z.infolist():
            archives.relative(info.filename)
        inside = {info.filename.partition("/")[2]: info for info in z.infolist() if not info.is_dir()}
        wanted = GAMES[game].wanted(inside)
        archives.bounded(((path, inside[name].file_size, inside[name]) for path, name in wanted.items()),
                         MAX_FILES, MAX_UNPACKED, MAX_TABLE)
        for path, name in wanted.items():
            target = long_path(archives.destination(folder, path))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(inside[name]) as source, open(target, "wb") as out:
                archives.copy(source, out, inside[name].file_size)
    if not wanted:
        raise OSError("the download holds no raid events")
    return len(wanted)


# --- Downloading and updating ----------------------------------------------------------------------

def download(root: Path | None = None, progress: Progress = lambda text, done, total: None,
             cancelled: Callable[[], bool] = lambda: False, game: str = "sv") -> State:
    """Puts master's raid events at `root`, a first copy or an update; a copy there is replaced only
    once the new one is complete."""
    root = _home(game) if root is None else Path(root)
    progress("Asking GitHub for the latest raid events...", 0, 0)
    commit, date = _newest(game)
    work = root.parent / f".{root.name}.download"
    shutil.rmtree(long_path(work), ignore_errors=True)
    fresh = work / root.name
    fresh.mkdir(parents=True)
    try:
        archive = work / "gallery.zip"
        update.fetch(ZIP.format(commit=commit), archive,
                     lambda done, total: progress("Downloading the event gallery...", done, total), cancelled)
        progress("Unpacking the raid events...", 0, 0)
        extract(archive, fresh, game)
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
    return state(root, game)


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


def title(key: str, game: str = "sv") -> str:
    if game == "swsh":
        try:
            return titles(Path(long_path(_home(game)), README).read_text(encoding="utf-8-sig")).get(key, key)
        except OSError:
            return key
    return " · ".join(re.sub(r"^\d+\s*", "", part) for part in key.split("/"))


def titles(text: str) -> dict[str, str]:
    """-> {"Index NNN": the event's name} from the Sword/Shield gallery's readme: its index list names
    each index's event number, and the event's heading its name."""
    names = {}
    for line in text.splitlines():
        heading = re.match(r"^##\s*\[(Wild Area Event #(\d+)[^\]]*)\]", line)
        if heading:
            names.setdefault(int(heading.group(2)), heading.group(1))
    out = {}
    for key, event in re.findall(r"^- \[(Index [^\]]+)\]\([^)]*\) - \[([^\]]+)\]", text, re.M):
        number = re.search(r"#(\d+)", event)
        out.setdefault(key, names.get(int(number.group(1)), event) if number else event)
    return out


def _swsh_index(root: Path) -> list[Entry]:
    base = long_path(root)
    try:
        named = titles(Path(base, README).read_text(encoding="utf-8-sig"))
    except OSError:
        named = {}
    found = []
    for folder in swsh_event.deliveries(base):
        key = os.path.relpath(folder, base).replace(os.sep, "/")
        try:
            event = load(key, root, "swsh")
        except (OSError, ValueError):
            continue
        number = re.search(r"\d+", key)
        found.append(Entry(key, named.get(key, key), int(number.group()) if number else -1,
                           tuple(dict.fromkeys(b.name for b in event.bosses)), (), event.index))
    found.sort(key=lambda e: (e.number, e.key))
    return found


def index(root: Path | None = None, game: str = "sv") -> list[Entry]:
    """-> the copy's raid events, oldest first."""
    root = _home(game) if root is None else Path(root)
    base = long_path(root)
    if (game, base) in _INDEX:
        return _INDEX[(game, base)]
    if game == "swsh":
        _INDEX[(game, base)] = _swsh_index(root)
        return _INDEX[(game, base)]
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
    _INDEX[(game, base)] = found
    return found


def load(key: str, root: Path | None = None, game: str = "sv"):
    """-> the event an index entry names, read once: a `pokeldn.sv.raid_event.Event` or a
    `pokeldn.swsh.raid_event.Event`."""
    folder = _event(key, root, game)
    if (game, folder) not in _EVENTS:
        _EVENTS[(game, folder)] = (swsh_event if game == "swsh" else raid_event).load(folder)
    return _EVENTS[(game, folder)]


GAMES = {
    "sv": Game(RAID_EVENTS, FOLDER, newest_tables, "Files"),
    "swsh": Game(SWSH_EVENTS, SWSH_FOLDER, swsh_files, swsh_event.AREAS[0][0]),
}
