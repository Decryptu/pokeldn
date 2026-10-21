"""Display boundaries resolve semantic references and entity identities, never English text."""
from pokeldn.app.i18n import ref as _ref
from dataclasses import fields, is_dataclass
import flet as ft
from pokeldn import pokemon
from pokeldn.app import i18n
from pokeldn.app.i18n_types import DisplayText, EntityKind, MessageRef, TextRef


def date_time(seconds):
    return i18n.text("core.presentation.timestamp", value=seconds)


def translate(value):
    return i18n.render(value)


def error_message(error):
    value = getattr(error, "message", error)
    if isinstance(error, Exception) and error.args and isinstance(error.args[0], (MessageRef, DisplayText, TextRef)):
        value = error.args[0]
    return i18n.render(value)


def summary_text(value):
    # Unstructured imported summaries and player text are opaque.
    return i18n.render(value)


def summary_lines(value):
    parts = summary_text(value).split(" · ")
    return i18n.join(parts[:2], " · "), i18n.join(parts[2:], " · ")


def display_summary(value, game=None):
    if hasattr(value, "species_id") and hasattr(value, "path"):
        from pokeldn.app import bank
        return summary(bank.display_info(value))
    if isinstance(value, dict) and value.get("display"):
        return summary(value["display"])
    if isinstance(value, dict) and game and value.get("file"):
        from pathlib import Path
        path = Path(value["file"]).expanduser()
        if path.is_file():
            try:
                value["display"] = pokemon.SERVICE.identity(game, path.read_bytes())
                return summary(value["display"])
            except (OSError, ValueError, pokemon.BuilderError):
                pass
    return summary_text(value.get("summary", "") if isinstance(value, dict) else value)


def summary(info):
    game = info.get("game", "sv")
    parts = []
    species = info.get("species_id")
    parts.append(i18n.name(EntityKind.SPECIES, species, game=game, form=info.get("form_id", 0))
                 if species is not None else info.get("species", ""))
    if info.get("level") is not None:
        parts.append(i18n.text("core.presentation.level", level=info["level"]))
    if info.get('shiny'):
        parts.append(i18n.text("core.presentation.shiny"))
    if info.get("is_nicknamed") and info.get("nickname"):
        parts.append("'" + info["nickname"] + "'")
    if info.get("nature_id") is not None:
        parts.append(i18n.text("core.presentation.nature", nature=i18n.name(EntityKind.NATURE, info["nature_id"], game=game)))
    if info.get("ability_id"):
        parts.append(i18n.name(EntityKind.ABILITY, info["ability_id"], game=game))
    if info.get("held_item_id"):
        parts.append(i18n.text("core.presentation.held_item", item=i18n.name(EntityKind.ITEM, info["held_item_id"], game=game)))
    if info.get("ball_id"):
        parts.append(i18n.name(EntityKind.BALL, info["ball_id"], game=game))
    if info.get("move_ids"):
        moves = i18n.text("core.presentation.list_separator").join(i18n.name(EntityKind.MOVE, n, game=game) for n in info["move_ids"])
        parts.append(i18n.text("core.presentation.moves", moves=moves))
    return DisplayText(" · ", ("literal", " · ")).join(parts)


def gift_description(game, state, name):
    from pokeldn.app.gift_builder import module
    builder = module(game)
    if game == "frlg":
        state = builder.cartridge_state(state)
        lookup = name
        name = lambda kind, number: lookup(kind, builder.national_species(int(number or 0)) if kind == "species" else number)
    when, lines = builder.describe(state, name)
    return translate(when), [translate(line) for line in lines]


def app_log(line):
    return i18n.render(line) if isinstance(line, (MessageRef, TextRef, DisplayText)) else line


def flet_locale():
    language, *parts = i18n.locale().split("-")
    script = next((p.title() for p in parts if len(p) == 4), None)
    region = next((p.upper() for p in parts if len(p) == 2 or p.isdigit()), None)
    current = ft.Locale(language.lower(), region, script)
    return ft.LocaleConfiguration(supported_locales=[ft.Locale("en"), current], current_locale=current)


