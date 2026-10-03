"""A gift tool's one value: a preset, a built gift or an opened file. Each game's builder module
(pokeldn.frlg.gift.builder, pokeldn.swsh.gift_builder) supplies KINDS, PRESETS, blank(), compile()
and describe(); a built gift reaches the launcher as a .pokegift through --gift-file."""

import importlib
import os

from pokeldn import gifts
from pokeldn.app.paths import SESSION

GAMES = {"frlg-gift": "frlg", "swsh-gift": "swsh"}
MODULES = {"frlg": "pokeldn.frlg.gift.builder", "swsh": "pokeldn.swsh.gift_builder"}
MODES = (("preset", "Use a preset", "gift"), ("build", "Build your own", "sliders-horizontal"),
         ("file", "Open a file", "folder"))


def module(game):
    return importlib.import_module(MODULES[game])


def normalized(game, value):
    """Any stored value -> {"mode", "preset", "build", "file"}; a bare path is an opened file."""
    builder = module(game)
    if isinstance(value, str):
        value = {"mode": "file" if value else "preset", "file": value}
    value = dict(value or {})
    value.setdefault("mode", "preset")
    if value.get("preset") not in builder.PRESET:
        value["preset"] = builder.PRESETS[0].key
    value.setdefault("file", "")
    if not isinstance(value.get("build"), dict):
        value["build"] = builder.blank()
    return value


def output(tool):
    return str(SESSION / "gifts" / f"{tool.key}.pokegift")


def _built_state(game, value):
    """The form state the launcher gets as a file, or None when a preset goes as flags."""
    if value["mode"] == "build":
        return value["build"]
    if value["mode"] == "preset":
        preset = module(game).PRESET[value["preset"]]
        return None if preset.args else preset.state
    return None


def args(tool, value):
    game = GAMES[tool.key]
    value = normalized(game, value)
    if value["mode"] == "file":
        if not value["file"]:
            return []
        return ["--gift-file", output(tool) if value.get("icon") is not None else value["file"]]
    if _built_state(game, value) is None:
        return list(module(game).PRESET[value["preset"]].args)
    return ["--gift-file", output(tool)]


def compile(tool, value):
    game = GAMES[tool.key]
    value = normalized(game, value)
    if value["mode"] == "file":
        if not value["file"]:
            raise ValueError("Open a gift file, or choose a preset.")
        gift = gifts.load(value["file"], game=game)
        if value.get("icon") is not None:
            gift = gifts.adapter(game).with_icon(gift, value["icon"])
        return gift
    return module(game).compile(_built_state(game, value))


def prepare(tool, value):
    """Write the built gift where args() points the launcher. A preset sent as flags needs nothing."""
    game = GAMES[tool.key]
    value = normalized(game, value)
    if _built_state(game, value) is None and not (value["mode"] == "file" and value.get("icon") is not None):
        return
    path = output(tool)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gifts.save(path, compile(tool, value))


def problem(tool, value) -> str:
    """Why the gift cannot be sent as it stands, or ""."""
    game = GAMES[tool.key]
    value = normalized(game, value)
    if value["mode"] == "preset" and _built_state(game, value) is None:
        return ""
    try:
        compile(tool, value)
    except (OSError, ValueError) as exc:
        return str(exc)
    return ""
