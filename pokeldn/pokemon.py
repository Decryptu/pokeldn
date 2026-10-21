"""Legal Pokemon from PKHeX.Core, through the services/pkhex service, saved in the form each launcher reads."""
import base64
import glob
import json
import os
import re
import queue
import subprocess
import sys
import threading
import time
import atexit
from pathlib import Path
from uuid import uuid4

from pokeldn.app.paths import POKEMON, ROOT, SESSION

HERE = os.path.join(ROOT, "services", "pkhex")
EXE = "pokeldn-pkhex.exe" if sys.platform == "win32" else "pokeldn-pkhex"
# The file each game's launchers take as an offer.
EXTENSIONS = {"frlg": "pk3", "rse": "pk3", "lgpe": "pb7", "bdsp": "pb8", "swsh": "pk8", "pla": "pa8", "sv": "pk9",
              "za": "pa9"}
ZA_OFFER_HEADER = bytes.fromhex("0101b90300bc815801")   # SelectPokemon, round 0 (docs/za.md)
RECORD_SIZES = {"frlg": (80, 100), "rse": (80, 100), "lgpe": (232, 260), "bdsp": (328, 344),
                "swsh": (328, 344), "pla": (360, 376), "sv": (328, 344), "za": (328, 344)}
NATURES = ("Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish",
           "Lax", "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful",
           "Rash", "Calm", "Gentle", "Sassy", "Careful", "Quirky")   # the index every record stores
CHECK_TIMEOUT = 10.0
RECORD_LIMIT = 768


class BuilderError(Exception):
    pass


def _command() -> list[str]:
    override = os.environ.get("POKELDN_PKHEX")
    if override:
        return ["dotnet", override] if override.endswith(".dll") else [override]
    # dist/ is the release build's single file; bin/ is a local `dotnet build -c Release`. The newest
    # wins: a dist/ left by a pack would otherwise hide every later source build.
    found = [path for path in (os.path.join(HERE, "dist", EXE),
                               *glob.glob(os.path.join(HERE, "bin", "Release", "*", "*", EXE)))
             if os.path.isfile(path)]
    if found:
        return [max(found, key=os.path.getmtime)]
    raise BuilderError("PKHeX is missing. From source, run: dotnet build -c Release services/pkhex")


def _library(command: list[str]) -> bool:
    """The helper as a library: a .dylib, or the iOS bundle's framework (examples/ios/build.py). Python on
    macOS lives in Python.framework too, so the framework is matched by name."""
    return len(command) == 1 and (command[0].endswith(".dylib") or "/pokeldn_pkhex.framework/" in command[0])


class _Library:
    """The helper compiled as a library (services/pkhex/Library.cs), for iOS, which starts no process:
    its request loop runs on a thread over two pipes, behind Popen's stdin, stdout, poll and wait."""

    def __init__(self, path: str):
        import ctypes
        serve = ctypes.CDLL(path).pokeldn_pkhex_serve
        serve.argtypes, serve.restype = (ctypes.c_int, ctypes.c_int), None
        requests_read, requests_write = os.pipe()
        replies_read, replies_write = os.pipe()
        self.stdin = open(requests_write, "w", encoding="utf-8")
        self.stdout = open(replies_read, "r", encoding="utf-8")
        # The library owns and closes its two ends; closing stdin ends its loop.
        self.thread = threading.Thread(target=serve, args=(requests_read, replies_write), name="pkhex", daemon=True)
        self.thread.start()

    def poll(self):
        return None if self.thread.is_alive() else 0

    def wait(self, timeout=None):
        self.thread.join(timeout)
        if self.thread.is_alive() and timeout is not None:
            raise subprocess.TimeoutExpired("pkhex", timeout)
        return 0

    def kill(self):
        """A thread cannot be stopped; a stuck check is abandoned with its pipes."""
        self.thread = threading.Thread(target=lambda: None)
        self.thread.start()