def localize_controls(root):
    """Relabel the existing control graph, preserving focus, user input and callbacks."""
    seen, changed = set(), []
    def walk(value):
        if isinstance(value, (DisplayText, TextRef)):
            return i18n.render(value)
        if id(value) in seen:
            return value
        if isinstance(value, (list, tuple)):
            seen.add(id(value))
            items = [walk(item) for item in value]
            return tuple(items) if isinstance(value, tuple) else items
        if isinstance(value, dict):
            seen.add(id(value))
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, ft.BaseControl):
            seen.add(id(value))
            bindings = value._internals.setdefault("localization", {})
            for field in fields(value):
                key = field.name
                if key.startswith("_") or key in ("data", "key"):
                    continue
                item = getattr(value, key)
                if isinstance(item, (DisplayText, TextRef)):
                    bindings[key] = (item, str(item))
                elif key in bindings:
                    reference, previous = bindings[key]
                    if isinstance(item, str) and item == previous:
                        item = reference
                    else:
                        bindings.pop(key)
                localized = walk(item)
                if localized is not item:
                    setattr(value, key, localized)
                    if key in bindings:
                        bindings[key] = (bindings[key][0], str(localized))
                    if isinstance(localized, str):
                        changed.append(value)
            return value
        if is_dataclass(value) and value.__class__.__module__.startswith("flet"):
            seen.add(id(value))
            for field in fields(value):
                if not field.name.startswith("_"):
                    item = getattr(value, field.name)
                    localized = walk(item)
                    if localized is not item:
                        setattr(value, field.name, localized)
        return value
    walk(root)
    return changed


class DisplayService(pokemon.Service):
    """Business services filter IDs; localization supplies labels for those exact IDs."""
    def __init__(self):
        super().__init__()
        self._caches = {}

    @property
    def species_cache(self):
        return self._caches.setdefault(i18n.identity(), {})

    @species_cache.setter
    def species_cache(self, value):
        self._caches = {}

    def _ask(self, request):
        token = i18n.identity()
        reply = pokemon.SERVICE._ask({**request, "display_language": token[1]})
        game = request.get("game", "sv")
        def labels(values, kind):
            for entry in values:
                entry["name"] = i18n.name(kind, int(entry["id"]), game=game)
        cmd = request.get("cmd")
        if cmd == "species":
            labels(reply["species"], EntityKind.SPECIES)
        if cmd == "names":
            kind = {"species": EntityKind.SPECIES, "moves": EntityKind.MOVE, "items": EntityKind.ITEM,
                    "bag": EntityKind.ITEM, "held": EntityKind.ITEM, "balls": EntityKind.BALL}.get(request["list"])
            if kind:
                labels(reply["names"], kind)
        if cmd == "options":
            for key, kind in (("natures", EntityKind.NATURE), ("abilities", EntityKind.ABILITY),
                              ("held", EntityKind.ITEM), ("balls", EntityKind.BALL)):
                labels(reply.get(key, []), kind)
            for entry in reply.get("forms", []):
                entry["name"] = i18n.name(EntityKind.SPECIES, int(request["species"]), game=game, form=int(entry["id"]))
        def record(info):
            info["game"] = game
            for key, kind in (("species", EntityKind.SPECIES), ("nature", EntityKind.NATURE),
                              ("ability", EntityKind.ABILITY), ("ball", EntityKind.BALL), ("held_item", EntityKind.ITEM)):
                if info.get(key + "_id") is not None:
                    info[key] = ("" if key == "held_item" and not info[key + "_id"] else
                        i18n.name(kind, info[key + "_id"], game=game,
                            form=info.get("form_id", 0) if key == "species" else None))
            if "move_ids" in info:
                info["moves"] = [i18n.name(EntityKind.MOVE, move, game=game) for move in info["move_ids"]]
            if info.get("tera_type_id") is not None:
                info["tera"] = i18n.name(EntityKind.TYPE, info["tera_type_id"], game=game)
        if "species_id" in reply:
            record(reply)
        if cmd == "gift_events":
            for info in reply.get("events", []):
                record(info)
        return reply

    def close(self):
        pass


SERVICE = DisplayService()
