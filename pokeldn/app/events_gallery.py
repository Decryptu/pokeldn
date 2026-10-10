"""The local copy of Project Pokemon's EventsGallery the app's event raids come from: where it lives,
downloading it, checking for and taking its updates (by git when the machine has git, by GitHub's
zip of master otherwise), and the index of its Scarlet/Violet raid events. docs/gui.md (Raid events).

Only each raid event's tables (`Files/`) and pkNX's text of them (`Encounters.txt`) are kept, about a
fifth of the raid events folder; the JSON copies stay on GitHub.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from pokeldn.app import paths, update
from pokeldn.sv import raid_event

REPOSITORY = "projectpokemon/EventsGallery"
GIT_URL = f"https://github.com/{REPOSITORY}.git"
API = f"https://api.github.com/repos/{REPOSITORY}"
ZIP = f"https://codeload.github.com/{REPOSITORY}/zip/{{commit}}"
BRANCH = "master"
FOLDER = "EventsGallery"
RAID_EVENTS = "Released/Gen 9/SV/Raid Events"
SPARSE = (f"/{RAID_EVENTS}/**/Files/", f"/{RAID_EVENTS}/**/Encounters.txt")
MARKER = ".pokeldn.json"          # a zip copy's commit and the date of its last raid event change
PLACEHOLDER = "000 Base Data"     # the game's own table, no delivery
TIMEOUT = 10.0
GIT_TIMEOUT = 900.0

Progress = Callable[[str, int, int], None]   # what is happening, bytes done, bytes in all (0 unknown)


def location(frozen: bool = bool(getattr(sys, "frozen", False)), system: str = sys.platform) -> Path:
    """Where the gallery lives: beside the packed app's own files (its `_internal` folder, which an
    app update carries over) unless that folder is not writable or the app is a signed macOS bundle,
    then the app's data folder; running from source, the repository's EventsGallery/."""
    if not frozen:
        return Path(paths.ROOT) / FOLDER
    bundled, data = Path(paths.ROOT) / FOLDER, paths.DATA / FOLDER
    if system == "darwin" or data.is_dir():
        return data
    return bundled if bundled.is_dir() or update.writable(Path(paths.ROOT)) else data


def long_path(path) -> str:
    """-> the path as Windows opens it past 260 characters (the \\\\?\\ form); elsewhere as it is. An
    event's files sit some 205 characters below the gallery."""
    text = os.path.abspath(str(path))
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    return "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text


def raid_events(root: Path | None = None) -> Path:
    return (location() if root is None else Path(root)) / RAID_EVENTS


def event_path(key: str, root: Path | None = None) -> str:
    """-> the folder of an event the index named, as `bin/sv_host.py --raid-event` takes it."""
    return long_path(raid_events(root) / key)


def present(root: Path | None = None) -> bool:
    """Whether a copy is there; no git runs."""
    return os.path.isdir(long_path(raid_events(root)))


def holds(key: str, root: Path | None = None) -> bool:
    """Whether the copy holds the event an index entry named: none is downloaded, or an update can
    drop one."""
    return os.path.isdir(os.path.join(event_path(key, root), "Files"))


# --- What is there ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class State:
    present: bool
    method: str = ""        # "git" or "zip"
    commit: str = ""
    date: str = ""          # ISO 8601, the newest raid event change the copy holds


@dataclass(frozen=True)
class Check:
    available: bool
    commit: str             # master's head
    date: str               # its newest raid event change


def git() -> str | None:
    return shutil.which("git")


