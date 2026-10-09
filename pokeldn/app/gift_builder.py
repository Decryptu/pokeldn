"""A gift tool's one value: a preset, a built gift or an opened file. Each game's builder module
(pokeldn.frlg.gift.builder, pokeldn.swsh.gift_builder) supplies KINDS, PRESETS, blank(), compile()
and describe(); a built gift reaches the launcher as a .pokegift through --gift-file."""

import importlib
import os

from pokeldn import gifts
from pokeldn.app.paths import SESSION

GAMES = {"frlg-gift": "frlg", "swsh-gift": "swsh"}
MODULES = {"frlg": "pokeldn.frlg.gift.builder", "swsh": "pokeldn.swsh.gift_builder"}
MODES = (("preset", "Use a preset", "gift"), ("event", "Official events", "book-open"),
         ("build", "Build your own", "sliders-horizontal"), ("file", "Open a file", "folder"),
         ("save", "Your save", "save"))
# The save mode backs the console's save up into the library or restores one from it [docs/frlg_gift.md].
SAVE_GAMES = ("frlg",)
SAVE_ACTIONS = ("backup", "restore")


def modes(game):
    """The modes a game's tool offers: official events only where the builder ships them, the
    save only on FireRed and LeafGreen."""
    return [m for m in MODES if (m[0] != "event" or hasattr(module(game), "OFFICIAL"))
            and (m[0] != "save" or game in SAVE_GAMES)]


def module(game):
    return importlib.import_module(MODULES[game])


def normalized(game, value):
    """Any stored value -> {"mode", "preset", "options", "build", "file"}; a bare path is an opened file.
    "options" holds each preset's settings by preset key."""
    builder = module(game)
    if isinstance(value, str):
        value = {"mode": "file" if value else "preset", "file": value}
    value = dict(value or {})
    value.setdefault("mode", "preset")
    if not isinstance(value.get("options"), dict):
        value["options"] = {}
    if value.get("preset") in getattr(builder, "ALIASES", {}):
        value["preset"], settings = builder.ALIASES[value["preset"]]
        value["options"][value["preset"]] = {**value["options"].get(value["preset"], {}), **settings}
    if value["mode"] not in {m[0] for m in modes(game)}:
        value["mode"] = "preset"
    if hasattr(builder, "OFFICIAL") and value.get("event") not in builder.OFFICIAL.by_key():
        value["event"] = builder.OFFICIAL.load()[0]["key"]
    if value.get("preset") not in builder.PRESET:
        value["preset"] = builder.PRESETS[0].key
    value.setdefault("file", "")
    if not isinstance(value.get("save"), dict):
        value["save"] = {}
    value["save"].setdefault("action", "backup")
    if value["save"]["action"] not in SAVE_ACTIONS:
        value["save"]["action"] = "backup"
    value["save"].setdefault("file", "")
    if not isinstance(value.get("build"), dict):
        value["build"] = builder.blank()
    return value


def preset_args(game, value):
    """The flags a preset sent as flags passes, its settings applied."""
    preset = module(game).PRESET[value["preset"]]
    arguments = getattr(preset, "arguments", None)
    return list(arguments(value["options"].get(preset.key)) if arguments else preset.args)


def output(tool):
    return str(SESSION / "gifts" / f"{tool.key}.pokegift")


def _built_state(game, value):
    """The form state the launcher gets as a file, or None when a preset goes as flags."""
    if value["mode"] == "event":
        return {}
    if value["mode"] == "build":
        return value["build"]
    if value["mode"] == "preset":
        preset = module(game).PRESET[value["preset"]]
        return None if preset.args else preset.state
    return None


def save_args(value):
    """--save-backup into the library under the run's {stamp}, or --save-restore of the chosen file."""
    from pokeldn.app import saves
    chosen = value["save"]
    if chosen["action"] == "restore":
        return ["--save-restore", chosen["file"]] if chosen["file"] else []
    return ["--save-backup", saves.backup_target(), "--save-resume-dir", saves.partial_dir()]


def save_problem(value):
    from pokeldn.frlg.save import sav
    chosen = value["save"]
    if chosen["action"] != "restore":
        return ""
    if not chosen["file"]:
        return "Choose the save to put on the console."
    try:
        with open(chosen["file"], "rb") as handle:
            if not sav.describe(handle.read()).sound:
                return "This save has no whole copy of a game in it."
    except (OSError, sav.SaveError) as exc:
        return str(exc)
    if not chosen.get("anyway"):
        from pokeldn.app import saves
        check = saves.cached_check(chosen["file"])     # the save panel reads it off the UI thread
        if check is None:
            return "Checking the save's party with PKHeX..."
        illegal = check["illegal"]
        if illegal:
            return (f"PKHeX finds {', '.join(illegal)} in this save's party not legal. Fix it in the "
                    "editor, or turn on Restore anyway.")
    return ""


def args(tool, value):
    game = GAMES[tool.key]
    value = normalized(game, value)
    if value["mode"] == "save":
        return save_args(value)
    if value["mode"] == "file":
        if not value["file"]:
            return []
        return ["--gift-file", output(tool) if value.get("icon") is not None else value["file"]]
    if _built_state(game, value) is None:
        return preset_args(game, value)
    return ["--gift-file", output(tool)]


def compile(tool, value):
    game = GAMES[tool.key]
    value = normalized(game, value)
    if value["mode"] == "save":
        raise ValueError("A save backup or restore sends no gift.")
    if value["mode"] == "file":
        if not value["file"]:
            raise ValueError("Open a gift file, or choose a preset.")
        gift = gifts.load(value["file"], game=game)
        if value.get("icon") is not None:
            gift = gifts.adapter(game).with_icon(gift, value["icon"])
        return gift
    if value["mode"] == "event":
        return module(game).OFFICIAL.gift(value["event"])
    return module(game).compile(_built_state(game, value))


def prepare(tool, value):
    """Write the built gift where args() points the launcher. A preset sent as flags needs nothing."""
    game = GAMES[tool.key]
    value = normalized(game, value)
    if value["mode"] == "save":
        return
    if _built_state(game, value) is None and not (value["mode"] == "file" and value.get("icon") is not None):
        return
    path = output(tool)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gifts.save(path, compile(tool, value))


def problem(tool, value) -> str:
    """Why the gift cannot be sent as it stands, or ""."""
    game = GAMES[tool.key]
    value = normalized(game, value)
    if value["mode"] == "save":
        return save_problem(value)
    if value["mode"] == "preset" and _built_state(game, value) is None:
        preset = module(game).PRESET[value["preset"]]
        check = getattr(preset, "problem", None)
        return check(value["options"].get(preset.key)) if check else ""
    try:
        compile(tool, value)
    except (OSError, ValueError) as exc:
        return str(exc)
    return ""
