from types import SimpleNamespace

import pytest

pytest.importorskip("flet")

from gui.views.games import GamesView
from pokeldn.app.catalog import Field, offer


def test_saved_pokemon_offer_keeps_its_card_description():
    field = offer()
    view = SimpleNamespace(values={field.key: {"file": "pikachu.pk3", "species": 25, "legal": True}})
    assert GamesView.description(view, field) == field.help


def test_choice_card_includes_help_for_the_saved_selection():
    field = Field("--mode", "Mode", "choice", help="Choose a mode.",
                  choice_help=(("trade", "Trades Pokemon."),))
    view = SimpleNamespace(values={field.key: "trade"})
    assert GamesView.description(view, field) == "Choose a mode. Trades Pokemon."