def _run_git(args: list[str], cwd: Path | None = None, timeout: float = 120.0) -> subprocess.CompletedProcess:
    if not git():
        raise OSError("git is not installed")
    return subprocess.run([git(), "-c", "core.longpaths=true", *args], cwd=None if cwd is None else str(cwd),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def _git_ok(args: list[str], cwd: Path | None = None, timeout: float = 120.0) -> str:
    run = _run_git(args, cwd, timeout)
    if run.returncode:
        lines = [line for line in run.stderr.splitlines() if line.strip()]
        raise OSError(f"git {args[0]} failed: {lines[-1] if lines else run.returncode}")
    return run.stdout.strip()


_STATES: dict = {}


def state(root: Path | None = None) -> State:
    """-> the copy at `root`, read once until `forget`."""
    root = location() if root is None else Path(root)
    if str(root) not in _STATES:
        _STATES[str(root)] = _read_state(root)
    return _STATES[str(root)]


def _read_state(root: Path) -> State:
    if not present(root):
        return State(False)
    if (root / ".git").exists() and git():
        commit = _git_ok(["rev-parse", "HEAD"], root)
        return State(True, "git", commit, _git_ok(["log", "-1", "--format=%cI", "HEAD", "--", RAID_EVENTS], root)
                     or _git_ok(["log", "-1", "--format=%cI", "HEAD"], root))
    try:
        marker = json.loads((root / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marker = {}
    return State(True, "zip", str(marker.get("commit", "")), str(marker.get("date", "")))


def _latest() -> tuple[str, str]:
    """-> (master's head commit, the date of master's newest raid event change)."""
    head = update.github_json(f"{API}/commits/{BRANCH}", TIMEOUT, "commit")
    changes = update.github_json(f"{API}/commits?sha={BRANCH}&per_page=1&path={urllib.parse.quote(RAID_EVENTS)}",
                                 TIMEOUT, "commit")
    try:
        return head["sha"], changes[0]["commit"]["committer"]["date"]
    except (KeyError, IndexError, TypeError) as error:
        raise OSError("GitHub sent no commit") from error


def date_of(date: str) -> datetime | None:
    """-> an ISO 8601 date as GitHub and git write it, or None."""
    try:
        return datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError:
        return None


def check(root: Path | None = None) -> Check:
    """Whether master has a raid event change the copy lacks. A git copy fetches master and compares
    the raid events folder; a zip copy asks GitHub for master's newest change to it."""
    root = location() if root is None else Path(root)
    found = state(root)
    if not found.present:
        raise OSError("the event gallery is not downloaded")
    if found.method == "git":
        _fetch(root)
        changed = _run_git(["diff", "--quiet", "HEAD", "FETCH_HEAD", "--", RAID_EVENTS], root).returncode == 1
        return Check(changed, _git_ok(["rev-parse", "FETCH_HEAD"], root),
                     _git_ok(["log", "-1", "--format=%cI", "FETCH_HEAD"], root))
    commit, date = _latest()
    ours, theirs = date_of(found.date), date_of(date)
    return Check(ours is None or (theirs is not None and theirs > ours), commit, date)


# --- Downloading and updating ----------------------------------------------------------------------

def _fetch(root: Path) -> bool:
    """Fetches master into FETCH_HEAD, as shallow as the copy is; -> whether it is shallow."""
    shallow = (root / ".git" / "shallow").exists()
    _git_ok(["fetch", *(["--depth", "1"] if shallow else []), "origin", BRANCH], root, GIT_TIMEOUT)
    return shallow


def _swap(fresh: Path, root: Path) -> None:
    old = root.parent / f".{root.name}.old"
    shutil.rmtree(long_path(old), ignore_errors=True)
    if root.exists():
        os.rename(root, old)
    os.rename(fresh, root)
    shutil.rmtree(long_path(old), ignore_errors=True)


def _git_clone(root: Path, progress: Progress) -> None:
    fresh = root.parent / f".{root.name}.download"
    shutil.rmtree(long_path(fresh), ignore_errors=True)
    progress("Cloning the gallery with git...", 0, 0)
    _git_ok(["clone", "--depth", "1", "--filter=blob:none", "--sparse", "--no-checkout", "--branch", BRANCH,
             GIT_URL, str(fresh)], timeout=GIT_TIMEOUT)
    _git_ok(["config", "core.longpaths", "true"], fresh)
    _git_ok(["sparse-checkout", "set", "--no-cone", *SPARSE], fresh)
    progress("Fetching the raid events...", 0, 0)
    _git_ok(["checkout", BRANCH], fresh, GIT_TIMEOUT)
    _swap(fresh, root)


def _zip_download(root: Path, progress: Progress, cancelled: Callable[[], bool]) -> None:
    progress("Asking GitHub for the latest gallery...", 0, 0)
    commit, date = _latest()
    work = paths.DATA / "gallery-download"
    shutil.rmtree(long_path(work), ignore_errors=True)
    work.mkdir(parents=True)
    archive, fresh = work / "gallery.zip", root.parent / f".{root.name}.download"
    try:
        update.fetch(ZIP.format(commit=commit), archive, lambda done, total: progress(
            "Downloading the gallery...", done, total), cancelled)
        progress("Unpacking the raid events...", 0, 0)
        shutil.rmtree(long_path(fresh), ignore_errors=True)
        extract(archive, fresh)
        (fresh / MARKER).write_text(json.dumps({"commit": commit, "date": date}), encoding="utf-8")
        _swap(fresh, root)
    finally:
        shutil.rmtree(long_path(work), ignore_errors=True)
        shutil.rmtree(long_path(fresh), ignore_errors=True)


def extract(archive: Path, folder: Path) -> int:
    """Unpacks the raid events' tables and texts from GitHub's zip of the repository (whose entries
    sit under one top folder); -> how many files."""
    count = 0
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            _, _, inside = info.filename.partition("/")
            if info.is_dir() or not inside.startswith(RAID_EVENTS + "/") or ".." in inside.split("/"):
                continue
            if "/Files/" not in inside and not inside.endswith("/Encounters.txt"):
                continue
            target = long_path(folder / inside)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            count += 1
    if not count:
        raise OSError("the download holds no raid events")
    return count


def download(root: Path | None = None, progress: Progress = lambda text, done, total: None,
             cancelled: Callable[[], bool] = lambda: False, use_git: bool | None = None) -> State:
    """Puts a fresh copy at `root`, by git when the machine has it; a copy there is replaced only once
    the new one is complete."""
    root = location() if root is None else Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    if (git() is not None) if use_git is None else use_git:
        _git_clone(root, progress)
    else:
        _zip_download(root, progress, cancelled)
    forget()
    return state(root)


def take_update(root: Path | None = None, progress: Progress = lambda text, done, total: None,
                cancelled: Callable[[], bool] = lambda: False) -> State:
    """Brings the copy to master: a git copy moves to what it fetched (a fast-forward, or a reset
    that keeps local edits for a shallow one), a zip copy is downloaded again."""
    root = location() if root is None else Path(root)
    if state(root).method != "git":
        return download(root, progress, cancelled, use_git=False)
    progress("Updating the gallery with git...", 0, 0)
    shallow = _fetch(root)
    if _run_git(["merge", "--ff-only", "FETCH_HEAD"], root, GIT_TIMEOUT).returncode:
        if not shallow:
            raise OSError("the gallery has commits of its own; update it with git yourself")
        _git_ok(["reset", "--keep", "FETCH_HEAD"], root, GIT_TIMEOUT)
    forget()
    return state(root)


# --- The raid events -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    key: str                # its folder under Raid Events, with "/"
    title: str              # the folder's name without its number; a round, "Event · Round"
    number: int
    species: tuple          # boss names, table order
    catch_once: tuple       # the bosses a save catches once
    identifier: int


_INDEX: dict = {}
_EVENTS: dict = {}


def forget() -> None:
    """Drops what was read of the gallery, after it changed."""
    _INDEX.clear()
    _EVENTS.clear()
    _STATES.clear()


def title(key: str) -> str:
    return " · ".join(re.sub(r"^\d+\s*", "", part) for part in key.split("/"))


def index(root: Path | None = None) -> list[Entry]:
    """-> the gallery's raid events, oldest first: every folder that holds an event's Files."""
    root = location() if root is None else Path(root)
    base = long_path(root / RAID_EVENTS)
    if base in _INDEX:
        return _INDEX[base]
    found = []
    for folder in raid_event.deliveries(base):
        key = os.path.relpath(folder, base).replace(os.sep, "/")
        if key.split("/")[0] == PLACEHOLDER:
            continue
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
