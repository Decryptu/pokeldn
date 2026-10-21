"""A plugin's library (pokeldn.plugins.library_folder) as the Games page lists it: the files a player keeps,
copies in, renames and deletes. Hidden names and unfinished `.part` files are the plugin's own."""
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    path: Path
    size: int
    modified: float

    @property
    def name(self) -> str:
        return self.path.name


def shown(folder: Path) -> str:
    """The folder as a player reads it: from their home folder when it is inside it."""
    try:
        return str(Path(folder).relative_to(Path.home()))
    except ValueError:
        return str(folder)


# A field, ascending, or with "-desc" descending: "date-desc" is newest first.
SORTS = ("name", "name-desc", "date", "date-desc", "size", "size-desc")
DEFAULT_SORT = "date-desc"


def natural(name: str) -> tuple:
    """Digit runs compare as numbers and letters without case: v65536 before v131072, 20.5.0 before 23.0.1."""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
                 for part in re.split(r"(\d+)", name) if part)


def _key(sort: str):
    field = sort.removesuffix("-desc")
    return {"name": lambda e: natural(e.name), "date": lambda e: (e.modified, natural(e.name)),
            "size": lambda e: (e.size, natural(e.name))}[field]


def entries(folder: Path, sort: str = DEFAULT_SORT) -> list[Entry]:
    """The library's files in the order `sort` (one of SORTS) names; an absent folder has none."""
    try:
        listed = [(p, p.stat()) for p in Path(folder).iterdir()
                  if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".part")]
    except OSError:
        return []
    if sort not in SORTS:
        raise ValueError(f"a library sort is one of {', '.join(SORTS)}")
    return sorted((Entry(p, s.st_size, s.st_mtime) for p, s in listed), key=_key(sort),
                  reverse=sort.endswith("-desc"))


def _inside(folder: Path, path: Path) -> Path:
    path = Path(path)
    if path.parent.resolve() != Path(folder).resolve():
        raise ValueError(f"{path.name} is not in the library")
    return path


def rename(folder: Path, entry: Entry, name: str) -> Path:
    """Renames a file, keeping its extension when the new name does not end with it ("Game 1.2.0" keeps .nsp);
    -> its new path."""
    name = " ".join(name.split())
    if not name or name.startswith(".") or any(c in name for c in '/\\:*?"<>|'):
        raise ValueError("A file name cannot be empty, start with a dot or hold / \\ : * ? \" < > |.")
    source = _inside(folder, entry.path)
    if not name.lower().endswith(source.suffix.lower()):
        name += source.suffix
    target = source.with_name(name)
    if target == source:
        return source
    if target.exists():
        raise FileExistsError(f"{name} is already in the library.")
    os.rename(source, target)
    return target


def delete(folder: Path, entry: Entry) -> None:
    _inside(folder, entry.path).unlink(missing_ok=True)


def add(folder: Path, source: str) -> Path:
    """Copies `source` into the library under a free name; the copy appears whole or not at all."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source = Path(source)
    target, n = folder / source.name, 2
    while target.exists():
        target = folder / f"{source.stem} ({n}){source.suffix}"
        n += 1
    partial = target.with_name(f".{target.name}.{int(time.time())}.part")
    try:
        shutil.copyfile(source, partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target
