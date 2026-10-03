"""Reclaim app session files and unused offers; docs/gui.md, Local storage."""
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from pokeldn.app.paths import LOGS, POKEMON, SESSION
from pokeldn.app.settings import PATH

RECORDS = {".pk3", ".ek3", ".pb7", ".pk8", ".pb8", ".pa8", ".pk9", ".pa9", ".bin", ".hex",
           ".pokegift", ".wc3", ".wc8"}
BUILT = re.compile(r".+-\d{8}-\d{6}-[0-9a-f]{8}\.(?:pk3|pb7|pk8|pb8|pa8|pk9|pa9)$")
PREPARED = re.compile(r"(?:frlg|lgpe|bdsp|swsh|pla|sv|za)-[0-9a-f]{32}\.(?:pk3|pb7|pk8|pb8|pa8|pk9|bin)$")


@dataclass(frozen=True)
class File:
    path: Path
    root: Path
    info: os.stat_result


@dataclass(frozen=True)
class Inventory:
    files: tuple[File, ...] = ()
    errors: int = 0

    @property
    def size(self) -> int:
        return sum(file.info.st_size for file in self.files)


@dataclass(frozen=True)
class Cleared:
    files: int = 0
    size: int = 0
    errors: int = 0
    skipped: int = 0


def size_text(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def _protected(settings) -> set[Path]:
    paths = {PATH.resolve()}

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value:
            try:
                path = Path(value).expanduser()
                paths.add((path if path.is_absolute() else SESSION / path).resolve())
            except (OSError, ValueError, RuntimeError):
                pass

    for value in (settings.received, settings.keys, settings.firmware, settings.tool_values):
        visit(value)
    return paths


def _kept(path: Path, protected: set[Path]) -> bool:
    return path.suffix.lower() == ".keys" or any(p == path or p in path.parents for p in protected)


def _disposable(path: Path, root: Path, managed: Path) -> bool:
    if managed == POKEMON:
        return bool(BUILT.fullmatch(path.name))
    if path.suffix.lower() in RECORDS:
        return managed == SESSION and path.parent == root / "offers" and bool(PREPARED.fullmatch(path.name))
    return True


def scan(settings) -> Inventory:
    protected, files, errors = _protected(settings), [], 0
    recent = time.time() - 60
    for managed in (SESSION, LOGS, POKEMON):
        if managed.is_symlink():
            continue
        root = managed.resolve()
        pending = [root]
        while pending:
            folder = pending.pop()
            if folder.is_symlink() or _kept(folder, protected):
                continue
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        if entry.is_symlink() or _kept(path, protected):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(path)
                        else:
                            # Windows DirEntry.stat omits file identity; clear uses Path.stat.
                            info = path.stat(follow_symlinks=False)
                            if (stat.S_ISREG(info.st_mode) and _disposable(path, root, managed)
                                    and (managed != POKEMON or info.st_mtime < recent)):
                                files.append(File(path, root, info))
            except FileNotFoundError:
                pass
            except OSError:
                errors += 1
    return Inventory(tuple(files), errors)


def clear(inventory: Inventory, settings) -> Cleared:
    protected = _protected(settings)
    removed = size = errors = skipped = 0
    folders = set()
    for file in inventory.files:
        path, root = file.path, file.root
        try:
            parents = path.parents[:path.parents.index(root) + 1]
            if _kept(path, protected) or any(p.is_symlink() for p in (path, *parents)):
                skipped += 1
                continue
            info = path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or
                    (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) !=
                    (file.info.st_dev, file.info.st_ino, file.info.st_size, file.info.st_mtime_ns)):
                skipped += 1
                continue
            path.unlink()
            removed += 1
            size += info.st_size
            folders.update((parent, root) for parent in parents[:-1])
        except FileNotFoundError:
            continue
        except OSError:
            errors += 1
    for folder, root in sorted(folders, key=lambda pair: len(pair[0].parts), reverse=True):
        try:
            parents = folder.parents[:folder.parents.index(root) + 1]
            if not any(p.is_symlink() for p in (folder, *parents)) and not _kept(folder, protected):
                folder.rmdir()
        except OSError:
            pass
    return Cleared(removed, size, errors, skipped)
