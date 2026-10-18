"""Language-neutral presentation of game data and legacy module messages.

Only controls use these adapters. Stored IDs, cartridge text, trainer input and wire values
remain owned by the game modules; language packs supply all translated text as data.
"""
import atexit
import functools
import re
import time

from pokeldn import pokemon
from pokeldn.app import i18n
from pokeldn.app.i18n import t as tr


def date_time(seconds: float) -> str:
    """Format stored timestamps only at the presentation boundary."""
    return time.strftime(tr("presentation.date_time_format", "%d %b %Y, %H:%M"), time.localtime(seconds))


def names(value: str) -> str:
    return i18n.terms(value)


def translate(value: str) -> str:
    translated = i18n.message(value)
    if translated != value:
        return translated
    # Shared reminders can follow otherwise independent module descriptions.
    from pokeldn.frlg.gift import builder as frlg
    for suffix in (" Turns off any game boost that is on.", frlg.MOM_STEPS):
        if value.endswith(suffix) and value != suffix:
            return translate(value[:-len(suffix)]) + i18n.message(suffix)
    return names(value)


def error_message(error: Exception | str) -> str:
    """Keep OS errors and unrecognized diagnostics literal, including file and player names."""
    value = str(error)
    if isinstance(error, OSError):
        return value
    translated = i18n.message(value)
    return translated if translated != value else value


class DisplayService(pokemon.Service):
    """A separate service for UI copy, with caches isolated from the canonical game service."""
    def __init__(self):
        super().__init__(display_language=i18n.locale())

    def _sync_language(self):
        selected = i18n.locale()
        with self.lock:
            if selected != self.display_language:
                self.species_cache.clear()
                self.display_language = selected

    def _ask(self, request):
        self._sync_language()
        try:
            reply = super()._ask(request)
        except pokemon.BuilderError as exc:
            raise pokemon.BuilderError(error_message(exc)) from exc
        for found in reply.get("sets", ()):
            for key in ("errors", "notes"):
                found[key] = [error_message(line) for line in found.get(key, ())]
        if "encounter" in reply:
            reply["encounter"] = translate(reply["encounter"])
        if "problems" in reply:
            reply["problems"] = "\n".join(error_message(line) for line in reply["problems"].splitlines())
        for route in reply.get("games", {}).values():
            route["reason"] = error_message(route.get("reason", ""))
        return reply

    def species(self, game):
        self._sync_language()
        return super().species(game)

    def names(self, game, kind):
        self._sync_language()
        return super().names(game, kind)

    def options(self, *args, **kwargs):
        self._sync_language()
        return super().options(*args, **kwargs)

    def gift_events(self, *args, **kwargs):
        self._sync_language()
        return super().gift_events(*args, **kwargs)


SERVICE = DisplayService()
atexit.register(SERVICE.close)


@functools.cache
def _game_terms(game: str, language: str) -> dict[str, str]:
    result = {}
    for kind in ("moves", "items", "balls", "natures", "abilities"):
        localized = {n["id"]: n["name"] for n in SERVICE.names(game, kind)}
        result.update((n["name"], localized[n["id"]]) for n in pokemon.SERVICE.names(game, kind)
                      if n["id"] in localized)
    return result


def game_terms(game: str) -> dict[str, str]:
    """Older peers send display names; pair their English names with localized names by ID."""
    return _game_terms(game, i18n.locale()) if i18n.locale() != "en" else {}


def import_note(value: str) -> str:
    if i18n.locale() == "en":
        return value
    parts = []
    for part in value.split(" · "):
        if part.startswith("Left its ") and part.endswith(" behind"):
            item = part[len("Left its "):-len(" behind")]
            terms = {**game_terms("swsh"), **game_terms("frlg")}
            parts.append(tr("presentation.left_item", "Left its {item} behind", item=terms.get(item, item)))
        elif part.startswith("Forgot "):
            moves = part[len("Forgot "):].split(", ")
            terms = game_terms("sv")
            parts.append(tr("presentation.forgot_moves", "Forgot {moves}",
                            moves=tr("presentation.list_separator", ", ").join(terms.get(move, move) for move in moves)))
        else:
            parts.append(translate(part))
    return " · ".join(parts)


