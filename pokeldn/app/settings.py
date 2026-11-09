import json
import os
import random
import shutil
import time
import types
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pokeldn import console_trainer
from pokeldn.app.paths import DATA, RECEIVED

PATH = DATA / "settings.json"
LANGUAGES = (("2", "English"), ("3", "French"), ("5", "German"), ("4", "Italian"), ("7", "Spanish"),
             ("1", "Japanese"), ("8", "Korean"))
# Switch titles show the 32-bit trainer id as id % 10**6 and id // 10**6 (docs/gui.md, Your trainer).
SWITCH_TID_LIMIT = 1_000_000
GEN3 = ("frlg", "rse")      # games whose records keep a 16-bit TID and SID and a Gen III name
TRAINER_LANGUAGES = {1, 2, 3, 4, 5, 7, 8, 9, 10}   # PKHeX LanguageID Settings offers
# A game sold as two versions -> each version's key and PKHeX version number: with a trainer per game, each
# version keeps its own save's trainer and the tool's "Your game" picks one (docs/gui.md, A trainer per game).
VERSIONS = {"frlg": (("firered", 4), ("leafgreen", 5)), "lgpe": (("pikachu", 42), ("eevee", 43)),
            "swsh": (("sword", 44), ("shield", 45)), "bdsp": (("bd", 48), ("sp", 49)),
            "sv": (("scarlet", 50), ("violet", 51))}
VERSION_GAME = {key: game for game, versions in VERSIONS.items() for key, _ in versions}


