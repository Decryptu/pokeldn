"""Legal Pokemon from PKHeX.Core, through the services/pkhex service, saved in the form each launcher reads."""
import base64
import glob
import json
import os
import re
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
EXTENSIONS = {"frlg": "pk3", "lgpe": "pb7", "bdsp": "pb8", "swsh": "pk8", "pla": "pa8", "sv": "pk9",
              "za": "pa9"}
ZA_OFFER_HEADER = bytes.fromhex("0101b90300bc815801")   # SelectPokemon, round 0 (docs/za.md)


class BuilderError(Exception):
    pass


def _command() -> list[str]:
    override = os.environ.get("POKELDN_PKHEX")
    if override:
        return ["dotnet", override] if override.endswith(".dll") else [override]
    # dist/ is the release build's single file; bin/ is a local `dotnet build -c Release`.
    found = [os.path.join(HERE, "dist", EXE), *glob.glob(os.path.join(HERE, "bin", "Release", "*", "*", EXE))]
    for path in found:
        if os.path.isfile(path):
            return [path]
    raise BuilderError("PKHeX is missing. From source, run: dotnet build -c Release services/pkhex")


class Service:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.species_cache: dict[str, list[dict]] = {}

    def _ask(self, request: dict) -> dict:
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                if self.proc is not None:
                    self.proc.stdin.close()
                    self.proc.stdout.close()
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                self.proc = subprocess.Popen(_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                             creationflags=flags)
            self.proc.stdin.write(json.dumps(request) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        if not line:
            raise BuilderError("The Pokemon builder stopped.")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise BuilderError(reply.get("error", "unknown error"))
        return reply

    def species(self, game: str) -> list[dict]:
        if game not in self.species_cache:
            self.species_cache[game] = sorted(self._ask({"cmd": "species", "game": game})["species"],
                                              key=lambda s: s["name"])
        return self.species_cache[game]

    def names(self, game: str, kind: str) -> list[dict]:
        """species, moves, items or balls the game has, by name."""
        key = f"{game}:{kind}"
        if key not in self.species_cache:
            names = self._ask({"cmd": "names", "game": game, "list": kind})["names"]
            self.species_cache[key] = sorted(names, key=lambda n: n["name"])
        return self.species_cache[key]

    def make(self, game: str, species: int, trainer: dict, level: int = 0, shiny: bool = False,
             nickname: str = "", version: str = "") -> dict:
        reply = self._ask({"cmd": "make", "game": game, "species": species, "level": level, "shiny": shiny,
                           "nickname": nickname, "trainer": trainer, "version": version})
        reply["file"] = self._save(game, reply)
        return reply

    def check_bytes(self, game: str, data: bytes, *, fresh=False, fields=None) -> dict:
        data = entity_bytes(game, data)
        return self._ask({"cmd": "check", "game": game, "data": base64.b64encode(data).decode(),
                          "fresh": fresh, "fields": fields or {}})

    def check(self, game: str, path: str) -> dict:
        return self.check_bytes(game, Path(path).expanduser().read_bytes())

    def import_file(self, game: str, path: str) -> dict:
        reply = self.check(game, path)
        if not reply["legal"]:
            raise BuilderError(reply["report"])
        reply["file"] = self._save(game, reply)
        return reply

    def prepare(self, game: str, data: bytes, *, fresh=False, fields=None) -> bytes:
        reply = self.check_bytes(game, data, fresh=fresh, fields=fields)
        if not reply["legal"]:
            raise BuilderError(reply["report"])
        return base64.b64decode(reply["data"])

    def validate_gift(self, data):
        from pokeldn.swsh import wc8
        if not wc8.sealed(data):
            raise BuilderError("The WC8 size or checksum is invalid.")
        return self._ask({"cmd": "gift", "game": "swsh", "data": base64.b64encode(data).decode()})

    def close(self):
        with self.lock:
            if self.proc is not None:
                self.proc.stdin.close()
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
                self.proc.stdout.close()
                self.proc = None

    def _save(self, game: str, reply: dict) -> str:
        data = base64.b64decode(reply["data"])
        folder = POKEMON / game
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9]+", "", reply["species"]) or "pokemon"
        path = folder / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.{EXTENSIONS[game]}"
        path.write_bytes(data)
        return str(path)


SERVICE = Service()
atexit.register(SERVICE.close)


def summary(info: dict) -> str:
    parts = [info["species"], f"level {info['level']}"]
    if info.get("shiny"):
        parts.append("shiny")
    if info.get("nickname") and info["nickname"].lower() != info["species"].lower():
        parts.append(f"'{info['nickname']}'")
    parts += [info.get("nature", ""), info.get("ball", "")]
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


def prepare_file(game, path, *, fresh=False, fields=None, transform=None):
    data = entity_bytes(game, Path(path).expanduser().read_bytes())
    if transform is not None:
        data = entity_bytes(game, transform(data))
    data = offer_bytes(game, prepare(game, data, fresh=fresh, fields=fields))
    folder = SESSION / "offers"
    folder.mkdir(parents=True, exist_ok=True)
    extension = "bin" if game == "za" else EXTENSIONS[game]
    target = folder / f"{game}-{uuid4().hex}.{extension}"
    target.write_bytes(data)
    return str(target)


def save_received(game, path, data):
    from pokeldn.host_support import write_file
    data = entity_bytes(game, data)
    if game == "lgpe" and len(data) == 232:
        data += bytes(28)
    write_file(path, data)
