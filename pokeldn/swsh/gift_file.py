"""Sword/Shield's native WC8 component in a shared gift file. See docs/gifts.md."""

from pathlib import Path

from pokeldn import gifts, pokemon
from pokeldn.swsh import wc8


def validate(gift):
    if set(gift.variants) != {"swsh"}:
        raise ValueError("Sword/Shield gifts need exactly one swsh variant.")
    variant = gift.variants["swsh"]
    if set(variant.data) != {"wc8"} or variant.options:
        raise ValueError("Sword/Shield gifts contain one WC8 record and no options.")
    if not wc8.sealed(variant.data["wc8"]):
        raise ValueError("The WC8 record has an invalid size or checksum.")


def from_record(record, *, name="Sword/Shield gift"):
    return gifts.Gift("swsh", name, {"swsh": gifts.Variant({"wc8": bytes(record)})})


def record(gift):
    validate(gift)
    return gift.variants["swsh"].data["wc8"]


def export_native(gift, directory, *, build=None):
    if build is not None:
        raise ValueError("Sword/Shield gifts have no FRLG cartridge variant.")
    raw = record(gift)
    pokemon.SERVICE.validate_gift(raw)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Gift.wc8"
    path.write_bytes(raw)
    return (path,)
