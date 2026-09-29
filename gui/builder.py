"""Legal Pokemon from PKHeX.Core, through the gui/pkhex service, saved in the form each launcher reads."""
import base64
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time

from gui.paths import POKEMON, ROOT

HERE = os.path.join(ROOT, "gui", "pkhex")
EXE = "pokeldn-pkhex.exe" if sys.platform == "win32" else "pokeldn-pkhex"
# The file each game's launchers take as an offer.
EXTENSIONS = {"frlg": "pk3", "lgpe": "pb7", "bdsp": "pb8", "pla": "pa8", "sv": "pk9", "za": "bin"}
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
    raise BuilderError("The Pokemon builder is missing from this copy of the app.")


class Service:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.species_cache: dict[str, list[dict]] = {}

    def _ask(self, request: dict) -> dict:
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
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

    def check(self, game: str, path: str) -> dict:
        with open(path, "rb") as fh:
            data = fh.read()
        if game == "za":
            from pokeldn.za import pokemon
            data = pokemon.parse_offer(data)[1]
        return self._ask({"cmd": "check", "game": game, "data": base64.b64encode(data).decode()})

    def _save(self, game: str, reply: dict) -> str:
        data = base64.b64decode(reply["data"])
        if game == "za":
            from pokeldn.za import pokemon
            data = pokemon.build_offer(ZA_OFFER_HEADER, data)
        folder = POKEMON / game
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9]+", "", reply["species"]) or "pokemon"
        path = folder / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.{EXTENSIONS[game]}"
        path.write_bytes(data)
        return str(path)


SERVICE = Service()


def summary(info: dict) -> str:
    parts = [info["species"], f"level {info['level']}"]
    if info.get("shiny"):
        parts.append("shiny")
    if info.get("nickname") and info["nickname"].lower() != info["species"].lower():
        parts.append(f"'{info['nickname']}'")
    parts += [info.get("nature", ""), info.get("ball", "")]
    return " · ".join(p for p in parts if p)
