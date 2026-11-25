"""Emerald gifts in the shared .pokegift file (docs/gifts.md): one variant, "emerald", serving
every Emerald cartridge, since nothing in it names a ROM address."""

from pokeldn import gifts
from pokeldn.frlg.gift import mg_server, wonder_card
from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
from pokeldn.rse.constants import EMERALD_RULES

TARGET = "emerald"


def validate(gift):
    if set(gift.variants) != {TARGET}:
        raise ValueError('An Emerald gift has one variant, "emerald".')
    distribution(gift.variants[TARGET])


def distribution(variant):
    keys = set(variant.data)
    if not {"card", "ram_script"} <= keys or keys - {"card", "ram_script", "mevent"} or variant.options:
        raise ValueError("An Emerald gift is a Wonder Card, its delivery script and an optional Mystery Event.")
    card, script = variant.data["card"], variant.data["ram_script"]
    mevent = variant.data.get("mevent")
    if len(card) != wonder_card.WONDER_CARD_SIZE:
        raise ValueError(f"An Emerald Wonder Card is {wonder_card.WONDER_CARD_SIZE} bytes.")
    EMERALD_RULES.flag_for_flag_id(int.from_bytes(card[:2], "little"))
    if not 0 < len(script) <= mg_server.MysteryGiftServer.MAX_RAM_SCRIPT_SIZE:
        raise ValueError("The delivery script must contain 1 to 995 bytes.")
    try:
        mg_server.MysteryGiftServer(card, script, mevent=mevent, game=TARGET)
    except (mg_server.MysteryGiftServerError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    return MysteryGiftDistribution(bytes(card), bytes(script),
                                   mevent=None if mevent is None else bytes(mevent), game=TARGET)


def from_distribution(chosen, *, name):
    data = {"card": bytes(chosen.card), "ram_script": bytes(chosen.ram_script)}
    if chosen.mevent is not None:
        data["mevent"] = bytes(chosen.mevent)
    return gifts.Gift("rse", name, {TARGET: gifts.Variant(data)})
