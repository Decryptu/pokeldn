import json
import os
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pokeldn.app.paths import DATA, RECEIVED

PATH = DATA / "settings.json"
LANGUAGES = (("2", "English"), ("3", "French"), ("5", "German"), ("4", "Italian"), ("7", "Spanish"),
             ("1", "Japanese"), ("8", "Korean"))


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
    # Trainer used for generated encounters.
    ot: str = "PkCamp"
    tid: int = field(default_factory=lambda: random.randint(1, 65535))
    sid: int = field(default_factory=lambda: random.randint(1, 65535))
    language: int = 2
    board_names: dict = field(default_factory=dict)   # MAC -> name the user gave the board
    tool_values: dict = field(default_factory=dict)   # tool key -> {"values": {...}, "extra": {...}}

    def save(self) -> None:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, PATH)

    def trainer(self) -> dict:
        return {"ot": self.ot, "tid": self.tid, "sid": self.sid, "language": self.language, "gender": 0}


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
    return Settings(**{k: v for k, v in data.items() if k in known})
