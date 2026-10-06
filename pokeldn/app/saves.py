"""The FireRed/LeafGreen saves the app keeps: each `.sav` in the library folder with a `.json` beside it
holding the name the player gave it, where it came from and the cartridge [docs/gui.md, Your saves].
The folder is the player's, under Documents; Clear local files never touches it."""
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from pokeldn.app.paths import SAVES
from pokeldn.frlg.save import sav

PARTIAL = ".partial"                  # backups the link cut short [save_transfer.SaveBackupServer]
CARTRIDGES = {"BPR": "FireRed", "BPG": "LeafGreen"}


def library() -> Path:
    """The folder; created by the first save kept in it, never by a listing."""
    return SAVES


def partial_dir() -> str:
    return str(SAVES / PARTIAL)


def has_partial() -> bool:
    """A backup the link cut short is waiting to go on."""
    folder = SAVES / PARTIAL
    return folder.is_dir() and any(folder.glob("*.partial"))


def backup_target() -> str:
    """The launcher's --save-backup file; {stamp} is the run's."""
    return str(SAVES / "backup-{stamp}.sav")


def _meta_path(path) -> Path:
    return Path(path).with_suffix(".json")


def read_meta(path) -> dict:
    try:
        meta = json.loads(_meta_path(path).read_text(encoding="utf-8"))
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


def write_meta(path, **fields) -> dict:
    meta = {**read_meta(path), **fields}
    target = _meta_path(path)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return meta


@dataclass(frozen=True)
class Entry:
    path: str
    name: str
    created: float
    source: str           # backup, import, edit
    game_code: str        # the console's, for a backup; "" when unknown
    trainer: dict | None  # sav.trainer(), None when no copy is whole
    language: int | None  # the language the player's own Pokemon carry [sav.language]

    @property
    def sound(self) -> bool:
        return self.trainer is not None

    @property
    def cartridge(self) -> str:
        """FireRed or LeafGreen, "" when the save came from a file."""
        return CARTRIDGES.get(self.game_code[:3], "")

    @property
    def when(self) -> str:
        return time.strftime("%d %b %Y, %H:%M", time.localtime(self.created))


def default_name(trainer: dict | None, game_code: str = "") -> str:
    """The trainer, and the cartridge when known: the list shows the date beside it."""
    who = trainer["name"] if trainer else "Save"
    game = CARTRIDGES.get(game_code[:3])
    return f"{who}'s {game}" if game else who


def entry(path) -> Entry | None:
    path = str(path)
    try:
        data = sav.normalize(Path(path).read_bytes())
        created = os.path.getmtime(path)
    except (OSError, sav.SaveError):
        return None
    summary = sav.describe(data)
    trainer = sav.trainer(data) if summary.sound else None
    meta = read_meta(path)
    source = meta.get("source", "import")
    created = float(meta.get("created", created))
    game_code = str(meta.get("game_code", ""))
    return Entry(path, meta.get("name") or default_name(trainer, game_code), created, source, game_code,
                 trainer, sav.language(data))


def entries() -> list[Entry]:
    """Every save in the library, newest first. A backup the launcher just wrote is named here."""
    out = []
    for path in sorted(SAVES.glob("*.sav")) if SAVES.is_dir() else ():
        found = entry(path)
        if found is None:
            continue
        if not read_meta(path).get("name"):
            write_meta(path, name=found.name, source=found.source, created=found.created)
        out.append(found)
    return sorted(out, key=lambda e: e.created, reverse=True)


def _unique(stem: str) -> Path:
    SAVES.mkdir(parents=True, exist_ok=True)
    stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in stem).strip("-") or "save"
    path, n = SAVES / f"{stem}.sav", 2
    while path.exists():
        path, n = SAVES / f"{stem}-{n}.sav", n + 1
    return path


def add(data: bytes, *, source: str, name: str = "", game_code: str = "") -> Entry:
    """Keep `data` in the library; SaveError when it is not a FireRed/LeafGreen save."""
    data = sav.normalize(data)
    created = time.time()
    path = _unique(f"{source}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(created))}")
    path.write_bytes(data)
    summary = sav.describe(data)
    trainer = sav.trainer(data) if summary.sound else None
    write_meta(path, name=name.strip() or default_name(trainer, game_code), source=source,
               created=created, game_code=game_code)
    return entry(path)


def import_file(path: str) -> Entry:
    data = Path(path).read_bytes()
    return add(data, source="import", name=Path(path).stem)


def rename(item: Entry, name: str) -> None:
    write_meta(item.path, name=name.strip() or item.name)


def delete(item: Entry) -> None:
    for path in (Path(item.path), _meta_path(item.path)):
        path.unlink(missing_ok=True)


def export(item: Entry, destination: str) -> None:
    shutil.copyfile(item.path, destination)


_checks: dict[tuple, dict] = {}


def party_check(path: str) -> dict:
    """-> {"illegal": [species], "error": ""}: the party PKHeX finds illegal, cached by file version."""
    try:
        stat = os.stat(path)
    except OSError as exc:
        return {"illegal": [], "error": str(exc)}
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _checks:
        from pokeldn import pokemon
        try:
            info = pokemon.SERVICE.save_read(Path(path).read_bytes())
            _checks[key] = {"illegal": [m["species"] for m in info["party"] if not m["legal"]], "error": ""}
        except Exception as exc:
            return {"illegal": [], "error": str(exc)}
    return _checks[key]


def cached_check(path: str) -> dict | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return _checks.get((path, stat.st_mtime_ns, stat.st_size))


def file_name(item: Entry) -> str:
    """A .sav file name made from the save's name."""
    clean = "".join(c if c.isalnum() or c in " -_" else "" for c in item.name).strip() or "save"
    return f"{clean}.sav"