class Service:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.species_cache: dict[str, list[dict]] = {}
        # Settings.home_tracker; the app sets it, a run inherits it through the environment.
        self.home_tracker = os.environ.get("POKELDN_HOME_TRACKER") or "empty"

    def _ask(self, request: dict) -> dict:
        request = {**request, "home_tracker": self.home_tracker}
        with self.lock:
            for attempt in range(2):
                if self.proc is None or self.proc.poll() is not None:
                    self._close()
                    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    command = _command()
                    self.proc = (_Library(command[0]) if _library(command) else
                                 subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                  stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                                  creationflags=flags))
                line = self._exchange(request)
                if not line:
                    raise BuilderError("The Pokemon builder stopped.")
                reply = json.loads(line)
                if not reply.get("ok"):
                    raise BuilderError(reply.get("error", "unknown error"))
                if request.get("cmd") != "check" or reply.get("parsed") is not False:
                    return reply
                self._close()
                if attempt:
                    raise BuilderError("PKHeX could not complete its legality analysis after restarting the builder.")

    def _exchange(self, request):
        proc = self.proc
        replies = queue.Queue(maxsize=1)

        def exchange():
            try:
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
                replies.put(proc.stdout.readline())
            except (OSError, ValueError) as exc:
                replies.put(exc)

        if request.get("cmd") != "check":
            exchange()
        else:
            worker = threading.Thread(target=exchange, name="pokemon check", daemon=True)
            worker.start()
        try:
            reply = replies.get(timeout=CHECK_TIMEOUT)
        except queue.Empty:
            proc.kill()
            proc.wait()
            worker.join(timeout=2)
            self._close()
            raise BuilderError("PKHeX took too long to check this Pokemon.") from None
        if isinstance(reply, Exception):
            self._close()
            raise BuilderError("The Pokemon builder stopped.") from reply
        return reply

    def species(self, game: str) -> list[dict]:
        if game not in self.species_cache:
            self.species_cache[game] = sorted(self._ask({"cmd": "species", "game": game})["species"],
                                              key=lambda s: s["name"])
        return self.species_cache[game]

    def names(self, game: str, kind: str) -> list[dict]:
        """Names by ID; form IDs encode (national species << 8) | form, unlike cartridge species3 IDs."""
        key = f"{game}:{kind}"
        if key not in self.species_cache:
            names = self._ask({"cmd": "names", "game": game, "list": kind})["names"]
            self.species_cache[key] = sorted(names, key=lambda n: n["name"])
        return self.species_cache[key]

    def options(self, game: str, species: int, trainer: dict, version: str = "", form: int = 0) -> dict:
        """The forms, natures, abilities, held items, balls and effort kind an offer of this species can ask for."""
        key = f"{game}:options:{species}:{form}:{version}"
        if key not in self.species_cache:
            self.species_cache[key] = self._ask({"cmd": "options", "game": game, "species": species,
                                                 "form": form, "trainer": trainer, "version": version})
        return self.species_cache[key]

    def gender_ratio(self, game: str, species: int, form: int = 0) -> int:
        """The species' personal gender byte: 0 male only, 254 female only, 255 genderless."""
        return self._ask({"cmd": "gender_ratio", "game": game, "species": species, "form": form})["ratio"]

    def make(self, game: str, species: int, trainer: dict, level: int = 0, shiny: bool = False,
             nickname: str = "", version: str = "", options: dict | None = None) -> dict:
        """options: form, nature, ability, gender, held_item, ball (ids), friendship (0-255), moves (up to four
        ids), and ivs / effort as {hp, atk, def, spa, spd, spe}."""
        reply = self._ask({"cmd": "make", "game": game, "species": species, "level": level, "shiny": shiny,
                           "nickname": nickname, "trainer": trainer, "version": version,
                           "options": options or {}})
        reply["file"] = self.keep(game, reply)
        return reply

    def paste(self, game: str, text: str, trainer: dict, version: str = "") -> list[dict]:
        """The Showdown sets in `text`, each as make's values with its errors and notes (services/pkhex Paste)."""
        return self._ask({"cmd": "paste", "game": game, "text": text, "trainer": trainer,
                          "version": version})["sets"]

    def check_bytes(self, game: str, data: bytes, *, fresh=False, fields=None) -> dict:
        if not isinstance(game, str) or game not in RECORD_SIZES or len(data) > RECORD_LIMIT:
            raise BuilderError("This is not a Pokemon record of the selected game.")
        try:
            data = entity_bytes(game, data)
        except ValueError as exc:
            raise BuilderError("This is not a Pokemon record of the selected game.") from exc
        if len(data) not in RECORD_SIZES[game]:
            raise BuilderError("This is not a Pokemon record of the selected game.")
        return self._ask({"cmd": "check", "game": game, "data": base64.b64encode(data).decode(),
                          "fresh": fresh, "fields": fields or {}})

    def check(self, game: str, path: str) -> dict:
        return self.check_bytes(game, Path(path).expanduser().read_bytes())

    def owner(self, game: str, data: bytes) -> dict:
        """The owner of the Pokemon in `data`, as a console sends it, read with no legality check: species,
        shiny, egg, ot, tid and sid (16-bit), gender, language, handler (0 while it is still with its original
        trainer), the handling trainer's ht_name, ht_gender and ht_language (0 where the format keeps none), and
        version (PKHeX's number). BuilderError for a record PKHeX cannot read."""
        data = entity_bytes(game, data)
        return self._ask({"cmd": "owner", "game": game, "data": base64.b64encode(data).decode()})

    def import_file(self, game: str, path: str) -> dict:
        reply = self.check(game, path)
        if not reply["legal"]:
            raise BuilderError(reply["report"])
        reply["file"] = self.keep(game, reply)
        return reply

    def import_records(self, data: bytes, name: str, trainers: dict[str, dict]) -> dict:
        """Each Pokemon in a Pokemon file or a game save, as the bank would keep it [services/pkhex Import].
        `trainers` maps every game to the trainer who receives a Pokemon HOME moves there."""
        return self._ask({"cmd": "import", "game": "sv", "name": name, "trainers": trainers,
                          "data": base64.b64encode(data).decode()})

    def prepare(self, game: str, data: bytes, *, fresh=False, fields=None) -> bytes:
        reply = self.check_bytes(game, data, fresh=fresh, fields=fields)
        if not reply["legal"]:
            raise BuilderError(reply["report"])
        if reply.get("note"):
            print(f"[pokemon] the offer {reply['note']}", flush=True)
        return base64.b64decode(reply["data"])

    def move(self, source: str, game: str, data: bytes, tracker: int, trainer: dict) -> dict:
        """The banked Pokemon as `game` takes it from `trainer`, legal there, or BuilderError with the reason.
        `tracker` fills a HOME tracker only under home_tracker "made"."""
        return self._ask({"cmd": "move", "game": game, "source": source, "tracker": str(tracker),
                          "trainer": trainer,
                          "data": base64.b64encode(entity_bytes(source, data)).decode()})

    def destinations(self, source: str, data: bytes, tracker: int, trainer: dict) -> dict[str, dict]:
        """Each game key -> {"ok", "reason", "home_tracker"}: whether `move` would give a legal Pokemon there."""
        return self._ask({"cmd": "destinations", "game": source, "tracker": str(tracker), "trainer": trainer,
                          "data": base64.b64encode(entity_bytes(source, data)).decode()})["games"]

    def events(self) -> list[dict]:
        """PKHeX's Gen 3 event gifts a FireRed/LeafGreen can be sent."""
        return self._ask({"cmd": "events", "game": "frlg"})["events"]

    def event(self, name: str, language: int = 0) -> tuple[bytes, str]:
        """-> (decrypted .pk3 party record, summary): a fresh legal copy of the named event."""
        reply = self._ask({"cmd": "event", "game": "frlg", "name": name, "language": language})
        return base64.b64decode(reply["data"]), reply["summary"]

    def gift_events(self, game: str, trainer: dict) -> list[dict]:
        """The game's Mystery Gift Pokemon in PKHeX's event database, newest first, as `trainer` would receive
        each: key, card_id, title, date, species, form, form_id, level, shiny (never, random or always), tera, the card's
        own ot and language where it fixes them, ball, held_item, moves, legal, refused (`gift_event`'s), and
        home_tracker: a gift HOME gave has the tracker the HOME tracker setting gives it (HOME_TRACKER_WARNINGS)."""
        key = f"{game}:gift_events:{self.home_tracker}:{sorted(trainer.items())}"
        if key not in self.species_cache:
            self.species_cache[key] = self._ask({"cmd": "gift_events", "game": game, "trainer": trainer})["events"]
        return self.species_cache[key]

    def gift_event(self, game: str, key: str, trainer: dict, version: str = "", keep: bool = True) -> dict:
        """A fresh copy of one of `gift_events`, as `trainer`'s save receives it, kept like a built Pokemon:
        check's reply with its key, its card's title, your_ot (the card gives the receiver's own trainer, so
        the copy carries `trainer`), refused and the file. refused says why no save like `trainer`'s received
        the card, in its language or, with `version`, on that version; "" when one did, and such a copy is never
        kept. A gift HOME gave has the tracker the HOME tracker setting gives it. `version` (PKHeX's name, SL or
        VL) makes it on that version alone, as that save would receive it; without `keep` no file is written."""
        request = {"cmd": "gift_event", "game": game, "key": key, "trainer": trainer}
        if version:
            request.update(version=version, only_version=True)
        reply = self._ask(request)
        if keep and not reply["refused"]:
            reply["file"] = self.keep(game, reply)
        return reply

    def save_read(self, data: bytes) -> dict:
        """A FireRed/LeafGreen .sav: trainer, party (each with PKHeX's legality verdict) and box contents."""
        return self._ask({"cmd": "sav_read", "game": "frlg", "data": base64.b64encode(data).decode()})

    def save_box(self, data: bytes, box: int) -> list[dict | None]:
        """One box's Pokemon with their legality, None for an empty slot."""
        return self._ask({"cmd": "sav_box", "game": "frlg", "data": base64.b64encode(data).decode(),
                          "box": box})["mons"]

    def save_edit(self, data: bytes, *, trainer: dict | None = None, party: list | None = None) -> tuple[bytes, dict]:
        """-> (the edited .sav, save_read of it). trainer: name, gender, money, coins; party: in order,
        {"keep": n} for the save's slot n or {"data": base64 PK3}."""
        request = {"cmd": "sav_edit", "game": "frlg", "data": base64.b64encode(data).decode(),
                   "trainer": trainer or {}}
        if party is not None:
            request["party"] = party
        reply = self._ask(request)
        return base64.b64decode(reply["data"]), reply

    def validate_gift(self, data):
        from pokeldn.swsh import wc8
        if not wc8.sealed(data):
            raise BuilderError("The WC8 size or checksum is invalid.")
        return self._ask({"cmd": "gift", "game": "swsh", "data": base64.b64encode(data).decode()})

    def close(self):
        with self.lock:
            self._close()

    def _close(self):
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc.stdout.close()
            self.proc = None

    def keep(self, game: str, reply: dict) -> str:
        """Writes a reply's record where the offer queue keeps built Pokemon; returns the path."""
        data = base64.b64decode(reply["data"])
        folder = POKEMON / game
        folder.mkdir(parents=True, exist_ok=True)
        species = reply.get("canonical", {}).get("species", reply["species"])
        name = re.sub(r"[^A-Za-z0-9]+", "", species) or "pokemon"
        path = folder / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.{EXTENSIONS[game]}"
        path.write_bytes(data)
        return str(path)


