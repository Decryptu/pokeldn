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
# A .pk3 is FireRed's: Ruby, Sapphire and Emerald share the format and come after it.
GAME_OF = {extension: game for game, extension in reversed(EXTENSIONS.items())}


@dataclass(frozen=True)
class Entry:
    id: str               # the record's file name without its extension
    path: str
    game: str             # the catalog key of the game it is in now
    species_id: int
    shiny: bool
    summary: str          # pokeldn.pokemon.summary
    legal: bool
    tracker: int          # the HOME tracker a move under the "made" setting gives it, never 0
    created: float
    origin: str           # the Received file it came from, "" when unknown
    home_tracker: str     # "empty" or "made" when its record's tracker is one HOME did not issue, else ""

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


def _banked(folder: Path) -> set[str]:
    return {_read_meta(p).get("sha256") for p in folder.glob("*.json")} if folder.is_dir() else set()


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
                 float(meta.get("created") or 0), str(meta.get("origin", "")), _home_tracker(game, meta))


# Before the setting, an import through HOME's conversion into a game with a tracker always made one.
TRACKED = {"bdsp": "PB8", "swsh": "PK8", "pla": "PA8", "sv": "PK9", "za": "PA9"}


def _home_tracker(game: str, meta: dict) -> str:
    if "home_tracker" in meta:
        return str(meta["home_tracker"])
    imported = meta.get("imported")
    converted = isinstance(imported, dict) and imported.get("from") not in (None, TRACKED.get(game))
    return "made" if game in TRACKED and converted else ""


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
    return _keep(game, Path(source).read_bytes(), info, Path(folder or BANK), str(source))


def _keep(game: str, content: bytes, info: dict, folder: Path, origin: str, banked: set[str] | None = None,
          **extra) -> Entry | None:
    """`banked` is the SHA-256 of each record in the folder, read once for many deposits and kept up to date."""
    digest = _digest(content)
    if banked is None:
        banked = _banked(folder)
    if digest in banked:
        return None
    banked.add(digest)
    from pokeldn.pokemon import summary
    # Display-service replies also enter here when a trade's received file is banked.
    info = {**info, **info.get("canonical", {})}
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9]+", "", str(info.get("species", ""))) or "pokemon"
    stem = f"{name}-{time.strftime('%Y%m%d-%H%M%S')}-{random.getrandbits(32):08x}"
    path = folder / f"{stem}.{EXTENSIONS[game]}"
    path.write_bytes(content)
    _write_meta(path, {
        "game": game, "species": info.get("species", ""), "species_id": int(info.get("species_id") or 0),
        "shiny": bool(info.get("shiny")), "summary": summary(info), "legal": bool(info.get("legal")),
        # HOME gives each Pokemon a tracker when it enters; a string, since JSON readers lose 64-bit precision.
        "tracker": str(int(info.get("tracker") or 0) or random.randrange(1, 1 << 63)), "created": time.time(),
        "home_tracker": str(info.get("home_tracker", "")), "origin": origin, "sha256": digest, **extra,
    })
    return _entry(path)


# Importing

# The largest file read: PKHeX takes a save of any size it knows, the biggest a few megabytes.
IMPORT_LIMIT = 64 << 20
LEDGER = ".imported"      # one services/pkhex Import key per line: what was imported, even if since traded


@dataclass(frozen=True)
class ImportedPokemon:
    where: str            # "Party, slot 1", "Box 2, slot 3"; "" for a Pokemon file
    species: str
    species_id: int
    shiny: bool
    state: str            # "banked", "already" (imported before, or its exact record is banked) or "refused"
    game: str             # the bank game it is kept in; "" when refused
    detail: str           # what HOME's way in took off ("Left its Oran Berry behind"), or why it was refused


@dataclass
class Imported:
    name: str             # the file's name
    save: str             # "Black 2, ROSA" for a game save, "" for a Pokemon file
    pokemon: list[ImportedPokemon]

    def count(self, state: str) -> int:
        return sum(p.state == state for p in self.pokemon)


