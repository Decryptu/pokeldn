"""Language-pack text for game data and module messages, applied where a control shows it
[pokeldn.app.i18n, docs/plugins.md, Additional resources]. Records, summaries, settings, peer
messages and player input stay in English."""
import re
import time

from pokeldn import pokemon
from pokeldn.app import i18n
from pokeldn.app.i18n import t as tr

SENTENCE = re.compile(r"(?<=[.!?])\s+")


def date_time(seconds: float) -> str:
    return time.strftime(tr("presentation.date_time_format", "%d %b %Y, %H:%M"), time.localtime(seconds))


def translate(value: str) -> str:
    """A module's English text: the whole message, else each sentence, else the game terms in it."""
    if not value or i18n.locale() == "en":
        return value
    if (whole := i18n.message(value)) != value:
        return whole
    sentences = SENTENCE.split(value)
    if len(sentences) > 1 and any(i18n.message(s) != s for s in sentences):
        return " ".join(translate(s) for s in sentences)
    return i18n.terms(value)


def error_message(error: Exception | str) -> str:
    """An OSError names a path and keeps its text; any other error is a module message."""
    return str(error) if isinstance(error, OSError) else i18n.message(str(error))


def summary_text(value: str) -> str:
    """pokeldn.pokemon.summary as shown; a quoted nickname stays as the player typed it."""
    return " · ".join(part if part[:1] == "'" else translate(part) for part in value.split(" · "))


def summary_lines(value: str) -> tuple[str, str]:
    """A summary's species, level and shininess, then the rest."""
    parts = value.split(" · ")
    head = 3 if len(parts) > 2 and parts[2] == "shiny" else 2
    return summary_text(" · ".join(parts[:head])), summary_text(" · ".join(parts[head:]))


def summary(info: dict) -> str:
    """A display reply's summary in its own names; pokemon.summary alone reads the English ones."""
    return summary_text(pokemon.summary({key: value for key, value in info.items() if key != "canonical"}))


def gift_description(game, state, name):
    from pokeldn.app.gift_builder import module
    when, lines = module(game).describe(state, name)
    return translate(when), [translate(line) for line in lines]


def app_log(line: str) -> str:
    """Only the app's own [app] lines are shown translated; the log keeps what was written."""
    return "[app] " + i18n.message(line[6:]) if line.startswith("[app] ") else line


def flet_locale():
    """The pack's locale for Flet's own dialogs and pickers: language, script and region subtags."""
    import flet as ft
    language, *parts = i18n.locale().split("-")
    script = next((p.title() for p in parts if len(p) == 4), None)
    region = next((p.upper() for p in parts if len(p) == 2 or p.isdigit()), None)
    current = ft.Locale(language.lower(), region, script)
    return ft.LocaleConfiguration(supported_locales=[ft.Locale("en"), current], current_locale=current)


class DisplayService(pokemon.Service):
    """pokemon.SERVICE's PKHeX process asked for names in the selected pack's language; a record or
    file it keeps reads the English names under the reply's "canonical" (services/pkhex Describe)."""

    def __init__(self):
        super().__init__()
        self._caches: dict[str, dict] = {}

    @property
    def species_cache(self) -> dict:
        return self._caches.setdefault(i18n.locale(), {})

    @species_cache.setter
    def species_cache(self, value) -> None:
        self._caches = {}

    def _ask(self, request):
        language = i18n.locale()
        try:
            reply = pokemon.SERVICE._ask(request if language == "en" else {**request, "display_language": language})
        except pokemon.BuilderError as exc:
            raise pokemon.BuilderError(error_message(exc)) from exc
        if language == "en":
            return reply
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

    def close(self):
        pass


SERVICE = DisplayService()
