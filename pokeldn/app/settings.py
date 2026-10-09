import json
import os
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pokeldn.app.paths import DATA, RECEIVED

PATH = DATA / "settings.json"
LANGUAGES = (("2", "English"), ("3", "French"), ("5", "German"), ("4", "Italian"), ("7", "Spanish"),
             ("1", "Japanese"), ("8", "Korean"))
# Switch titles show the 32-bit trainer id as id % 10**6 and id // 10**6 (docs/gui.md, Your trainer).
SWITCH_TID_LIMIT = 1_000_000


@dataclass
class Settings:
    keys: str = str(Path.home() / ".switch" / "prod.keys")
    received: str = str(RECEIVED)
    radio_port: str = ""
    baud: int = 921600
    capture: bool = True
    board_trace: bool = False
    sprites: bool = True    # download Pokemon sprites from PokeAPI; the cache is read either way
    check_updates: bool = True   # ask GitHub for a newer release at launch
    firmware: str = ""
    firmware_kind: str = "radio"   # what Flash writes: "radio" (wireless) or "pad" (controller, S3 only)
    # Trainer used for generated encounters.
    ot: str = "POKELDN"
    tid: int = field(default_factory=lambda: random.randint(1, 65535))   # FireRed/LeafGreen, as shown
    sid: int = field(default_factory=lambda: random.randint(1, 65535))
    switch_tid: int | None = None   # the Switch titles' six-digit ID, as shown; None: the one tid/sid make
    switch_sid: int | None = None
    language: int = 2
    board_names: dict = field(default_factory=dict)   # MAC -> name the user gave the board
    tool_values: dict = field(default_factory=dict)   # tool key -> {"values": {...}, "extra": {...}}

    def __post_init__(self) -> None:
        if self.switch_tid is None or self.switch_sid is None:
            self.switch_sid, self.switch_tid = divmod(self.sid << 16 | self.tid, SWITCH_TID_LIMIT)

    def save(self) -> None:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, PATH)

    def ids(self, game: str) -> tuple[int, int]:
        """The 16-bit TID and SID a record of `game` stores."""
        if game == "frlg":
            return self.tid, self.sid
        whole = self.switch_sid * SWITCH_TID_LIMIT + self.switch_tid
        return whole & 0xFFFF, whole >> 16

    def name(self, game: str) -> str:
        """The trainer name `game` can hold: Japanese FRLG takes five Gen III characters."""
        if game != "frlg":
            return self.ot
        from pokeldn.frlg.text import charmap
        limit = 5 if int(self.language) == 1 else 7
        for name in (self.ot, self.ot[:limit]):
            encoded = charmap.encode(name, language=int(self.language))
            if name and charmap.decode(encoded, language=int(self.language)) == name and len(encoded) <= limit:
                return name
        return Settings.ot[:limit]

    def trainer(self, game: str) -> dict:
        tid, sid = self.ids(game)
        return {"ot": self.name(game), "tid": tid, "sid": sid, "language": self.language, "gender": 0}


def switch_ids_valid(tid: int, sid: int) -> bool:
    """A six-digit ID and its secret ID that one 32-bit trainer id can carry."""
    return 0 <= tid < SWITCH_TID_LIMIT and 0 <= sid and sid * SWITCH_TID_LIMIT + tid < 1 << 32


def load() -> Settings:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings must be an object")
    except (OSError, ValueError):
        settings = Settings()
        settings.save()   # keeps the trainer ids drawn above
        return settings
    known = Settings.__dataclass_fields__
    if data.get("ot") == "PkCamp":   # the default before POKELDN
        data["ot"] = Settings.ot
    return Settings(**{k: v for k, v in data.items() if k in known})