def import_file(path: str, trainers: dict[str, dict], folder=None) -> Imported:
    """Bank each Pokemon in a Pokemon file or a game save PKHeX reads; the file is only read [docs/gui.md,
    Importing]. A record imported once is not imported again, even after it left the bank in a trade.
    `trainers` maps each game to who receives a Pokemon HOME moves there. OSError or BuilderError."""
    from pokeldn.pokemon import HOME_TRACKER_WARNINGS, SERVICE, BuilderError
    folder = Path(folder or BANK)
    source = Path(path)
    if source.stat().st_size > IMPORT_LIMIT:
        raise BuilderError("This file is too big to be a Pokemon or a game save.")
    reply = SERVICE.import_records(source.read_bytes(), source.name, trainers)
    ledger = folder / LEDGER
    try:
        seen = set(ledger.read_text(encoding="utf-8").split())
    except OSError:
        seen = set()
    result, banked = Imported(source.name, reply.get("save", ""), []), _banked(folder)
    for record in reply["pokemon"]:
        if "refusal" in record:
            state, detail = "refused", record["refusal"].splitlines()[0]
        else:
            key = record["key"]
            entry = None if key in seen else _keep(
                record["game"], base64.b64decode(record["data"]), record, folder, str(source), banked,
                imported={"file": source.name, "where": record["where"], "from": record["source"],
                          "notes": record["notes"]})
            warning = HOME_TRACKER_WARNINGS.get(record["home_tracker"])
            state, detail = ("already", "") if entry is None else (
                "banked", " · ".join([*record["notes"], *([warning] if warning else [])]))
            if key not in seen:
                seen.add(key)
                folder.mkdir(parents=True, exist_ok=True)
                with ledger.open("a", encoding="utf-8") as out:
                    out.write(key + "\n")
        result.pokemon.append(ImportedPokemon(record["where"], record["species"], int(record["species_id"]),
                                              bool(record["shiny"]), state, record.get("game", ""), detail))
    return result


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
    for path in folder.iterdir() if folder.is_dir() else ():
        if path.stem == entry_id and (FILES.search(path.name) or path.suffix == ".json"):
            path.unlink(missing_ok=True)


# The offer queues

def destinations(entry: Entry, trainer: dict, *, service=None) -> dict[str, dict]:
    """Each game -> {ok, reason, home_tracker}, using the same conversion rules as offer."""
    from pokeldn.pokemon import SERVICE
    return (service or SERVICE).destinations(entry.game, data(entry), entry.tracker, trainer)


def offer(entry: Entry, game: str, trainer: dict) -> dict:
    """The queue item that trades this banked Pokemon into `game`: moved there by PKHeX's HOME conversion
    and legal there, or BuilderError with the reason. `trainer` is the bank's owner, who handles it."""
    from pokeldn.pokemon import SERVICE, summary
    reply = SERVICE.move(entry.game, game, data(entry), entry.tracker, trainer)
    return {"file": SERVICE.keep(game, reply), "summary": summary(reply), "species": reply["species_id"],
            "shiny": reply["shiny"], "legal": reply["legal"], "encounter": reply["encounter"],
            "moves": reply["moves"], "report": "", "home_tracker": reply["home_tracker"], "bank": entry.id}


class TradeSession:
    """Snapshot the ordered offers for one run; only confirmed trades remove their bank entries."""

    def __init__(self, offers: list[dict], folder=None):
        self._ids = tuple(item.get("bank", "") for item in offers)
        self._folder = Path(folder or BANK)
        self._completed = 0

    @property
    def completed(self) -> int:
        return self._completed

    def advance(self, count: int) -> int:
        """Apply a cumulative completed-trade count; repeats are harmless, invalid counts raise ValueError."""
        if type(count) is not int or count < 0:
            raise ValueError("Completed trades must be a nonnegative integer.")
        while self._completed < min(count, len(self._ids)):
            entry_id = self._ids[self._completed]
            if entry_id:
                remove(entry_id, folder=self._folder)
            self._completed += 1
        self._completed = max(self._completed, count)
        return self._completed


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
