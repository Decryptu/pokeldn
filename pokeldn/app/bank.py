"""The Pokemon the app keeps between games: each record in the bank folder with a `.json` beside it
[docs/gui.md, The bank]. A trade's received Pokemon is deposited on its own; one queued for a trade
carries {"bank": id} in the offer queue and leaves the bank when that trade completes."""
import base64
import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

from pokeldn.app.paths import BANK
from pokeldn.pokemon import EXTENSIONS

FILES = re.compile(r"\.(pk3|pb7|pk8|pb8|pa8|pk9|pa9)$", re.IGNORECASE)
GAME_OF = {extension: game for game, extension in EXTENSIONS.items()}


@dataclass(frozen=True)
class Entry:
    id: str               # the record's file name without its extension
    path: str
    game: str             # the catalog key of the game it is in now
    species_id: int
    shiny: bool
    summary: str          # pokeldn.pokemon.summary
    legal: bool
    tracker: int          # the HOME tracker a move to another game gives it, never 0
    created: float
    origin: str           # the Received file it came from, "" when unknown

    @property
    def when(self) -> str:
        return time.strftime("%d %b %Y, %H:%M", time.localtime(self.created))


def library() -> Path:
    """The folder; created by the first deposit, never by a listing."""
    return BANK


def _meta_path(path) -> Path:
    return Path(path).with_suffix(".json")


def _read_meta(path) -> dict:
    try:
        meta = json.loads(_meta_path(path).read_text(encoding="utf-8"))
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_meta(path, meta: dict) -> None:
    target = _meta_path(path)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(path: Path) -> Entry | None:
    game = GAME_OF.get(path.suffix[1:].lower())
    meta = _read_meta(path)
    if game is None or not meta:
        return None
    try:
        tracker = int(meta.get("tracker", "0"))
    except ValueError:
        tracker = 0
    return Entry(path.stem, str(path), game, int(meta.get("species_id") or 0), bool(meta.get("shiny")),
                 str(meta.get("summary", "")), meta.get("legal") is not False, tracker,
                 float(meta.get("created") or 0), str(meta.get("origin", "")))


def entries(folder=None) -> list[Entry]:
    """Every banked Pokemon, newest first."""
    folder = Path(folder or BANK)
    if not folder.is_dir():
        return []
    found = [e for path in folder.iterdir() if FILES.search(path.name) and (e := _entry(path))]
    return sorted(found, key=lambda e: (e.created, e.id), reverse=True)


def find(entry_id: str, folder=None) -> Entry | None:
    return next((e for e in entries(folder) if e.id == entry_id), None)


def data(entry: Entry) -> bytes:
    return Path(entry.path).read_bytes()


def deposit(game: str, source: str, info: dict, folder=None) -> Entry | None:
    """Keep a copy of the record at `source`, which PKHeX read as `info`. None when the bank already holds
    these bytes: a received file is read again while it grows, and on every later scan."""
    folder = Path(folder or BANK)
    content = Path(source).read_bytes()
    digest = _digest(content)
    if folder.is_dir() and any(_read_meta(p).get("sha256") == digest for p in folder.glob("*.json")):
        return None
    from pokeldn.pokemon import summary
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9]+", "", str(info.get("species", ""))) or "pokemon"
    stem = f"{name}-{time.strftime('%Y%m%d-%H%M%S')}-{random.getrandbits(32):08x}"
    path = folder / f"{stem}.{EXTENSIONS[game]}"
    path.write_bytes(content)
    _write_meta(path, {
        "game": game, "species": info.get("species", ""), "species_id": int(info.get("species_id") or 0),
        "shiny": bool(info.get("shiny")), "summary": summary(info), "legal": bool(info.get("legal")),
        # HOME gives each Pokemon a tracker when it enters; a string, since JSON readers lose 64-bit precision.
        "tracker": str(random.randrange(1, 1 << 63)), "created": time.time(),
        "origin": str(source), "sha256": digest,
    })
    return _entry(path)


def edit(entry: Entry, fields: dict) -> Entry:
    """Change what a player could change in the game (nickname, level, moves, held item) and keep the result,
    or BuilderError with the reason. A legal Pokemon stays legal: an edit PKHeX rejects is refused."""
    from pokeldn.pokemon import SERVICE, BuilderError, summary
    reply = SERVICE.check_bytes(entry.game, data(entry), fields=fields)
    if entry.legal and not reply["legal"]:
        raise BuilderError(reply["problems"])
    content = base64.b64decode(reply["data"])
    path = Path(entry.path)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)
    meta = _read_meta(path)
    meta.update({"species": reply["species"], "species_id": int(reply["species_id"]), "shiny": bool(reply["shiny"]),
                 "summary": summary(reply), "legal": bool(reply["legal"]), "sha256": _digest(content),
                 "edited": time.time()})
    _write_meta(path, meta)
    return _entry(path)


def remove(entry_id: str, folder=None) -> None:
    folder = Path(folder or BANK)
    for path in folder.glob(f"{entry_id}.*") if folder.is_dir() else ():
        if FILES.search(path.name) or path.suffix == ".json":
            path.unlink(missing_ok=True)


# The offer queues

def offer(entry: Entry, game: str, trainer: dict) -> dict:
    """The queue item that trades this banked Pokemon into `game`: moved there by PKHeX's HOME conversion
    and legal there, or BuilderError with the reason. `trainer` is the bank's owner, who handles it."""
    from pokeldn.pokemon import SERVICE, summary
    reply = SERVICE.move(entry.game, game, data(entry), entry.tracker, trainer)
    return {"file": SERVICE.keep(game, reply), "summary": summary(reply), "species": reply["species_id"],
            "shiny": reply["shiny"], "legal": reply["legal"], "encounter": reply["encounter"],
            "moves": reply["moves"], "report": "", "bank": entry.id}


def queued(settings, entry_id: str) -> list[str]:
    """The tool keys whose offer queue holds this banked Pokemon."""
    return [tool for tool, stored in settings.tool_values.items()
            for value in stored.get("values", {}).values() if isinstance(value, list)
            if any(isinstance(v, dict) and v.get("bank") == entry_id for v in value)]


def enqueue(settings, tool, field, item: dict) -> str:
    """Append a moved Pokemon to a tool's queue; why it cannot be, or ""."""
    from pokeldn.app.command import offers
    stored = settings.tool_values.setdefault(tool.key, {"values": {}, "extra": {}})
    queue = [v for v in offers(stored["values"].get(field.key, field.default)) if v.get("file")]
    if len(queue) >= field.queue:
        return f"{tool.name} already has {field.queue} Pokemon queued."
    stored["values"][field.key] = queue + [item]
    settings.save()
    return ""


def dequeue(settings, entry_id: str) -> None:
    """Take a banked Pokemon out of every queue; it stays in the bank."""
    _drop(settings, lambda v: v.get("bank") == entry_id)


def prune(settings) -> None:
    """Drop queued Pokemon whose bank record is gone: traded away, or removed from the folder."""
    if not BANK.is_dir():     # an unplugged or unreadable folder says nothing about what was traded
        return
    held = {e.id for e in entries()}
    _drop(settings, lambda v: bool(v.get("bank")) and v["bank"] not in held)


def _drop(settings, gone) -> None:
    changed = False
    for stored in settings.tool_values.values():
        for key, value in stored.get("values", {}).items():
            if isinstance(value, list) and any(isinstance(v, dict) and gone(v) for v in value):
                stored["values"][key] = [v for v in value if not (isinstance(v, dict) and gone(v))]
                changed = True
    if changed:
        settings.save()