SERVICE = Service()
atexit.register(SERVICE.close)


# What a reply's "home_tracker" means for HOME (docs/gui.md, The bank).
HOME_TRACKER_WARNINGS = {"empty": "PKHeX flags the missing HOME tracker", "made": "Can't be deposited in HOME"}


def summary(info: dict) -> str:
    info = {**info, **info.get("canonical", {})}
    parts = [f"{info['species']}-{info['form']}" if info.get("form") else info["species"], f"level {info['level']}"]
    if info.get("shiny"):
        parts.append("shiny")
    if info.get("nickname") and info.get("is_nicknamed", info["nickname"].lower() != info["species"].lower()):
        parts.append(f"'{info['nickname']}'")
    parts += [info.get("nature", ""), info.get("ability", ""), info.get("ball", "")]
    if info.get("held_item"):
        parts.append(f"holding {info['held_item']}")
    return " · ".join(p for p in parts if p)


def entity_bytes(game, data):
    data = bytes(data)
    try:
        data = bytes.fromhex(data.decode("ascii").strip())
    except (ValueError, UnicodeDecodeError):
        pass
    if game == "za" and len(data) == 354:
        from pokeldn.za.pokemon import parse_offer
        data = parse_offer(data)[1]
    elif game == "sv" and len(data) in (348, 352):
        from pokeldn.gen9 import from_wire
        data = from_wire(data[-348:])
    return data