@dataclass
class Settings:
    keys: str = str(Path.home() / ".switch" / "prod.keys")
    received: str = str(RECEIVED)
    radio_port: str = ""
    radio: str = ""         # external radio scheme (pokeldn.ldn.radios); empty: the board
    plugins: list = field(default_factory=list)   # plugin ids turned on
    app_language: str = ""   # language-pack plugin id; empty selects English
    baud: int = 921600
    tx_power: float = 0     # the board's transmit power cap in dBm; 0: the driver's maximum
    capture: bool = True
    private_logs: bool = True   # mask names, trainer IDs, MACs and the home folder in the logs shown (redact.py)
    board_trace: bool = False
    board_screen: bool = False   # draw the board's screen in the Session panel (pokeldn.app.screen_render)
    larger_text: bool = False    # every text 15 % larger (gui/theme.py text_scale); read at launch
    retry_trades: bool = False   # a trade run that failed starts again on the trades left (gui/views/games.py)
    sprites: bool = True    # download Pokemon sprites from PokeAPI; the cache is read either way
    check_updates: bool = True   # ask GitHub for a newer release at launch
    # "empty" or "made": what the bank and the builder put in a HOME tracker HOME never issued (docs/gui.md,
    # The bank); pokeldn.pokemon.Service sends it with every request.
    home_tracker: str = "empty"
    allow_illegal: bool = False   # PKHeX-flagged Pokemon may be built, kept and traded, never put on the GTS
    bank_illegal: bool = False    # an import keeps a PKHeX-flagged Pokemon in the bank (docs/gui.md, Non-legal Pokemon)
    # Trainer used for generated encounters.
    ot: str = "POKELDN"
    tid: int = field(default_factory=lambda: random.randint(1, 65535))   # FireRed/LeafGreen, as shown
    sid: int = field(default_factory=lambda: random.randint(1, 65535))
    switch_tid: int | None = None   # the Switch titles' six-digit ID, as shown; None: the one tid/sid make
    switch_sid: int | None = None
    language: int = 2
    # 0 male, 1 female. Legends Z-A checks it before taking a Pokemon back as its trainer's, and Legends
    # Arceus's data exchange record carries it.
    gender: int = 0
    # With per_game_trainer, game -> the fields of the trainer above it replaces for that game: ot, gender, language,
    # and tid and sid as that game shows them (docs/gui.md, A trainer per game).
    per_game_trainer: bool = False
    game_trainers: dict = field(default_factory=dict)
    # "gba" or "switch" -> the newest console trainer a run reported (pokeldn.console_trainer), for Find mine.
    found_trainers: dict = field(default_factory=dict)
    played: dict = field(default_factory=dict)      # game -> the version key its tools run as (VERSIONS)
    board_names: dict = field(default_factory=dict)   # MAC -> name the user gave the board
    tool_values: dict = field(default_factory=dict)   # tool key -> {"values": {...}, "extra": {...}}
    bank_view: dict = field(default_factory=dict)     # the Bank's "sort", "only" and "dex_only" choices

    def __post_init__(self) -> None:
        if self.switch_tid is None or self.switch_sid is None:
            self.switch_sid, self.switch_tid = divmod(self.sid << 16 | self.tid, SWITCH_TID_LIMIT)

    def save(self) -> None:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, PATH)

    def version(self, game: str) -> str:
        """The version `game`'s tools run as: the one picked, else its first."""
        versions = [key for key, _ in VERSIONS.get(game, ())]
        return self.played.get(game) if self.played.get(game) in versions else (versions[0] if versions else game)

    def own(self, game: str) -> dict:
        """`game`'s trainer as the player sees it: ot, gender, language, and tid and sid as the game shows them.
        `game` is a game key or a version key; a game with versions reads the picked version's trainer, and a
        version never edited reads its game's."""
        version, game = (game, VERSION_GAME[game]) if game in VERSION_GAME else (self.version(game), game)
        shown = {"ot": self.ot, "gender": self.gender, "language": self.language,
                 "tid": self.tid if game in GEN3 else self.switch_tid,
                 "sid": self.sid if game in GEN3 else self.switch_sid}
        if self.per_game_trainer:
            for own in (self.game_trainers.get(game), self.game_trainers.get(version)):
                for key, value in (own.items() if isinstance(own, dict) else ()):
                    if key in shown and type(value) is type(shown[key]):
                        shown[key] = value
        return shown

    def split(self, game: str) -> bool:
        """`game`'s versions hold different trainers, so its tools ask which one runs."""
        versions = VERSIONS.get(game, ())
        return self.per_game_trainer and len({json.dumps(self.own(key), sort_keys=True) for key, _ in versions}) > 1

    def names(self) -> list[str]:
        """Every trainer name a run can present, the shared one and each game's own: the private-log masks."""
        own = [g.get("ot") for g in self.game_trainers.values() if isinstance(g, dict)] if self.per_game_trainer else []
        return list(dict.fromkeys(n for n in [self.ot, *own] if isinstance(n, str) and n))

    def set_own(self, game: str, key: str, value) -> None:
        """Sets one field of `game`'s own trainer; the others start as the shared trainer's."""
        self._keep_own(game, {key: value})
        self.save()

    def _keep_own(self, game: str, fields: dict) -> None:
        own = {**self.own(game), **fields}
        self.game_trainers.pop(game, None)     # last in the dict: last_edited
        self.game_trainers[game] = own

    def last_edited(self, games) -> str | None:
        """The newest of `games` given its own trainer: Settings opens on it after a restart."""
        return next((game for game in reversed(self.game_trainers) if game in games), None)

    def ids(self, game: str) -> tuple[int, int]:
        """The 16-bit TID and SID a record of `game` stores."""
        shown, game = self.own(game), VERSION_GAME.get(game, game)
        if game in GEN3:
            return shown["tid"], shown["sid"]
        whole = shown["sid"] * SWITCH_TID_LIMIT + shown["tid"]
        return whole & 0xFFFF, whole >> 16

    def name(self, game: str) -> str:
        """The trainer name `game` can hold: Japanese FRLG takes five Gen III characters."""
        shown, game = self.own(game), VERSION_GAME.get(game, game)
        if game not in GEN3:
            return shown["ot"]
        from pokeldn.frlg.text import charmap
        language = int(shown["language"])
        limit = 5 if language == 1 else 7
        for name in (shown["ot"], shown["ot"][:limit]):
            encoded = charmap.encode(name, language=language)
            if name and charmap.decode(encoded, language=language) == name and len(encoded) <= limit:
                return name
        return Settings.ot[:limit]

    def found(self, message: dict) -> None:
        """Keeps a run's `[trainer]` message as the newest of its row ("gba" or "switch") and of its game."""
        row = "gba" if message["game"] in GEN3 else "switch"
        self.found_trainers[row] = self.found_trainers[message["game"]] = {**message, "when": time.time()}
        version = next((key for key, number in VERSIONS.get(message["game"], ()) if number == message.get("version")), None)
        if version:
            self.found_trainers[version] = self.found_trainers[row]
        self.save()

    def take_found(self, row: str) -> dict | None:
        """Takes the newest found trainer of `row` ("gba", "switch", or a game for a trainer per game) as this
        trainer: its IDs, and its name, gender and language where known. -> what it took, None when no run
        reported one."""
        found = self.found_trainers.get(row)
        if not found and row not in ("gba", "switch"):     # a run that named its game only
            number = dict(VERSIONS.get(VERSION_GAME.get(row), ())).get(row)
            found = next((f for f in self.found_trainers.values() if isinstance(f, dict)
                          and f.get("game") == VERSION_GAME.get(row, row) and f.get("version") in (None, number)), None)
        if not found:
            return None
        tid, sid = console_trainer.shown(found["game"], found["tid"], found["sid"])
        taken = {"tid": tid, "sid": sid, "ot": str(found["ot"])[:12] or self.ot}
        if found.get("gender") in (0, 1):
            taken["gender"] = found["gender"]
        if found.get("language") in TRAINER_LANGUAGES:
            taken["language"] = found["language"]
        if row not in ("gba", "switch"):
            self._keep_own(row, taken)
        else:
            if row == "gba":
                self.tid, self.sid = taken.pop("tid"), taken.pop("sid")
            else:
                self.switch_tid, self.switch_sid = taken.pop("tid"), taken.pop("sid")
            for key, value in taken.items():
                setattr(self, key, value)
        self.save()
        return found

    def trainer(self, game: str) -> dict:
        tid, sid = self.ids(game)
        shown = self.own(game)
        return {"ot": self.name(game), "tid": tid, "sid": sid, "language": shown["language"],
                "gender": shown["gender"]}


