"""One zip of the player's own files: settings, built and received Pokemon, the bank, saves, GTS
listings and macros. Never the console keys and never plugin code. A restore stages the settings for
the next launch and writes the other files over their namesakes. docs/gui.md, Backup and restore."""
import json
import os
import shutil
import stat
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pokeldn.app import paths
from pokeldn.app import settings as settings_module

SETTINGS = "settings/settings.json"
MANIFEST = "pokeldn-backup.json"
FORMAT = 1
MAX_FILES = 200_000
MAX_BYTES = 8 << 30         # what a restore unpacks at most: zipfile never reads past a member's declared size
NEVER = {".keys"}           # console keys stay on this computer


def folders(received: str = "") -> dict[str, Path]:
    """The archive's top folders and where each lives on this computer."""
    return {
        "pokemon": paths.POKEMON,
        "received": Path(os.path.expanduser(received)) if received else paths.RECEIVED,
        "bank": paths.BANK,
        "saves": paths.SAVES,
        "gts": paths.GTS,
        "macros": paths.MACROS,
    }


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class Summary:
    files: int
    size: int


def _files(root: Path):
    """Regular files under `root`, never through a link, without the keys."""
    if not root.is_dir() or root.is_symlink():
        return
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(folder, d)))
        for name in sorted(names):
            path = Path(folder, name)
            if path.suffix.lower() in NEVER or path.is_symlink() or not path.is_file():
                continue
            yield path


def create(target: str | Path, received: str = "") -> Summary:
    """Writes the backup to `target` through a temporary file beside it."""
    target = Path(target)
    count = size = 0
    handle, temporary = tempfile.mkstemp(prefix=".pokeldn-backup-", suffix=".zip", dir=target.parent)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr(MANIFEST, json.dumps({"format": FORMAT, "made": int(time.time())}))
            if settings_module.PATH.is_file():
                archive.write(settings_module.PATH, SETTINGS)
                count, size = 1, settings_module.PATH.stat().st_size
            for top, root in folders(received).items():
                for path in _files(root):
                    archive.write(path, f"{top}/{path.relative_to(root).as_posix()}")
                    count += 1
                    size += path.stat().st_size
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return Summary(count, size)


def _checked(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Every member a restore writes; a BackupError for an archive that is not a pokeldn backup or that
    names a path outside its folders."""
    try:
        manifest = json.loads(archive.read(MANIFEST))
    except (KeyError, ValueError) as error:
        raise BackupError("This is not a pokeldn backup.") from error
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupError("This backup was made by a newer pokeldn.")
    members, total = [], 0
    tops = set(folders()) | {"settings"}
    for info in archive.infolist():
        if info.filename == MANIFEST or info.is_dir():
            continue
        name = info.filename
        parts = PurePosixPath(name).parts
        if ("\\" in name or name.startswith("/") or ":" in parts[0] or ".." in parts or len(parts) < 2
                or parts[0] not in tops or (parts[0] == "settings" and name != SETTINGS)):
            raise BackupError(f"The backup names a path outside its folders: {name}")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise BackupError(f"The backup holds a link: {name}")
        if PurePosixPath(name).suffix.lower() in NEVER:
            continue
        total += info.file_size
        members.append(info)
    if len(members) > MAX_FILES or total > MAX_BYTES:
        raise BackupError("The backup is larger than a pokeldn backup can be.")
    return members


def inspect(source: str | Path) -> Summary:
    """What a restore would write, after the same checks; a BackupError otherwise."""
    try:
        with zipfile.ZipFile(source) as archive:
            members = _checked(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise BackupError(f"The backup cannot be read: {error}") from error
    return Summary(len(members), sum(m.file_size for m in members))


def restore(source: str | Path, received: str = "", safety: str | Path | None = None) -> Summary:
    """Writes the backup's files over their namesakes; files it does not hold stay. `safety`: a backup
    of this computer's files first. The settings land in settings.restore.json, which the next launch
    applies (pokeldn.app.settings.load)."""
    try:
        with zipfile.ZipFile(source) as archive:
            members = _checked(archive)
            if safety:
                create(safety, received)
            settings = next((m for m in members if m.filename == SETTINGS), None)
            if settings is not None:
                try:
                    data = json.loads(archive.read(settings))
                except ValueError as error:
                    raise BackupError("The backup's settings cannot be read.") from error
                if not isinstance(data, dict):
                    raise BackupError("The backup's settings cannot be read.")
                staged = settings_module.STAGED
                staged.parent.mkdir(parents=True, exist_ok=True)
                temporary = staged.with_suffix(".tmp")
                temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
                os.replace(temporary, staged)
            roots = folders(received)
            count, size = int(settings is not None), settings.file_size if settings else 0
            for info in members:
                if info is settings:
                    continue
                top, _, rest = info.filename.partition("/")
                root = roots[top].resolve()
                path = (root / rest).resolve()
                if root not in path.parents:
                    raise BackupError(f"The backup names a path outside its folders: {info.filename}")
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.restoring")
                try:
                    with archive.open(info) as reader, open(temporary, "wb") as writer:
                        shutil.copyfileobj(reader, writer, 1 << 20)   # a wrong CRC raises at the end
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                count += 1
                size += info.file_size
    except (OSError, zipfile.BadZipFile) as error:
        raise BackupError(f"The backup cannot be read: {error}") from error
    return Summary(count, size)


def default_name() -> str:
    return time.strftime("pokeldn-backup-%Y%m%d-%H%M%S.zip")


KEEP_SAFETY = 3


def safety_path() -> Path:
    """Where a restore keeps this computer's files from before it; the newest KEEP_SAFETY stay."""
    folder = paths.DATA / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    for old in sorted(folder.glob("before-restore-*.zip"))[:-(KEEP_SAFETY - 1)]:
        old.unlink(missing_ok=True)
    return folder / time.strftime("before-restore-%Y%m%d-%H%M%S.zip")