def prepare(game, data, *, fresh=False, fields=None):
    return SERVICE.prepare(game, data, fresh=fresh, fields=fields)


def validate(game, data):
    prepare(game, data)
    return data


def offer_bytes(game, data):
    if game == "lgpe":
        return data[:232]
    if game == "za":
        from pokeldn.za.pokemon import build_offer
        return build_offer(ZA_OFFER_HEADER, data)
    return data


def prepare_offer(game, data, *, fresh=False, fields=None, transform=None):
    """-> `data` as a host offers it, through the offer check every offer takes: `transform`, PKHeX's check
    (`prepare`) and the game's offer form. A Mystery Gift made during the trade takes it too
    (pokeldn.receiver_gift)."""
    data = entity_bytes(game, data)
    if transform is not None:
        data = entity_bytes(game, transform(data))
    return offer_bytes(game, prepare(game, data, fresh=fresh, fields=fields))


def prepare_file(game, path, *, fresh=False, fields=None, transform=None):
    data = prepare_offer(game, Path(path).expanduser().read_bytes(), fresh=fresh, fields=fields,
                         transform=transform)
    folder = SESSION / "offers"
    folder.mkdir(parents=True, exist_ok=True)
    extension = "bin" if game == "za" else EXTENSIONS[game]
    target = folder / f"{game}-{uuid4().hex}.{extension}"
    target.write_bytes(data)
    return str(target)


def trade_path(path, n):
    """Where the n-th trade of one run writes what it received: `path` itself for the first."""
    if n <= 1 or not path:
        return path
    target = Path(path)
    return str(target.with_name(f"{target.stem}-{n}{target.suffix}"))


def save_received(game, path, data):
    from pokeldn.host_support import write_file
    data = entity_bytes(game, data)
    if game == "lgpe" and len(data) == 232:
        data += bytes(28)
    write_file(path, data)