def summary(info: dict) -> str:
    return summary_text(pokemon.summary({key: value for key, value in info.items() if key != "canonical"}))


def gift_description(game, state, name):
    from pokeldn.app.gift_builder import module
    when, lines = module(game).describe(state, name)
    return translate(when), [translate(line) for line in lines]


def raid_label(value: str) -> str:
    """Gallery labels only; never change the directory key used to select a raid."""
    if i18n.locale() == "en":
        return value
    value = value.replace("Inceneroar", "Incineroar")
    for source in (
        "Mighty Mewtwo Showdown - Prepare the Offense!", "Mighty Mewtwo Showdown - A Show of Supporters",
        "Mighty Mewtwo Showdown - ", "Prepare for Tricks and Treats from Mismagius!",
        "Happy Valentine's Day", "Valentines Day", "Hard to Find Pokemon", "Presents from ",
        "Hisuian ", "Alolan ", "Worthy ", "Shiny ",
    ):
        value = value.replace(source, i18n.message(source))
    value = i18n.message(value)
    value = re.sub(r"\bRound \d+\b", lambda match: i18n.message(match[0]), value)
    for source in ("the Unrivaled", "Spotlight", "Round", "Mighty"):
        value = re.sub(r"\b" + re.escape(source) + r"\b", lambda match: i18n.message(match[0]), value)
    for source in (" Appears", " Returns", " and ", " & ", ", "):
        value = value.replace(source, i18n.message(source))
    return names(value)


def event_text(value: str) -> str:
    result = translate(value)
    for pattern in (r"\blevel \d+\b", r"\b\d+ Battle Points\b", r"\b\d+ pieces? of clothing\b"):
        result = re.sub(pattern, lambda match: i18n.message(match[0]), result)
    result = re.sub(r"\b[Ss]hiny\b", lambda match: i18n.message(match[0]), result)
    for source in ("(Galar)", "Master Ball", " (an egg)", " (Gmax)", "can Gigantamax"):
        result = result.replace(source, i18n.message(source))
    result = re.sub(r"\(([^()]*)\)", lambda match: tr("presentation.parenthesized", "({text})",
                    text=i18n.message(match[1])) if i18n.message(match[1]) != match[1] else match[0], result)
    result = re.sub(r"\((\d{4}) (Feb|March|April) International Competition ([JM])\)",
                    lambda match: tr("presentation.competition", "({year} {month} International Competition {division})",
                                     year=match[1], month=i18n.message(match[2]), division=match[3]), result)
    return result


def event_label(game: str, card: dict) -> str:
    if i18n.locale() != "en" and game == "swsh" and card.get("group") == "Items":
        from pokeldn.swsh.events import item_pairs
        items = {item["id"]: item["name"] for item in SERVICE.names(game, "items")}
        return tr("presentation.reward_separator", ", ").join(
            f"{items.get(ident, tr('presentation.item_number', 'Item {number}', number=ident))} ×{quantity}"
            for ident, quantity in item_pairs(card["record"]))
    return event_text(card["label"])


def summary_text(value: str) -> str:
    """A stored/remote summary: quoted nicknames retain exactly what the player entered."""
    parts = []
    for number, part in enumerate(value.split(" · ")):
        if part.startswith(("'", "\u201c")) and part.endswith(("'", "\u201d")):
            parts.append(part)
        elif part.startswith("holding "):
            parts.append(tr("presentation.holding", "holding {item}", item=translate(part.removeprefix("holding "))))
        else:
            shown = event_text(part)
            if number == 0 and "-" in shown:
                species, _, form = shown.partition("-")
                localized = i18n.message(form)
                if localized == form:
                    localized = "-".join(i18n.message(piece) for piece in form.split("-"))
                shown = species + "-" + localized
            parts.append(shown)
    return " · ".join(parts)


def translate_app_log(line: str) -> str:
    """Only app-authored copy is localized; the log store and exported diagnostics stay raw."""
    return "[app] " + i18n.message(line[6:]) if line.startswith("[app] ") else line
