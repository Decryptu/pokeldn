"""The helper's "icon" names against file names in PokeAPI's sprite repository (sprites/items/,
sprites/ribbons/generation-viii/), listed from github.com/PokeAPI/sprites."""
import base64

import pytest

from pokeldn.swsh import gift_builder, wc8
from test_pokemon_service import service  # noqa: F401  (the PKHeX helper, built once)


@pytest.mark.parametrize("game, kind, name, icon", [
    ("swsh", "balls", "Poké Ball", "poke-ball"),           # the accent PKHeX's English name carries
    ("pla", "balls", "Gigaton Ball", "lagigaton-ball"),     # Legends Arceus's own balls
    ("frlg", "items", "Parlyz Heal", "paralyze-heal"),      # a Gen 3 id named after its later item
    ("frlg", "held", "Stick", "stick"),
    ("frlg", "items", "Itemfinder", "dowsing-machine"),
    ("sv", "held", "King’s Rock", "kings-rock"),
    ("sv", "held", "Upgrade", "up-grade"),
    ("sv", "held", "Health Feather", "health-wing"),
    ("swsh", "bag", "Master Ball", "master-ball"),
    ("swsh", "ribbons", "Classic", "classic-ribbon"),
])
def test_an_item_ball_or_ribbon_names_its_pokeapi_file(service, game, kind, name, icon):
    by_name = {n["name"]: n.get("icon") for n in service.names(game, kind)}
    assert by_name[name] == icon


def test_a_sword_card_carries_the_ribbons_picked_once_each(service):
    ribbons = {n["name"]: n["id"] for n in service.names("swsh", "ribbons")}
    picked = [ribbons["Classic"], ribbons["Birthday"], ribbons["Classic"]]
    record = gift_builder.record(gift_builder.blank(ribbons=picked))
    assert wc8.read(record)["ribbons"] == (ribbons["Classic"], ribbons["Birthday"])
    with pytest.raises(ValueError, match="A ribbon is 0 to 52"):
        gift_builder.record(gift_builder.blank(ribbons=[53]))        # the first mark
    service._ask({"cmd": "gift", "game": "swsh", "data": base64.b64encode(record).decode()})   # PKHeX's checks
