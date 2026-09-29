import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PATH = Path.home() / ".pokeldn" / "settings.json"


@dataclass
class Settings:
    keys: str = str(Path.home() / ".switch" / "prod.keys")
    work_dir: str = str(Path.home() / "pokeldn")
    radio_port: str = ""
    baud: int = 921600
    capture: bool = True
    board_trace: bool = False
    firmware: str = ""
    board_names: dict = field(default_factory=dict)   # MAC -> name the user gave the board
    tool_values: dict = field(default_factory=dict)   # tool key -> {flag: value}

    def save(self) -> None:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.replace(tmp, PATH)

    def work_path(self, *parts: str) -> Path:
        return Path(os.path.expanduser(self.work_dir), *parts)


def load() -> Settings:
    try:
        data = json.loads(PATH.read_text())
    except (OSError, ValueError):
        return Settings()
    known = Settings.__dataclass_fields__
    return Settings(**{k: v for k, v in data.items() if k in known})