def switch_ids_valid(tid: int, sid: int) -> bool:
    """A six-digit ID and its secret ID that one 32-bit trainer id can carry."""
    return 0 <= tid < SWITCH_TID_LIMIT and 0 <= sid and sid * SWITCH_TID_LIMIT + tid < 1 << 32


BAD = PATH.with_name("settings.json.bad")
# A restore's settings (pokeldn.app.backup), put in place at the app's next launch: the running app
# would save its own over them.
STAGED = PATH.with_name("settings.restore.json")


def apply_staged() -> bool:
    """At launch, before the first load: True when a restore's settings replaced the current ones."""
    try:
        os.replace(STAGED, PATH)
        return True
    except FileNotFoundError:
        return False
# What the last load() could not use: {"path": the copy kept at BAD, "fields": the names reset, empty when
# the whole file was unreadable}. It outlives later loads in the process (gui/main.py loads twice), so the
# app can tell the player once.
damaged: dict | None = None


def _fits(kind, value) -> bool:
    if isinstance(kind, types.UnionType):
        return any(_fits(k, value) for k in kind.__args__)
    if kind is type(None):
        return value is None
    if kind in (int, float):
        return isinstance(value, (int, float) if kind is float else int) and not isinstance(value, bool)
    return isinstance(value, kind)


def _set_aside(fields: list[str]) -> None:
    """Keeps the file the player's settings were in before load() replaces any of it."""
    global damaged
    try:
        shutil.copyfile(PATH, BAD)
    except OSError:
        pass
    damaged = {"path": str(BAD), "fields": fields}


def load() -> Settings:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings must be an object")
    except FileNotFoundError:
        settings = Settings()
        settings.save()   # keeps the trainer ids drawn above
        return settings
    except (OSError, ValueError):
        _set_aside([])
        settings = Settings()
        settings.save()
        return settings
    known = Settings.__dataclass_fields__
    if data.get("ot") == "PkCamp":   # the default before POKELDN
        data["ot"] = Settings.ot
    from pokeldn.app import ios
    if ios.active():
        data = {k: ios.rebase(v) for k, v in data.items()}
    wrong = [k for k, v in data.items() if k in known and not _fits(known[k].type, v)]
    if wrong:
        _set_aside(wrong)
    settings = Settings(**{k: v for k, v in data.items() if k in known and k not in wrong})
    if wrong:
        settings.save()
    return settings
